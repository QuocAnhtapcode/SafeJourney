"""Opt-in local integration test. Creates synthetic rows; never truncates user data."""
import os
from datetime import datetime, timezone
from uuid import uuid4
import pytest
import redis
from fastapi.testclient import TestClient
from langgraph.checkpoint.postgres import PostgresSaver
from app.main import app
from app.config import DATABASE_URL, REDIS_URL, STREAM
from app.db import connect
from app.worker import relay, process
from app.planner import build_graph, plan_pending

pytestmark = pytest.mark.skipif(os.getenv('RUN_DEMO_TESTS') != '1', reason='Set RUN_DEMO_TESTS=1 on local demo DB only')

def test_durable_sos_permissions_and_human_gate():
    trip_id = 'test-' + str(uuid4())
    with connect() as conn:
        conn.execute("INSERT INTO trips(id,label,driver_id,passenger_id,route_geom) SELECT %s,%s,'driver','passenger',route_geom FROM trips WHERE id='trip-001'", (trip_id, trip_id))
    operator, driver, passenger = TestClient(app), TestClient(app), TestClient(app)
    for client, name in [(operator,'operator'),(driver,'driver'),(passenger,'passenger')]:
        assert client.post('/api/login', json={'username': name, 'password': os.environ['DEMO_PASSWORD']}).status_code == 200
    with operator.websocket_connect('/ws', headers={'origin': 'http://localhost:5173'}) as socket:
        assert socket.receive_json()['type'] == 'refresh'
    assert operator.post('/api/logout', headers={'origin': 'https://untrusted.example'}, json={}).status_code == 403
    event = {'event_id': str(uuid4()), 'seq': 0, 'lat': 10.78, 'lon': 106.7,
             'accuracy_m': 10, 'speed_kmh': 25, 'event_time': datetime.now(timezone.utc).isoformat()}
    assert driver.post('/api/trips/trip-002/telemetry', json=event).status_code == 404
    assert driver.post(f'/api/trips/{trip_id}/telemetry', json=event).status_code == 200
    assert driver.post(f'/api/trips/{trip_id}/telemetry', json=event).json()['duplicate']
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    relay(r)
    assert any(fields['event_id'] == event['event_id'] for _, fields in r.xrange(STREAM))
    process(event['event_id'])
    process(event['event_id'])
    sos = {'event_id': str(uuid4())}
    response = passenger.post(f'/api/trips/{trip_id}/sos', json=sos)
    assert response.status_code == 200
    inc = response.json()['incident_id']
    assert passenger.post(f'/api/trips/{trip_id}/sos', json=sos).json()['incident_id'] == inc
    assert inc not in [row['id'] for row in driver.get('/api/incidents').json()]
    with connect() as conn:
        assert conn.execute('SELECT severity FROM incidents WHERE id=%s', (inc,)).fetchone()['severity'] == 3
    with PostgresSaver.from_conn_string(DATABASE_URL) as saver:
        saver.setup()
        plan_pending(build_graph(saver))
    with connect() as conn:
        proposal = conn.execute('SELECT * FROM proposals WHERE incident_id=%s', (inc,)).fetchone()
        assert proposal['status'] == 'PENDING'
        assert conn.execute('SELECT count(*) AS n FROM mock_actions WHERE proposal_id=%s', (proposal['id'],)).fetchone()['n'] == 0
    claim = operator.post(f'/api/incidents/{inc}/ack', json={})
    assert claim.status_code == 200
    version = claim.json()['assignment_version']
    receipt = next(row for row in passenger.get('/api/incidents').json() if row['id'] == inc)
    assert not {'assigned_operator_id', 'assigned_operator_username', 'assignment_version', 'acknowledged_by'} & receipt.keys()
    decision = {'proposal_id': str(proposal['id']), 'proposal_revision': proposal['revision'],
                'approve': True, 'assignment_version': version}
    assert driver.post(f'/api/incidents/{inc}/decision', json=decision).status_code == 403
    assert operator.post(f'/api/incidents/{inc}/decision', json=decision).status_code == 200
    assert operator.post(f'/api/incidents/{inc}/decision', json=decision).status_code == 409
    # Rebuild graph/checkpointer as if planner restarted: terminal approval is read from DB.
    with PostgresSaver.from_conn_string(DATABASE_URL) as saver:
        plan_pending(build_graph(saver))
    with connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM mock_actions WHERE proposal_id=%s', (proposal['id'],)).fetchone()['n'] == 1
        assert conn.execute('SELECT status FROM graph_jobs WHERE incident_id=%s', (inc,)).fetchone()['status'] == 'DONE'
    expired_id = str(uuid4())
    with connect() as conn:
        conn.execute("INSERT INTO proposals(id,incident_id,action_type,recipient_ref,body,expires_at) VALUES (%s,%s,'MOCK_EMERGENCY','safety-team-demo','Expiry test',now()-interval '1 second')", (expired_id, inc))
    assert operator.post(f'/api/incidents/{inc}/decision', json={'proposal_id': expired_id, 'approve': True, 'assignment_version': version}).status_code == 409
    with connect() as conn:
        assert conn.execute('SELECT status FROM proposals WHERE id=%s', (expired_id,)).fetchone()['status'] == 'EXPIRED'
    assert operator.post(f'/api/incidents/{inc}/ack', json={}).status_code == 200
    assert operator.post(f'/api/incidents/{inc}/resolve', json={'reason': 'Đã xác minh dữ liệu thử nghiệm', 'assignment_version': version}).status_code == 200
    assert operator.get('/api/area-alerts').status_code == 200
    assert passenger.get(f'/api/incidents/{inc}/timeline').status_code == 403
