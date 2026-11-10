"""Real PostgreSQL/API coverage: permissions, dedupe, leases and read-only advice."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import connect
from app.api import operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_DEMO_TESTS') != '1', reason='Requires isolated test DB')


@pytest.fixture(scope='module')
def actors():
    clients = {role: TestClient(app) for role in ('operator', 'operator2', 'driver', 'passenger')}
    for role, client in clients.items():
        assert client.post('/api/login', json={'username': role, 'password': os.environ['DEMO_PASSWORD']}).status_code == 200
    yield clients
    for client in clients.values():
        client.close()


@pytest.fixture
def case(monkeypatch):
    monkeypatch.delenv('OSRM_URL', raising=False)
    monkeypatch.setenv('OPERATIONS_LLM_MODE', 'mock')
    trip = 'operations-test-' + str(uuid4())
    with connect() as conn:
        conn.execute("INSERT INTO trips(id,label,driver_id,passenger_id,route_geom) SELECT %s,%s,'driver','passenger',route_geom FROM trips WHERE id='trip-001'", (trip, trip))
    yield {'request_id': str(uuid4()), 'trip_id': trip, 'scenario_id': 'normal'}
    with connect() as conn:
        conn.execute('DELETE FROM operations_runs WHERE trip_id=%s', (trip,))
        conn.execute('DELETE FROM incidents WHERE trip_id=%s', (trip,))
        conn.execute('DELETE FROM trips WHERE id=%s', (trip,))


def post(client, body):
    return client.post('/api/operations/plans', json=body)


@pytest.mark.parametrize('role', ['driver', 'passenger'])
def test_operations_require_operator(actors, case, role):
    client = actors[role]
    assert post(client, case).status_code == 403
    assert client.get('/api/operations/plans').status_code == 403
    assert client.get('/api/operations/scenarios').status_code == 403
    assert client.get('/api/operations/plans/'+case['request_id']).status_code == 403


def test_idempotency_immutable_snapshot_and_no_effect_on_trip(actors, case):
    client = actors['operator']
    with connect() as conn:
        before = conn.execute('SELECT version,status,route_geom FROM trips WHERE id=%s', (case['trip_id'],)).fetchone()
    first = post(client, case)
    assert first.status_code == 200, first.text
    assert first.json()['duplicate'] is False
    second = post(client, case)
    assert second.status_code == 200 and second.json()['duplicate'] is True
    assert second.json()['report'] == first.json()['report']
    with connect() as conn:
        assert conn.execute('SELECT version,status,route_geom FROM trips WHERE id=%s', (case['trip_id'],)).fetchone() == before
        assert conn.execute('SELECT count(*) AS n FROM operations_runs WHERE id=%s', (case['request_id'],)).fetchone()['n'] == 1
        assert not conn.execute('SELECT 1 FROM incidents WHERE trip_id=%s', (case['trip_id'],)).fetchone()
        conn.execute('UPDATE trips SET version=version+1 WHERE id=%s', (case['trip_id'],))
    assert post(client, case).json()['report'] == first.json()['report']
    assert post(client, {**case, 'scenario_id': 'rain'}).status_code == 409
    assert post(actors['operator2'], case).status_code == 409
    history = client.get('/api/operations/plans', params={'trip_id': case['trip_id'], 'limit': 1}).json()
    assert [str(row['id']) for row in history] == [case['request_id']]
    detail = client.get('/api/operations/plans/'+case['request_id']).json()
    assert detail['report'] == first.json()['report']
    assert 'snapshot' not in detail and 'actor_id' not in detail


def test_failed_attempt_retry_reuses_original_snapshot(actors, case, monkeypatch):
    original = operations.assess
    def failure(_):
        raise RuntimeError('synthetic failure')
    monkeypatch.setattr(operations, 'assess', failure)
    assert post(actors['operator'], case).status_code == 503
    with connect() as conn:
        saved = conn.execute('SELECT snapshot,status FROM operations_runs WHERE id=%s', (case['request_id'],)).fetchone()
        assert saved['status'] == 'FAILED'
        conn.execute('UPDATE trips SET version=version+1 WHERE id=%s', (case['trip_id'],))
    monkeypatch.setattr(operations, 'assess', original)
    retry = post(actors['operator'], case)
    assert retry.status_code == 200, retry.text
    assert retry.json()['report']['trip_version'] == saved['snapshot']['trip_version']


def test_inflight_duplicate_and_actor_limit_then_retry(actors, case, monkeypatch):
    entered, release = Event(), Event()
    original = operations.assess
    def slow(snapshot):
        entered.set()
        assert release.wait(15)
        return original(snapshot)
    monkeypatch.setattr(operations, 'assess', slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(post, actors['operator'], case)
        try:
            assert entered.wait(10)
            assert post(actors['operator'], case).status_code == 409
            assert post(actors['operator'], {**case, 'request_id': str(uuid4())}).status_code == 429
        finally:
            release.set()
        assert future.result().status_code == 200
    assert post(actors['operator'], case).json()['duplicate'] is True


def test_expired_worker_cannot_overwrite_new_execution(actors, case, monkeypatch):
    original = operations.assess
    def superseded(snapshot):
        with connect() as conn:
            conn.execute('UPDATE operations_runs SET execution_token=%s WHERE id=%s', (uuid4(), case['request_id']))
        return original(snapshot)
    monkeypatch.setattr(operations, 'assess', superseded)
    assert post(actors['operator'], case).status_code == 409
    with connect() as conn:
        conn.execute("UPDATE operations_runs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (case['request_id'],))
    monkeypatch.setattr(operations, 'assess', original)
    assert post(actors['operator'], case).status_code == 200


def test_open_emergency_blocks_dispatch_without_approving(actors, case):
    with connect() as conn:
        conn.execute("INSERT INTO incidents(id,trip_id,kind,severity,status,summary,needs_plan) VALUES (%s,%s,'SOS',3,'OPEN','Synthetic emergency',false)", (uuid4(), case['trip_id']))
    result = post(actors['operator'], case)
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'BLOCKED'
    assert not result.json()['report']['allocation']['assignments']
    with connect() as conn:
        assert conn.execute('SELECT status FROM incidents WHERE trip_id=%s', (case['trip_id'],)).fetchone()['status'] == 'OPEN'


def test_request_contract_rejects_untrusted_tool_values(actors, case):
    client = actors['operator']
    assert post(client, {**case, 'scenario_id': 'unknown'}).status_code == 422
    assert post(client, {**case, 'refund_vnd': 1000000}).status_code == 422
    assert post(client, {**case, 'trip_id': 'missing-trip'}).status_code == 404
    assert client.get('/api/operations/plans?limit=51').status_code == 422


def test_new_request_quota_does_not_block_completed_retries(actors, case):
    client = actors['operator']
    for index in range(10):
        request = case if index == 0 else {**case, 'request_id': str(uuid4())}
        response = post(client, request)
        assert response.status_code == 200, response.text
    rejected = post(client, {**case, 'request_id': str(uuid4())})
    assert rejected.status_code == 429 and rejected.headers['retry-after'] == '60'
    assert post(client, case).json()['duplicate'] is True
