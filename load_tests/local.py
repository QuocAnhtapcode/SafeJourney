"""One-command isolated local stack, seed and load run. No production targets."""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import math
from datetime import datetime, timezone
from uuid import uuid4
import httpx

ROOT = Path(__file__).resolve().parents[1]
DB_URL = 'postgresql://loadtest:local_loadtest_only@127.0.0.1:25432/safejourney_loadtest'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vehicles', type=int, default=1000)
    parser.add_argument('--ramp', type=float, default=30)
    parser.add_argument('--warmup', type=float, default=30)
    parser.add_argument('--duration', type=float, default=120)
    parser.add_argument('--drain', type=float, default=60)
    parser.add_argument('--operator-viewers', type=int, default=5)
    parser.add_argument('--viewer-interval', type=float, default=1)
    parser.add_argument('--api-workers', type=int, default=1)
    parser.add_argument('--allow-local-loadtest', action='store_true', required=True)
    args = parser.parse_args()
    if not 1 <= args.api_workers <= 4:
        parser.error('api-workers must be 1–4')
    if not (1 <= args.vehicles <= 10000 and 0 <= args.operator_viewers <= 20):
        parser.error('vehicles must be 1–10000 and operator-viewers 0–20')
    if not all(math.isfinite(getattr(args, name)) for name in ('ramp','warmup','duration','drain','viewer_interval')):
        parser.error('All time parameters must be finite')
    if args.ramp < 0 or args.warmup < 3 or args.duration <= 0 or args.drain < 0 or args.viewer_interval <= 0:
        parser.error('ramp/drain >=0, warmup >=3, duration/viewer-interval >0')
    # Do not start or stop someone else's API on the dedicated test port.
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', 18000))
        except OSError:
            parser.error('Port 18000 is in use. Stop the previous test API first.')
    run_id = 'run-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:4]
    folder = ROOT/'.work'/'loadtest'/run_id
    folder.mkdir(parents=True)
    env = dict(os.environ)
    env.update(DATABASE_URL=DB_URL, LOADTEST_DATABASE_URL=DB_URL,
               REDIS_URL='redis://127.0.0.1:26379/0', ALLOWED_ORIGINS='http://localhost:5173',
               COOKIE_SECURE='false', LLM_MODE='mock', GPS_LOST_SECONDS='60',
               STOP_SECONDS='180', DEVIATION_SECONDS='45', SPEED_SECONDS='10',
               LOADTEST_PASSWORD=secrets.token_urlsafe(24), PYTHONUNBUFFERED='1',
               PYTHONIOENCODING='utf-8', DB_POOL_MIN='2', DB_POOL_MAX='16',
               DB_POOL_TIMEOUT='5', DB_POOL_MAX_WAITING='64',
               TELEMETRY_BATCH_SIZE='200', TELEMETRY_FRESH_SECONDS='30',
               WATCHDOG_INTERVAL_SECONDS='5', SPEED_LIMIT_KMH='80')
    # Ensure inherited remote checkpoint/provider settings cannot redirect tests.
    env['CHECKPOINT_DATABASE_URL'] = DB_URL
    env.pop('RUN_DEMO_TESTS', None)
    processes, logs = [], []
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

    def call(command, cwd=ROOT):
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', creationflags=flags)
        print(result.stdout, end='', flush=True)
        if result.returncode:
            print(result.stderr, end='', flush=True)
            result.check_returncode()
        return result

    def start(name, command):
        log = (folder/f'{name}.log').open('w', encoding='utf-8')
        logs.append(log)
        process = subprocess.Popen(command, cwd=ROOT/'backend', env=env,
                                   stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        processes.append(process)

    try:
        call(['docker', 'compose', '-f', str(ROOT/'load_tests/compose.yaml'), 'up', '-d', '--wait'])
        call([sys.executable, '-m', 'app.db'], ROOT/'backend')
        # The runner requires its own DB to contain no other ACTIVE trips. Never
        # silently alter another fixture/run; use a fresh or finished load stack.
        import psycopg
        with psycopg.connect(DB_URL) as conn:
            if conn.execute("SELECT count(*) FROM trips WHERE status='ACTIVE'").fetchone()[0]:
                raise RuntimeError('Dedicated test DB has ACTIVE trips; finish the earlier test run before starting')
        call([sys.executable, '-m', 'load_tests.seed', '--run-id', run_id,
              '--vehicles', str(args.vehicles), '--allow-local-loadtest'])
        start('api', [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1',
                      '--port', '18000', '--workers', str(args.api_workers), '--no-access-log'])
        with httpx.Client(trust_env=False, timeout=1) as client:
            for _ in range(60):
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError('API exited; inspect the run log')
                try:
                    if client.get('http://127.0.0.1:18000/api/health').status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.5)
            else:
                raise RuntimeError('API did not become ready')
        start('detector', [sys.executable, '-m', 'app.worker'])
        start('planner', [sys.executable, '-m', 'app.planner'])
        time.sleep(2)
        if any(p.poll() is not None for p in processes):
            raise RuntimeError('A service exited; inspect the run logs')
        report_path = ROOT/'load_tests/reports'/f'{run_id}.json'
        command = [sys.executable, '-m', 'load_tests.run', '--run-id', run_id,
                   '--vehicles', str(args.vehicles), '--ramp', str(args.ramp),
                   '--warmup', str(args.warmup), '--duration', str(args.duration),
                   '--drain', str(args.drain), '--operator-viewers', str(args.operator_viewers),
                   '--viewer-interval', str(args.viewer_interval), '--output', str(report_path),
                   '--allow-local-loadtest']
        run_process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                       errors='replace', creationflags=flags)
        processes.append(run_process)
        with (folder/'runner.log').open('w', encoding='utf-8') as run_log:
            for line in run_process.stdout:
                run_log.write(line)
                run_log.flush()
                print(line, end='', flush=True)
        result_code = run_process.wait()
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding='utf-8'))
            report['service_configuration'] = {'api_workers': args.api_workers, 'detectors': 1,
                'planners': 1, 'pool_max_per_process': 16, 'telemetry_batch_size': 200,
                'llm_mode': 'mock', 'docker_services': 'PostGIS 16-3.6, Redis 7.4'}
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        elif result_code:
            # Setup failures have no timed workload: preserve evidence, never a
            # fabricated benchmark with zero failures or a misleading PASS.
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps({'schema_version': 3, 'run_id': run_id,
                'status': 'ABORTED', 'passed': False, 'exit_code': result_code,
                'note': 'No completed timed report; inspect service and runner logs.'}, indent=2)+'\n', encoding='utf-8')
        return result_code
    finally:
        # Only terminate process handles launched by this invocation. Compose
        # database/Redis and synthetic evidence remain available for inspection.
        for process in reversed(processes):
            if process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   capture_output=True, creationflags=flags)
                else:
                    process.terminate()
                process.wait(timeout=15)
        for log in logs:
            log.close()
        print(f'Service logs: {folder}; database/Redis kept for inspection.', flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
