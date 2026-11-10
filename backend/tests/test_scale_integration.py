"""Regression coverage for batching, scoped reads, replay and migrations."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from app.main import app
from app.db import connect, migrate
from app.worker import process_batch, watchdog
from app.realtime import get_refresh_state
from app import config

pytestmark = pytest.mark.skipif(os.getenv('RUN_DEMO_TESTS') != '1', reason='Requires isolated test database')


def create_trip(driver='driver', passenger='passenger'):
    trip = 'scale-test-' + str(uuid4())
    with connect() as conn:
        conn.execute("INSERT INTO trips(id,label,driver_id,passenger_id,route_geom) SELECT %s,%s,%s,%s,route_geom FROM trips WHERE id='trip-001'", (trip, trip, driver, passenger))
    return trip


def client(name):
    c = TestClient(app)
    assert c.post('/api/login', json={'username': name, 'password': os.environ['DEMO_PASSWORD']}).status_code == 200
    return c


def point(observed, speed=25):
    return {'event_id': str(uuid4()), 'seq': 1, 'lat': 10.78, 'lon': 106.7,
            'accuracy_m': 10, 'speed_kmh': speed, 'event_time': observed.isoformat()}


def test_old_delivery_does_not_hide_gps_loss_and_scoped_reads():
    trip = create_trip()
    driver = client('driver')
    old = datetime.now(timezone.utc) - timedelta(seconds=120)
    response = driver.post(f'/api/trips/{trip}/telemetry', json=point(old))
    assert response.status_code == 200
    assert process_batch([response.json()['event_id']]) == {'STALE': 1}
    with connect() as conn:
        assert conn.execute('SELECT last_received_at FROM trips WHERE id=%s', (trip,)).fetchone()['last_received_at'] is None
        conn.execute("UPDATE trips SET created_at=now()-interval '5 minutes' WHERE id=%s", (trip,))
    watchdog()
    with connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM incidents WHERE trip_id=%s AND kind='GPS_LOST'", (trip,)).fetchone()['n'] == 1
        evidence = conn.execute("SELECT evidence FROM incidents WHERE trip_id=%s AND kind='GPS_LOST'", (trip,)).fetchone()['evidence']
        assert evidence['missing_seconds'] >= 300
        assert evidence['threshold_seconds'] == config.GPS_LOST_SECONDS
    assert driver.get('/api/trips/trip-002').status_code == 404
    assert driver.get(f'/api/trips/{trip}').json()['route']['type'] == 'LineString'
    assert all(t['route'] is None for t in driver.get('/api/trips?include_route=false').json())
    finished = create_trip()
    with connect() as conn:
        conn.execute("UPDATE trips SET status='FINISHED' WHERE id=%s", (finished,))
    active = driver.get('/api/trips?include_route=false&active_only=true').json()
    assert trip in {t['id'] for t in active}
    assert finished not in {t['id'] for t in active}
    assert all(t['status'] == 'ACTIVE' and t['driver_id'] == 'driver' for t in active)
    assert finished in {t['id'] for t in driver.get('/api/trips').json()}
    assert driver.get('/api/ops/metrics').status_code == 403


def test_batch_replay_and_queue_delay_still_trigger_rules():
    trip = create_trip()
    # Event times and receive times are from 10 minutes ago. They were fresh at
    # ingestion, so delayed processing must still evaluate the speed window.
    start = datetime.now(timezone.utc)-timedelta(minutes=10)
    event_ids = []
    with connect() as conn:
        for second in range(0, config.SPEED_SECONDS+4, 3):
            observed = start + timedelta(seconds=second)
            p = point(observed, speed=110)
            event_id = uuid4()
            event_ids.append(event_id)
            conn.execute('INSERT INTO telemetry_inbox(event_id,trip_id,actor_id,payload,received_at) VALUES (%s,%s,%s,%s,%s)',
                         (event_id, trip, 'driver', Jsonb(p), observed+timedelta(milliseconds=50)))
            conn.execute('INSERT INTO telemetry_outbox(event_id) VALUES (%s)', (event_id,))
    assert process_batch(reversed(event_ids)) == {'APPLIED': len(event_ids)}
    assert process_batch(event_ids) == {}
    with connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM incidents WHERE trip_id=%s AND kind='SPEED'", (trip,)).fetchone()['n'] == 1
        evidence = conn.execute("SELECT evidence FROM incidents WHERE trip_id=%s AND kind='SPEED'", (trip,)).fetchone()['evidence']
        assert evidence['speed_kmh'] == 110
        assert evidence['speed_threshold_kmh'] == config.SPEED_LIMIT_KMH + 10
        assert evidence['observed_duration_seconds'] >= evidence['threshold_seconds'] == config.SPEED_SECONDS
        assert conn.execute('SELECT count(*) AS n FROM telemetry_outbox WHERE event_id=ANY(%s)', (event_ids,)).fetchone()['n'] == 0
        assert conn.execute('SELECT min(EXTRACT(EPOCH FROM processed_at-received_at)) AS age FROM telemetry_inbox WHERE event_id=ANY(%s)', (event_ids,)).fetchone()['age'] > 500


def test_concurrent_cross_trip_event_collision_is_conflict_not_500():
    first, second = create_trip(), create_trip('driver2', 'passenger2')
    c1, c2 = client('driver'), client('driver2')
    payload = point(datetime.now(timezone.utc))
    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = [executor.submit(c.post, f'/api/trips/{trip}/telemetry', json=payload)
                for c, trip in [(c1, first), (c2, second)]]
        assert sorted(job.result().status_code for job in jobs) == [200, 409]


def test_driver_refresh_not_invalidated_by_other_trip():
    driver = client('driver')
    token = driver.cookies.get('journey_session')
    before = get_refresh_state(token)
    with connect() as conn:
        conn.execute("UPDATE trips SET version=version+1 WHERE id='trip-002'")
        conn.execute('UPDATE system_state SET version=version+1 WHERE id=1')
    assert get_refresh_state(token) == before
    with connect() as conn:
        conn.execute("UPDATE trips SET version=version+1 WHERE id='trip-001'")
    assert get_refresh_state(token) == before+1


def test_migrations_reapply_without_resetting_data():
    trip = create_trip()
    migrate()
    migrate()
    with connect() as conn:
        assert conn.execute('SELECT id FROM trips WHERE id=%s', (trip,)).fetchone()
        assert conn.execute("SELECT count(*) AS n FROM schema_migrations WHERE version='001_mvp_scale.sql'").fetchone()['n'] == 1


def test_durable_retry_after_trip_finishes_but_new_event_is_rejected():
    trip = create_trip()
    driver = client('driver')
    payload = point(datetime.now(timezone.utc))
    assert driver.post(f'/api/trips/{trip}/telemetry', json=payload).status_code == 200
    with connect() as conn:
        conn.execute("UPDATE trips SET status='FINISHED' WHERE id=%s", (trip,))
    retry = driver.post(f'/api/trips/{trip}/telemetry', json=payload)
    assert retry.status_code == 200 and retry.json()['duplicate']
    fresh = point(datetime.now(timezone.utc))
    assert driver.post(f'/api/trips/{trip}/telemetry', json=fresh).status_code == 409
    with connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM telemetry_inbox WHERE trip_id=%s', (trip,)).fetchone()['n'] == 1


def test_parallel_logins_cannot_bypass_username_ip_limit():
    username = 'throttle-test-' + str(uuid4())
    def attempt(_):
        return TestClient(app).post('/api/login', json={'username': username, 'password': 'invalid-test-password'}).status_code
    try:
        with ThreadPoolExecutor(max_workers=12) as pool:
            statuses = list(pool.map(attempt, range(20)))
        assert statuses.count(401) == 10
        assert statuses.count(429) == 10
    finally:
        with connect() as conn:
            conn.execute('DELETE FROM login_attempts WHERE username=%s', (username,))
