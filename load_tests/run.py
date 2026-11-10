"""Open-loop authenticated telemetry load, limited to the local load-test stack."""
import argparse
import asyncio
import hashlib
import json
import os
import platform
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import aiohttp
import psycopg
from psycopg.rows import dict_row

from .common import (distribution_ms, driver_id, phase_at, prefix, scheduled_events,
                     trip_id, validate_base_url, validate_database_url, source_fingerprint)
from .http_client import LoadClient


@dataclass
class Measurements:
    scheduled: int = 0
    sent: int = 0
    accepted: int = 0
    dropped_late: int = 0
    dropped_capacity: int = 0
    statuses: Counter = field(default_factory=Counter)
    errors: Counter = field(default_factory=Counter)
    latency: list = field(default_factory=list)
    successful_latency: list = field(default_factory=list)
    schedule_latency: list = field(default_factory=list)
    scheduling_lag: list = field(default_factory=list)

    def report(self):
        failed = self.sent - self.accepted
        dropped = self.dropped_late + self.dropped_capacity
        return {
            'scheduled': self.scheduled, 'sent': self.sent, 'accepted': self.accepted,
            'failed': failed, 'error_rate': failed / self.sent if self.sent else None,
            'dropped_late': self.dropped_late, 'dropped_capacity': self.dropped_capacity,
            'dropped_rate': dropped / self.scheduled if self.scheduled else None,
            'http_statuses': dict(self.statuses), 'transport_errors': dict(self.errors),
            'request_latency_ms': distribution_ms(self.latency),
            'successful_request_latency_ms': distribution_ms(self.successful_latency),
            'schedule_to_response_ms': distribution_ms(self.schedule_latency),
            'scheduling_lag_ms': distribution_ms(self.scheduling_lag),
        }


def db_connect(url):
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=5,
                           options='-c statement_timeout=15000')


async def wait_until(deadline, *, clock=time.perf_counter, sleep=asyncio.sleep):
    # Windows asyncio timers may wake before a perf_counter deadline. Recheck so
    # request latency cannot exceed schedule-to-response due to an early send.
    while (remaining := deadline - clock()) > 0:
        await sleep(max(remaining, .001))


def database_snapshot(url, namespace, received_from=None, received_until=None, *, details=True):
    where = 'trip_id LIKE %s'
    params = [namespace + 'trip-%']
    if received_from is not None:
        where += ' AND received_at >= %s AND received_at < %s'
        params.extend([received_from, received_until])
    with db_connect(url) as conn:
        if not details:
            row = conn.execute(f"""SELECT count(*) AS received,
              count(*) FILTER (WHERE processed_at IS NOT NULL) AS processed,
              count(*) FILTER (WHERE processed_at IS NULL) AS pending,
              COALESCE(max(extract(epoch FROM (clock_timestamp()-received_at)))
                  FILTER (WHERE processed_at IS NULL),0) AS oldest_pending_seconds
              FROM telemetry_inbox WHERE {where}""", params).fetchone()
            row['oldest_pending_seconds'] = float(row['oldest_pending_seconds'])
            return row
        row = conn.execute(f"""SELECT count(*) AS received,
          count(*) FILTER (WHERE processed_at IS NOT NULL) AS processed,
          count(*) FILTER (WHERE processed_at IS NULL) AS pending,
          COALESCE(max(extract(epoch FROM (clock_timestamp()-received_at)))
              FILTER (WHERE processed_at IS NULL),0) AS oldest_pending_seconds,
          percentile_cont(ARRAY[0.50,0.95,0.99]) WITHIN GROUP
            (ORDER BY extract(epoch FROM (processed_at-received_at))*1000)
            FILTER (WHERE processed_at IS NOT NULL) AS processing_latency_ms
          FROM telemetry_inbox WHERE {where}""", params).fetchone()
        has_result = conn.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='telemetry_inbox' AND column_name='processing_result'").fetchone()
        row['processing_results'] = (dict((r['result'], r['n']) for r in conn.execute(
            f"SELECT COALESCE(processing_result,'pending') AS result,count(*) AS n FROM telemetry_inbox WHERE {where} GROUP BY 1", params))
            if has_result else None)
        row['incidents_by_kind'] = dict((r['kind'], r['n']) for r in conn.execute(
            'SELECT kind,count(*) AS n FROM incidents WHERE trip_id LIKE %s GROUP BY kind',
            (namespace+'trip-%',)))
    latencies = row.pop('processing_latency_ms')
    row['received_to_processed_ms'] = dict(zip(['p50', 'p95', 'p99'], latencies or [None]*3))
    row['oldest_pending_seconds'] = float(row['oldest_pending_seconds'])
    return row


def prepare_run(url, namespace, vehicle_count):
    with db_connect(url) as conn:
        rows = conn.execute("SELECT id,status FROM trips WHERE id LIKE %s", (namespace+'trip-%',)).fetchall()
        if len(rows) != vehicle_count or any(r['status'] != 'PLANNED' for r in rows):
            raise ValueError('Seed a new run-id with the same vehicle count; all trips must be PLANNED')
        if conn.execute('SELECT 1 FROM telemetry_inbox WHERE trip_id LIKE %s LIMIT 1', (namespace+'trip-%',)).fetchone():
            raise ValueError('This run-id already contains telemetry. Seed a fresh run-id')
        # Authentication is outside timed load; reset GPS watchdog start after login.
        conn.execute("UPDATE trips SET status='ACTIVE',created_at=clock_timestamp(),last_received_at=clock_timestamp() WHERE id LIKE %s", (namespace+'trip-%',))


def finish_trips(url, namespace):
    with db_connect(url) as conn:
        conn.execute("UPDATE trips SET status='FINISHED' WHERE id LIKE %s", (namespace+'trip-%',))


async def login_fleet(client, url, args, password):
    gate = asyncio.Semaphore(args.login_concurrency)
    tokens = [None] * args.vehicles

    async def login_one(i):
        async with gate:
            try:
                response = await client.post('/api/login', json={
                    'username': driver_id(args.run_id, i), 'password': password}, timeout=args.login_timeout)
            except (httpx.HTTPError, aiohttp.ClientError, TimeoutError) as exc:
                print(f'Login preparation failed: synthetic driver index={i}, error_type={type(exc).__name__}', flush=True)
                raise
            if response.status_code != 200:
                raise RuntimeError(f'Login failed for synthetic driver index {i}: HTTP {response.status_code}')
            token = response.cookies.get('journey_session')
            if not token:
                raise RuntimeError('Login returned no journey_session cookie')
            tokens[i] = token

    # Verify API connects to the exact database BEFORE sending the other 999 logins.
    await login_one(0)
    with db_connect(url) as conn:
        valid = conn.execute('SELECT 1 FROM sessions WHERE token_hash=%s AND user_id=%s',
                             (hashlib.sha256(tokens[0].encode()).hexdigest(), driver_id(args.run_id, 0))).fetchone()
    if not valid:
        raise RuntimeError('API and load-test database do not match; no load was generated')
    tasks = [asyncio.create_task(login_one(i)) for i in range(1, args.vehicles)]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    client.cookies.clear()
    own = await client.get('/api/trips', headers={'Cookie': f'journey_session={tokens[0]}'})
    if own.status_code != 200 or {r['id'] for r in own.json()} != {trip_id(args.run_id, 0)}:
        raise RuntimeError('Driver scoped trip read failed')
    if args.vehicles > 1:
        forbidden = await client.post(f'/api/trips/{trip_id(args.run_id, 1)}/telemetry',
                                     headers={'Cookie': f'journey_session={tokens[0]}'}, json=point(0))
        if forbidden.status_code not in (403, 404):
            raise RuntimeError('RBAC preflight failed: driver can write another vehicle')
    return tokens


def point(seq):
    # Triangular travel stays on the fixture route; every fresh event has a UUID.
    pos = seq % 200
    lat = 10.771 + .00008 * (pos if pos <= 100 else 200-pos)
    return {'event_id': str(uuid4()), 'seq': seq, 'lat': lat, 'lon': 106.7,
            'accuracy_m': 8, 'speed_kmh': 30,
            'event_time': datetime.now(timezone.utc).isoformat()}


def evaluate_gates(report, args):
    steady = report['http']['steady']
    db = report['database']['steady_received_window']
    all_db = report['database']['after_drain']
    gates = {
        'sent_steady_events': steady['sent'] > 0,
        'http_error_rate': steady['error_rate'] is not None and steady['error_rate'] <= args.max_error_rate,
        'no_dropped_arrivals': steady['dropped_rate'] == 0,
        'http_p95': steady['request_latency_ms']['p95'] is not None and steady['request_latency_ms']['p95'] <= args.max_http_p95_ms,
        'database_processing_p95': db['received_to_processed_ms']['p95'] is not None and db['received_to_processed_ms']['p95'] <= args.max_processing_p95_ms,
        'backlog_drained': all_db['pending'] == 0,
        'accepted_durable': all_db['received'] >= sum(p['accepted'] for p in report['http'].values()),
        'no_incidents_in_normal_scenario': not all_db.get('incidents_by_kind', {}),
    }
    results = all_db['processing_results']
    # Old schema can mark stale points processed without applying them. Do not claim
    # risk-detection capacity unless actual application outcomes are measurable.
    gates['processing_outcomes_available'] = results is not None
    gates['all_points_applied'] = results is not None and sum(n for result, n in results.items() if result.lower() != 'applied') == 0
    viewer_steady = report.get('operator_http', {}).get('steady')
    if viewer_steady is not None:
        gates['operator_http_no_drops'] = viewer_steady['dropped_rate'] == 0
        gates['operator_http_error_rate'] = viewer_steady['error_rate'] is not None and viewer_steady['error_rate'] <= args.max_error_rate
        gates['operator_http_p95'] = viewer_steady['request_latency_ms']['p95'] is not None and viewer_steady['request_latency_ms']['p95'] <= args.max_http_p95_ms
    return gates


async def run(args, url, password):
    measured_source = source_fingerprint()
    namespace = prefix(args.run_id)
    metrics = {phase: Measurements() for phase in ['ramp', 'warmup', 'steady']}
    viewer_metrics = {phase: Measurements() for phase in ['ramp', 'warmup', 'steady']}
    pending_series = []
    monitor_errors = Counter()
    tasks = set()
    stop_monitor = asyncio.Event()
    started = False
    max_inflight_seen = 0
    total_seconds = args.ramp + args.warmup + args.duration
    timeout = httpx.Timeout(args.timeout)
    limits = httpx.Limits(max_connections=args.max_inflight, max_keepalive_connections=args.max_inflight)
    transport = (LoadClient(args.base_url, args.timeout, args.max_inflight) if args.http_client == 'aiohttp'
                 else httpx.AsyncClient(base_url=args.base_url, timeout=timeout, limits=limits,
                                       trust_env=False, follow_redirects=False))
    async with transport as client:
        login_start = time.perf_counter()
        print(f'Logging in {args.vehicles} real synthetic driver accounts...', flush=True)
        tokens = await login_fleet(client, url, args, password)
        operator_token = None
        if args.operator_viewers:
            response = await client.post('/api/login', json={'username': namespace+'operator', 'password': password}, timeout=args.login_timeout)
            if response.status_code != 200 or not response.cookies.get('journey_session'):
                raise RuntimeError('Synthetic operator login failed')
            operator_token = response.cookies.get('journey_session')
            client.cookies.clear()
        login_seconds = time.perf_counter() - login_start
        prepare_run(url, namespace, args.vehicles)
        start_wall = datetime.now(timezone.utc)
        start = time.perf_counter()
        started = True

        async def send(due, vehicle, seq, metric):
            sent = time.perf_counter()
            metric.sent += 1
            metric.scheduling_lag.append(max(0, sent-start-due))
            accepted = False
            try:
                response = await client.post(f'/api/trips/{trip_id(args.run_id, vehicle)}/telemetry',
                                             headers={'Cookie': f'journey_session={tokens[vehicle]}'}, json=point(seq))
                metric.statuses[str(response.status_code)] += 1
                if response.status_code == 200:
                    body = response.json()
                    accepted = body.get('status') == 'durable' and not body.get('duplicate', False)
                if accepted:
                    metric.accepted += 1
            except (httpx.HTTPError, aiohttp.ClientError, TimeoutError, ValueError) as exc:
                metric.errors[type(exc).__name__] += 1
            finally:
                done = time.perf_counter()
                metric.latency.append(done-sent)
                metric.schedule_latency.append(done-start-due)
                if accepted:
                    metric.successful_latency.append(done-sent)

        async def monitor():
            while not stop_monitor.is_set():
                try:
                    snap = await asyncio.to_thread(database_snapshot, url, namespace, details=False)
                    pending_series.append({'elapsed_seconds': round(time.perf_counter()-start, 3),
                                           'received': snap['received'], 'processed': snap['processed'],
                                           'pending': snap['pending'], 'oldest_pending_seconds': snap['oldest_pending_seconds']})
                    print(f"t={time.perf_counter()-start:.0f}s received={snap['received']} pending={snap['pending']}", flush=True)
                except psycopg.Error as exc:
                    monitor_errors[type(exc).__name__] += 1
                try:
                    await asyncio.wait_for(stop_monitor.wait(), timeout=args.sample_interval)
                except asyncio.TimeoutError:
                    pass

        async def viewer_request(path, due, metric):
            sent = time.perf_counter()
            metric.sent += 1
            metric.scheduling_lag.append(max(0, sent-start-due))
            accepted = False
            try:
                response = await client.get(path, headers={'Cookie': f'journey_session={operator_token}'})
                metric.statuses[str(response.status_code)] += 1
                accepted = response.status_code == 200
                if accepted:
                    metric.accepted += 1
            except (httpx.HTTPError, aiohttp.ClientError, TimeoutError) as exc:
                metric.errors[type(exc).__name__] += 1
            finally:
                done = time.perf_counter()
                metric.latency.append(done-sent)
                metric.schedule_latency.append(done-start-due)
                if accepted:
                    metric.successful_latency.append(done-sent)

        async def viewer(index):
            due = index * args.viewer_interval / args.operator_viewers
            paths = ['/api/trips?include_route=false&active_only=true', '/api/incidents?limit=100', '/api/area-alerts']
            while due < total_seconds:
                await wait_until(start+due)
                metric = viewer_metrics[phase_at(due, args.ramp, args.warmup)]
                metric.scheduled += len(paths)
                if time.perf_counter()-start-due > args.max_schedule_lag:
                    metric.dropped_late += len(paths)
                else:
                    await asyncio.gather(*(viewer_request(path, due, metric) for path in paths))
                due += args.viewer_interval

        monitor_task = asyncio.create_task(monitor())
        viewer_tasks = [asyncio.create_task(viewer(i)) for i in range(args.operator_viewers)]
        try:
            for due, vehicle, seq in scheduled_events(args.vehicles, args.interval, args.ramp, total_seconds):
                await wait_until(start+due)
                metric = metrics[phase_at(due, args.ramp, args.warmup)]
                metric.scheduled += 1
                lag = time.perf_counter()-start-due
                if lag > args.max_schedule_lag:
                    metric.dropped_late += 1
                elif len(tasks) >= args.max_inflight:
                    metric.dropped_capacity += 1
                else:
                    task = asyncio.create_task(send(due, vehicle, seq, metric))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                    max_inflight_seen = max(max_inflight_seen, len(tasks))
                # Yield even when overdue; the producer must not starve senders.
                await asyncio.sleep(0)
            await wait_until(start+total_seconds)
            await asyncio.gather(*list(tasks))
            await asyncio.gather(*viewer_tasks)
            drain_start = time.perf_counter()
            while True:
                after_drain = await asyncio.to_thread(database_snapshot, url, namespace, details=False)
                if after_drain['pending'] == 0 or time.perf_counter()-drain_start >= args.drain:
                    break
                await asyncio.sleep(min(1, max(.01, args.drain-(time.perf_counter()-drain_start))))
            drain_seconds = time.perf_counter()-drain_start
            after_drain = await asyncio.to_thread(database_snapshot, url, namespace)
            steady_from = start_wall + timedelta(seconds=args.ramp+args.warmup)
            steady_until = steady_from + timedelta(seconds=args.duration)
            steady_db = await asyncio.to_thread(database_snapshot, url, namespace, steady_from, steady_until)
        finally:
            for task in tasks:
                task.cancel()
            for task in viewer_tasks:
                task.cancel()
            await asyncio.gather(*list(tasks), return_exceptions=True)
            await asyncio.gather(*viewer_tasks, return_exceptions=True)
            stop_monitor.set()
            await monitor_task
            if started:
                await asyncio.to_thread(finish_trips, url, namespace)
    report = {
        'schema_version': 3, 'run_id': args.run_id, 'started_at_utc': start_wall.isoformat(),
        'measured_source': measured_source,
        'finished_at_utc': datetime.now(timezone.utc).isoformat(), 'scenario': 'normal_telemetry',
        'environment': {'python': platform.python_version(), 'os': platform.system(),
                        'logical_cpus': os.cpu_count(), 'target': 'local-isolated-port-18000'},
        'configuration': {key: value for key, value in vars(args).items() if key not in ('base_url', 'output')},
        'target_steady_requests_per_second': args.vehicles / args.interval,
        'observed_steady_sent_per_second': metrics['steady'].sent / args.duration,
        'observed_steady_accepted_per_second': metrics['steady'].accepted / args.duration,
        'login_seconds': round(login_seconds, 3), 'drain_seconds': round(drain_seconds, 3),
        'max_inflight_observed': max_inflight_seen,
        'http': {phase: metric.report() for phase, metric in metrics.items()},
        'operator_http': {phase: metric.report() for phase, metric in viewer_metrics.items()} if args.operator_viewers else {},
        'database': {'after_drain': after_drain, 'steady_received_window': steady_db,
                     'backlog_samples': pending_series, 'monitor_errors': dict(monitor_errors)},
        'measurement_notes': [
            'Scheduler rechecks the monotonic deadline after each timer wake; no planned early sends.',
            'Operator trip reads use active_only=true; historical trips are excluded from the live fleet list.',
            'HTTP phase is based on planned arrival; database steady phase is based on server received_at.',
            'Request latency includes network/client pool wait; schedule-to-response includes scheduler delay.',
            'Processed does not mean applied; inspect processing_results, including stale/out-of-order.',
            'No request retries. A timeout may still have committed; DB received may exceed HTTP accepted.',
            'Optional operators poll 3 HTTP endpoints using a real operator session; no browser render/WebSocket fanout.',
            'Normal telemetry and optional reads only: no LLM, SOS or human approval load.',
            'Client and services on one machine compete for CPU; this is a local baseline, not production capacity.'
        ],
    }
    report['gates'] = evaluate_gates(report, args)
    report['gates']['source_unchanged_during_run'] = measured_source == source_fingerprint()
    report['passed'] = all(report['gates'].values()) and not monitor_errors
    return report


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--allow-local-loadtest', action='store_true', required=True)
    parser.add_argument('--base-url', default='http://127.0.0.1:18000')
    parser.add_argument('--http-client', choices=['aiohttp', 'httpx'], default='aiohttp')
    parser.add_argument('--vehicles', type=int, default=1000)
    parser.add_argument('--interval', type=float, default=3)
    parser.add_argument('--ramp', type=float, default=30)
    parser.add_argument('--warmup', type=float, default=30)
    parser.add_argument('--duration', type=float, default=120)
    parser.add_argument('--drain', type=float, default=60)
    parser.add_argument('--timeout', type=float, default=5)
    parser.add_argument('--max-inflight', type=int, default=256)
    parser.add_argument('--login-concurrency', type=int, default=4)
    parser.add_argument('--login-timeout', type=float, default=30)
    parser.add_argument('--operator-viewers', type=int, default=0)
    parser.add_argument('--viewer-interval', type=float, default=5)
    parser.add_argument('--max-schedule-lag', type=float, default=.25)
    parser.add_argument('--sample-interval', type=float, default=5)
    parser.add_argument('--max-error-rate', type=float, default=.001)
    parser.add_argument('--max-http-p95-ms', type=float, default=250)
    parser.add_argument('--max-processing-p95-ms', type=float, default=2000)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    for name in ['interval', 'duration', 'timeout', 'max_schedule_lag', 'sample_interval',
                 'max_http_p95_ms', 'max_processing_p95_ms', 'viewer_interval', 'login_timeout']:
        if not 0 < getattr(args, name) < float('inf'):
            parser.error(f'{name} must be finite and positive')
    if not (0 <= args.ramp < float('inf') and args.interval <= args.warmup < float('inf') and 0 <= args.drain < float('inf')):
        parser.error('ramp/drain >=0 and warmup >=interval; all finite')
    if not (1 <= args.vehicles <= 10000 and 1 <= args.max_inflight <= 10000
            and 1 <= args.login_concurrency <= 32 and 0 <= args.max_error_rate <= 1
            and 0 <= args.operator_viewers <= 20):
        parser.error('Invalid vehicles, concurrency or error-rate bounds')
    try:
        prefix(args.run_id)
        args.base_url = validate_base_url(args.base_url)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main():
    args = arguments()
    try:
        url = validate_database_url(os.environ.get('LOADTEST_DATABASE_URL', ''))
        password = os.environ.get('LOADTEST_PASSWORD', '')
        if not 12 <= len(password) <= 128:
            raise ValueError('Set LOADTEST_PASSWORD to the same value used by seed')
        report = asyncio.run(run(args, url, password))
    except (ValueError, RuntimeError, psycopg.Error, httpx.HTTPError, aiohttp.ClientError, TimeoutError) as exc:
        # Exception messages can contain URLs/credentials. Print only class here.
        print(f'Load run aborted ({type(exc).__name__}); check local services, fixture/run-id, credentials and configuration. No pass was recorded.')
        raise SystemExit(2) from None
    output = args.output or Path(__file__).resolve().parent / 'reports' / f'{args.run_id}.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise SystemExit('Report path already exists; choose a different --output')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=float)+'\n', encoding='utf-8')
    print(f"Report: {output.resolve()}\nResult: {'PASS' if report['passed'] else 'FAIL'}; inspect gates and backlog.")
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
