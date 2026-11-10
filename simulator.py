"""Send synthetic GPS/SOS for one demo trip; use load_tests for fleet capacity."""
import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4
import httpx
from dotenv import load_dotenv

def make_point(scenario, seq):
    point = {'event_id': str(uuid4()), 'seq': seq,
             'lat': 10.77 + (seq % 100)*0.00015, 'lon': 106.7,
             'accuracy_m': 10, 'speed_kmh': 25,
             'event_time': datetime.now(timezone.utc).isoformat()}
    if scenario == 'stop':
        point.update(lat=10.78, speed_kmh=0)
    elif scenario == 'deviation':
        point['lon'] = 106.705
    elif scenario == 'speed':
        point['speed_kmh'] = 105
    return point


def send_scenario(client, args, *, pause=time.sleep):
    path = f'/api/trips/{quote(args.trip, safe="")}'
    if args.scenario == 'sos':
        response = client.post(path+'/sos', json={'event_id': str(uuid4())})
        response.raise_for_status()
        print(response.json(), flush=True)
        return
    # Maintain a nominal 3-second interval despite HTTP time. This single-trip
    # demo producer is not an open-loop capacity benchmark.
    count = max(1, args.seconds // 3)
    start = time.monotonic()
    for seq in range(count):
        pause(max(0, start + seq*3 - time.monotonic()))
        response = client.post(path+'/telemetry', json=make_point(args.scenario, seq))
        response.raise_for_status()
        print(seq, response.json(), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=['normal','stop','deviation','speed','sos'], default='normal')
    parser.add_argument('--url', default='http://localhost:8000')
    parser.add_argument('--seconds', type=int, default=90)
    parser.add_argument('--user', default='driver')
    parser.add_argument('--trip', default='trip-001')
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error('--seconds must be positive')
    load_dotenv(Path(__file__).parent / 'backend' / '.env')
    password = os.getenv('DEMO_PASSWORD', '')
    if not password:
        parser.error('Set DEMO_PASSWORD in backend/.env before running the simulator')
    with httpx.Client(base_url=args.url, timeout=10, trust_env=False) as client:
        response = client.post('/api/login', json={'username': args.user, 'password': password})
        response.raise_for_status()
        send_scenario(client, args)


if __name__ == '__main__':
    main()
