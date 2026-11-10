"""Real DB state machine and authenticated recipient replies, without external sending."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import connect, create_incident
from app.planner import persist_proposal
from app.autoplaybooks import maintain_autoplaybooks
from app.worker import process

pytestmark = pytest.mark.skipif(os.getenv('RUN_DEMO_TESTS') != '1', reason='Requires isolated test DB')


@pytest.fixture(scope='module')
def actors():
    clients = {name: TestClient(app) for name in ('operator', 'driver', 'driver2', 'passenger')}
    for name, client in clients.items():
        assert client.post('/api/login', json={'username': name, 'password': os.environ['DEMO_PASSWORD']}).status_code == 200
    yield clients
    for client in clients.values():
        client.close()


@pytest.fixture
def case():
    trip, incident, proposal = 'auto-test-' + str(uuid4()), uuid4(), uuid4()
    with connect() as conn:
        conn.execute("INSERT INTO trips(id,label,driver_id,passenger_id,route_geom) SELECT %s,%s,'driver','passenger',route_geom FROM trips WHERE id='trip-001'", (trip, trip))
        conn.execute("INSERT INTO incidents(id,trip_id,kind,severity,summary) VALUES (%s,%s,'STOP',2,'Synthetic autonomous test')", (incident, trip))
    persist_proposal({'incident_id': incident, 'job_id': proposal, 'severity': 2, 'advice': 'Test routine policy'})
    yield trip, incident, proposal
    with connect() as conn:
        conn.execute('DELETE FROM telemetry_outbox WHERE event_id IN (SELECT event_id FROM telemetry_inbox WHERE trip_id=%s)', (trip,))
        conn.execute('DELETE FROM telemetry_inbox WHERE trip_id=%s', (trip,))
        conn.execute('DELETE FROM mock_actions WHERE proposal_id IN (SELECT id FROM proposals WHERE incident_id IN (SELECT id FROM incidents WHERE trip_id=%s))', (trip,))
        conn.execute('DELETE FROM proposals WHERE incident_id IN (SELECT id FROM incidents WHERE trip_id=%s)', (trip,))
        conn.execute('DELETE FROM incident_events WHERE incident_id IN (SELECT id FROM incidents WHERE trip_id=%s)', (trip,))
        conn.execute('DELETE FROM incidents WHERE trip_id=%s', (trip,))
        conn.execute('DELETE FROM trips WHERE id=%s', (trip,))


def respond(client, proposal, outcome='safe', request_id=None):
    return client.post(f'/api/contact-requests/{proposal}/reply', json={'request_id': str(request_id or uuid4()), 'outcome': outcome})


def due(proposal):
    with connect() as conn:
        conn.execute("UPDATE proposals SET follow_up_due_at=clock_timestamp()-interval '1 second' WHERE id=%s", (proposal,))


def snapshot(incident):
    with connect() as conn:
        return conn.execute('SELECT * FROM incidents WHERE id=%s', (incident,)).fetchone(), conn.execute('SELECT * FROM proposals WHERE incident_id=%s ORDER BY created_at,id', (incident,)).fetchall()


def test_routine_sms_runs_without_operator_and_replay_never_resends(actors, case):
    trip, incident, proposal = case
    persist_proposal({'incident_id': incident, 'job_id': proposal, 'severity': 2, 'advice': 'Replay'})
    inc, plans = snapshot(incident)
    assert inc['assigned_operator_id'] is None and inc['automation_state'] == 'WAITING_RESPONSE'
    assert len(plans) == 1 and plans[0]['status'] == 'EXECUTED' and plans[0]['execution_mode'] == 'AUTO'
    with connect() as conn:
        actions = conn.execute('SELECT * FROM mock_actions WHERE proposal_id=%s', (proposal,)).fetchall()
        assert len(actions) == 1 and actions[0]['approved_by'] is None
        assert actions[0]['payload']['authorized_by'] == 'BACKEND_ROUTINE_POLICY_V1'
        assert actions[0]['payload']['recipient_confirmed'] is False
    assert str(incident) in {i['id'] for i in actors['operator'].get('/api/incidents?assignment=agent').json()}
    assert str(incident) not in {i['id'] for i in actors['operator'].get('/api/incidents?assignment=human').json()}


def test_contact_scope_does_not_expose_operator_evidence_and_requires_recipient(actors, case):
    _, _, proposal = case
    row = next(r for r in actors['driver'].get('/api/contact-requests').json() if r['id'] == str(proposal))
    assert set(row) == {'id', 'incident_id', 'trip_id', 'created_at', 'follow_up_due_at', 'channel', 'message'}
    assert actors['operator'].get('/api/contact-requests').status_code == 403
    assert respond(actors['operator'], proposal).status_code == 403
    assert respond(actors['passenger'], proposal).status_code == 404
    assert respond(actors['driver2'], proposal).status_code == 404
    assert str(proposal) not in {r['id'] for r in actors['passenger'].get('/api/contact-requests').json()}


def test_two_timeouts_call_once_then_escalate_without_executing_emergency(actors, case):
    _, incident, proposal = case
    due(proposal)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: maintain_autoplaybooks(), range(2)))
    _, plans = snapshot(incident)
    assert len(plans) == 2 and plans[-1]['response_plan']['action']['channel'] == 'CALL'
    assert plans[-1]['status'] == 'EXECUTED' and plans[-1]['contact_attempt'] == 2
    assert respond(actors['driver'], proposal).status_code == 409  # Old SMS cannot close a newer call.
    due(plans[-1]['id'])
    maintain_autoplaybooks()
    maintain_autoplaybooks()
    inc, plans = snapshot(incident)
    assert inc['severity'] == 3 and inc['automation_state'] == 'ESCALATED'
    assert len(plans) == 3 and plans[-1]['execution_mode'] == 'HUMAN' and plans[-1]['status'] == 'PENDING'
    with connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM mock_actions WHERE proposal_id=ANY(%s)', ([p['id'] for p in plans],)).fetchone()['n'] == 2


def test_help_response_is_idempotent_and_creates_only_unapproved_emergency(actors, case):
    _, incident, proposal = case
    request_id = uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: respond(actors['driver'], proposal, 'needs_help', request_id), range(2)))
    assert all(r.status_code == 200 for r in replies)
    assert sorted(r.json()['duplicate'] for r in replies) == [False, True]
    inc, plans = snapshot(incident)
    assert inc['severity'] == 3 and plans[-1]['status'] == 'PENDING'
    assert len(plans) == 2
    with connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM mock_actions WHERE proposal_id=%s', (plans[-1]['id'],)).fetchone()['n'] == 0


@pytest.mark.parametrize('good', [True, False])
def test_safe_confirmation_requires_fresh_clear_telemetry_before_auto_resolution(actors, case, good):
    trip, incident, proposal = case
    rid = uuid4()
    assert respond(actors['driver'], proposal, request_id=rid).status_code == 200
    assert snapshot(incident)[0]['status'] == 'OPEN'
    point = {'event_id': str(uuid4()), 'seq': 1, 'lat': 10.78, 'lon': 106.7, 'accuracy_m': 10 if good else 100,
             'speed_kmh': 25, 'event_time': datetime.now(timezone.utc).isoformat()}
    assert actors['driver'].post(f'/api/trips/{trip}/telemetry', json=point).status_code == 200
    process(point['event_id'])
    with connect() as conn:
        conn.execute("UPDATE incidents SET monitor_until=clock_timestamp()-interval '1 second' WHERE id=%s", (incident,))
    maintain_autoplaybooks()
    inc, plans = snapshot(incident)
    if good:
        assert inc['status'] == 'RESOLVED' and inc['automation_state'] == 'COMPLETE'
        assert respond(actors['driver'], proposal, request_id=rid).json()['duplicate'] is True
    else:
        assert inc['status'] == 'OPEN' and inc['severity'] == 3 and plans[-1]['status'] == 'PENDING'


def test_sos_on_same_trip_stops_automatic_call(actors, case):
    trip, incident, proposal = case
    with connect() as conn:
        create_incident(conn.cursor(), trip, 'SOS', 3, 'Synthetic SOS', {})
    due(proposal)
    maintain_autoplaybooks()
    inc, plans = snapshot(incident)
    assert inc['severity'] == 3 and plans[-1]['status'] == 'PENDING'
    assert all(p['response_plan']['action']['channel'] != 'CALL' for p in plans)


def test_operator_exception_takeover_stops_automation(actors, case):
    _, incident, proposal = case
    assert actors['operator'].post(f'/api/incidents/{incident}/ack', json={}).status_code == 200
    due(proposal)
    maintain_autoplaybooks()
    inc, plans = snapshot(incident)
    assert inc['assigned_operator_id'] == 'operator' and inc['automation_state'] == 'ESCALATED'
    assert len(plans) == 2 and plans[-1]['execution_mode'] == 'HUMAN'
