"""Batched durable telemetry processing. One ordered detector per MVP deployment."""
import logging
import time
from datetime import datetime
from uuid import UUID
import psycopg
import redis
from psycopg.types.json import Jsonb
from . import config
from .db import connect, create_incident, close_pool
from .rules import evaluate
from .telemetry_policy import sample_result

logger = logging.getLogger(__name__)


class StreamReader:
    """Cache group readiness and recover pending work only when necessary."""
    def __init__(self, redis_client):
        self.redis = redis_client
        self.group_ready = False
        self.recover_pending = True
        self.claim_cursor = '0-0'
        self.next_claim = 0

    def ensure_group(self):
        if self.group_ready:
            return
        try:
            self.redis.xgroup_create(config.STREAM, config.GROUP, id='0', mkstream=True)
        except redis.ResponseError as exc:
            if 'BUSYGROUP' not in str(exc):
                raise
        self.group_ready = True

    def read(self):
        entries = []
        if self.recover_pending:
            pending = self.redis.xreadgroup(config.GROUP, 'detector-1',
                {config.STREAM: '0'}, count=config.TELEMETRY_BATCH_SIZE)
            entries = [item for _, batch in pending for item in batch if item[1]]
            self.recover_pending = bool(entries)
        if not entries and time.monotonic() >= self.next_claim:
            claimed = self.redis.xautoclaim(config.STREAM, config.GROUP, 'detector-1',
                10000, self.claim_cursor, count=config.TELEMETRY_BATCH_SIZE)
            self.claim_cursor, entries = claimed[0], claimed[1]
            self.next_claim = (0 if self.claim_cursor != '0-0' else time.monotonic() + 1)
        if not entries:
            batches = self.redis.xreadgroup(config.GROUP, 'detector-1',
                {config.STREAM: '>'}, count=config.TELEMETRY_BATCH_SIZE, block=100)
            entries = [item for _, batch in batches for item in batch]
        return entries

    def retry(self, error):
        # A failed process/ACK can leave our own deliveries pending. Redis may
        # also have restarted without its group; validate it on the next loop.
        self.recover_pending = True
        if isinstance(error, redis.RedisError):
            self.group_ready = False


def relay(r):
    # Redis may receive duplicates after a crash; the durable inbox deduplicates.
    with connect() as conn:
        rows = conn.execute("""
            SELECT o.event_id FROM telemetry_outbox o
            JOIN telemetry_inbox i USING(event_id)
            WHERE i.processed_at IS NULL AND
              (o.dispatched_at IS NULL OR o.dispatched_at<now()-interval '30 seconds')
            ORDER BY i.received_at,o.event_id LIMIT %s
            FOR UPDATE OF o SKIP LOCKED
        """, (config.TELEMETRY_BATCH_SIZE,)).fetchall()
        if not rows:
            return 0
        pipe = r.pipeline(transaction=False)
        for row in rows:
            pipe.xadd(config.STREAM, {'event_id': str(row['event_id'])})
        pipe.execute()
        conn.cursor().executemany(
            'UPDATE telemetry_outbox SET dispatched_at=clock_timestamp() WHERE event_id=%s',
            [(row['event_id'],) for row in rows])
        return len(rows)


def process_batch(event_ids):
    ids = sorted({UUID(str(value)) for value in event_ids})
    if not ids:
        return {}
    outcomes = {}
    with connect() as conn:
        candidates = conn.execute(
            'SELECT DISTINCT trip_id FROM telemetry_inbox WHERE event_id=ANY(%s) AND processed_at IS NULL',
            (ids,)).fetchall()
        if not candidates:
            return outcomes
        # Stable lock order: trips -> inbox -> incidents; API/SOS lock trip first.
        trips = {row['id']: row for row in conn.execute(
            'SELECT id,status,last_seen,detector_state FROM trips WHERE id=ANY(%s) ORDER BY id FOR UPDATE',
            ([row['trip_id'] for row in candidates],)).fetchall()}
        events = conn.execute("""
            SELECT i.*, NOT ST_DWithin(t.route_geom::geography,
              ST_SetSRID(ST_MakePoint((i.payload->>'lon')::float8,
                (i.payload->>'lat')::float8),4326)::geography,
              GREATEST(100,2*(i.payload->>'accuracy_m')::float8)) AS outside
            FROM telemetry_inbox i JOIN trips t ON t.id=i.trip_id
            WHERE i.event_id=ANY(%s) AND i.processed_at IS NULL
            ORDER BY i.received_at,i.event_id FOR UPDATE OF i
        """, (ids,)).fetchall()
        updated = {}
        for event in events:
            trip = trips[event['trip_id']]
            point = event['payload']
            observed = datetime.fromisoformat(point['event_time'].replace('Z', '+00:00'))
            result = sample_result(observed, event['received_at'], trip['last_seen'],
                                   trip['status'] == 'ACTIVE', config.TELEMETRY_FRESH_SECONDS)
            outcomes.setdefault(result, []).append(event['event_id'])
            if result != 'APPLIED':
                continue
            state, flags = evaluate(trip['detector_state'], point, event['outside'], observed.timestamp())
            previous_flags = set(trip['detector_state'].get('active_flags', []))
            state['active_flags'] = flags
            trip.update(last_lat=point['lat'], last_lon=point['lon'], last_seen=observed, detector_state=state)
            updated[trip['id']] = trip
            for kind in set(flags) - previous_flags:
                thresholds = {'STOP': config.STOP_SECONDS, 'SPEED': config.SPEED_SECONDS,
                              'DEVIATION': config.DEVIATION_SECONDS}
                evidence = {'speed_kmh': point['speed_kmh'], 'accuracy_m': point['accuracy_m'],
                            'observed_at': point['event_time'], 'outside_route': event['outside'],
                            'observed_duration_seconds': max(0, observed.timestamp() - state[kind + '_since']),
                            'threshold_seconds': thresholds[kind]}
                evidence.update({'speed_threshold_kmh': config.SPEED_LIMIT_KMH + 10} if kind == 'SPEED' else
                                {'stop_threshold_kmh': 3} if kind == 'STOP' else
                                {'route_tolerance_m': max(100, 2 * point['accuracy_m'])})
                create_incident(conn.cursor(), trip['id'], kind, 2,
                    f'{kind}: điều kiện kéo dài đủ ngưỡng cấu hình.',
                    evidence)
        if updated:
            conn.cursor().executemany(
                'UPDATE trips SET last_lat=%s,last_lon=%s,last_seen=%s,detector_state=%s,version=version+1 WHERE id=%s',
                [(t['last_lat'], t['last_lon'], t['last_seen'], Jsonb(t['detector_state']), t['id'])
                 for t in updated.values()])
            # Per-trip revisions avoid a global write lock on the GPS hot path.
        for result, event_group in outcomes.items():
            conn.execute('UPDATE telemetry_inbox SET processed_at=clock_timestamp(),processing_result=%s WHERE event_id=ANY(%s)',
                         (result, event_group))
        # Keep inbox for audit/idempotency; remove completed retry scheduling rows.
        conn.execute('DELETE FROM telemetry_outbox WHERE event_id=ANY(%s)',
                     ([event['event_id'] for event in events],))
    return {kind: len(values) for kind, values in outcomes.items()}


def process(event_id):
    return process_batch([event_id])


def watchdog():
    with connect() as conn:
        rows = conn.execute("""
            SELECT t.id,t.last_received_at,
              EXTRACT(EPOCH FROM now()-COALESCE(t.last_received_at,t.created_at)) AS missing_seconds
            FROM trips t WHERE t.status='ACTIVE'
              AND COALESCE(t.last_received_at,t.created_at)<now()-(%s*interval '1 second')
              AND NOT EXISTS (SELECT 1 FROM incidents i WHERE i.trip_id=t.id
                  AND i.kind='GPS_LOST' AND i.status='OPEN')
            ORDER BY t.id LIMIT 1000 FOR UPDATE OF t SKIP LOCKED
        """, (config.GPS_LOST_SECONDS,)).fetchall()
        for trip in rows:
            create_incident(conn.cursor(), trip['id'], 'GPS_LOST', 2,
                'Không nhận GPS mới; nguyên nhân chưa xác minh.',
                {'last_received_at': str(trip['last_received_at']),
                 'missing_seconds': float(trip['missing_seconds']), 'threshold_seconds': config.GPS_LOST_SECONDS})
    return len(rows)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    r = redis.Redis.from_url(config.REDIS_URL, decode_responses=True,
                            socket_connect_timeout=3, socket_timeout=5)
    try:
        with psycopg.connect(config.DATABASE_URL, autocommit=True) as guard:
            if not guard.execute('SELECT pg_try_advisory_lock(730012)').fetchone()[0]:
                raise SystemExit('Detector khác đang chạy; MVP dùng một detector xử lý theo lô.')
            logger.info('Detector ready batch_size=%s', config.TELEMETRY_BATCH_SIZE)
            next_watchdog = 0
            reader = StreamReader(r)
            while True:
                guard.execute('SELECT 1')
                # GPS loss is a PostgreSQL check. A failed Redis command must
                # never skip it; keep its error/retry path separate as well.
                if time.monotonic() >= next_watchdog:
                    try:
                        watchdog()
                    except psycopg.Error as exc:
                        logger.warning('GPS watchdog retry error_type=%s', type(exc).__name__)
                    next_watchdog = time.monotonic() + config.WATCHDOG_INTERVAL_SECONDS
                try:
                    reader.ensure_group()
                    relay(r)
                    entries = reader.read()
                    if entries:
                        process_batch([fields['event_id'] for _, fields in entries])
                        message_ids = [message_id for message_id, _ in entries]
                        pipe = r.pipeline(transaction=True)
                        pipe.xack(config.STREAM, config.GROUP, *message_ids)
                        pipe.xdel(config.STREAM, *message_ids)
                        pipe.execute()
                except (redis.RedisError, psycopg.Error) as exc:
                    reader.retry(exc)
                    logger.warning('Detector retry error_type=%s', type(exc).__name__)
                    time.sleep(2)
    finally:
        r.close()
        close_pool()


if __name__ == '__main__':
    main()
