"""Prepared-action approval, fencing, race and outcome checks against real PostgreSQL."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import connect
from app.planner import persist_proposal

pytestmark = pytest.mark.skipif(os.getenv('RUN_DEMO_TESTS') != '1', reason='Requires isolated test DB')


@pytest.fixture(scope='module')
def actors():
    clients = {name: TestClient(app) for name in ('operator', 'operator2', 'passenger')}
    for name, client in clients.items():
        assert client.post('/api/login', json={'username': name, 'password': os.environ['DEMO_PASSWORD']}).status_code == 200
    yield clients
    for client in clients.values():
        client.close()


@pytest.fixture
def case(actors):
    trip, incident, proposal = 'assist-test-' + str(uuid4()), uuid4(), uuid4()
    with connect() as conn:
        conn.execute("INSERT INTO trips(id,label,driver_id,passenger_id,route_geom) SELECT %s,%s,'driver','passenger',route_geom FROM trips WHERE id='trip-001'", (trip, trip))
        conn.execute("INSERT INTO incidents(id,trip_id,kind,severity,summary) VALUES (%s,%s,'STOP',3,'Synthetic assist test')", (incident, trip))
    persist_proposal({'incident_id': incident, 'job_id': proposal, 'severity': 3, 'advice': 'Bằng chứng giới hạn.'})
    version = actors['operator'].post(f'/api/incidents/{incident}/ack', json={}).json()['assignment_version']
    yield incident, proposal, version
    with connect() as conn:
        conn.execute('DELETE FROM mock_actions WHERE proposal_id IN (SELECT id FROM proposals WHERE incident_id=%s)', (incident,))
        conn.execute('DELETE FROM proposals WHERE incident_id=%s', (incident,))
        conn.execute('DELETE FROM incident_events WHERE incident_id=%s', (incident,))
        conn.execute('DELETE FROM incidents WHERE id=%s', (incident,))
        conn.execute('DELETE FROM trips WHERE id=%s', (trip,))


def decide(client, case, **updates):
    incident, proposal, version = case
    return client.post(f'/api/incidents/{incident}/decision', json={
        'proposal_id': str(proposal), 'assignment_version': version,
        'approve': True, 'proposal_revision': 1, **updates})


def test_plan_is_prepared_before_approval_and_payload_is_frozen(actors, case):
    incident, proposal, _ = case
    detail = actors['operator'].get(f'/api/incidents/{incident}').json()
    plan = detail['proposal']['response_plan']
    assert plan['action']['recipient']['ref'] == 'safety-team-demo'
    assert detail['proposal']['status'] == 'PENDING'
    assert detail['resolution_options'] and detail['release_options']
    assert decide(actors['operator'], case, proposal_revision=None).status_code == 409
    assert decide(actors['passenger'], case).status_code == 403
    assert decide(actors['operator'], case).status_code == 200
    assert decide(actors['operator'], case).status_code == 409
    with connect() as conn:
        row = conn.execute('SELECT * FROM mock_actions WHERE proposal_id=%s', (proposal,)).fetchone()
        assert row['payload']['response_plan'] == plan
        assert row['payload']['body'] == plan['action']['message']
        assert conn.execute('SELECT status FROM incidents WHERE id=%s', (incident,)).fetchone()['status'] == 'OPEN'
        assert conn.execute('SELECT follow_up_due_at>clock_timestamp() AS future FROM proposals WHERE id=%s', (proposal,)).fetchone()['future']


def test_edit_requires_new_review_and_never_changes_recipient(actors, case):
    incident, proposal, version = case
    body = {'proposal_id': str(proposal), 'assignment_version': version,
            'proposal_revision': 1, 'message': 'Nội dung ngoại lệ đã được kiểm tra', 'recipient_ref': 'attacker'}
    assert actors['operator2'].post(f'/api/incidents/{incident}/proposal-edit', json=body).status_code == 409
    assert actors['operator'].post(f'/api/incidents/{incident}/proposal-edit', json=body).json()['revision'] == 2
    assert decide(actors['operator'], case).status_code == 409
    assert decide(actors['operator'], case, proposal_revision=2).status_code == 200
    assert actors['operator'].post(f'/api/incidents/{incident}/proposal-edit', json={**body, 'proposal_revision': 2}).status_code == 409
    with connect() as conn:
        payload = conn.execute('SELECT payload FROM mock_actions WHERE proposal_id=%s', (proposal,)).fetchone()['payload']
        assert payload['body'] == body['message'] and payload['recipient_ref'] == 'safety-team-demo'
        assert payload['proposal_revision'] == 2


def test_double_approval_of_prepared_plan_has_one_effect(actors, case):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: decide(actors['operator'], case), range(2)))
    assert sorted(r.status_code for r in results) == [200, 409]
    with connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM mock_actions WHERE proposal_id=%s', (case[1],)).fetchone()['n'] == 1


@pytest.mark.parametrize('outcome', ['no_response', 'needs_help'])
def test_reported_outcome_creates_one_unapproved_followup_even_on_retry(actors, case, outcome):
    incident, proposal, version = case
    body = {'proposal_id': str(proposal), 'assignment_version': version,
            'request_id': str(uuid4()), 'outcome': outcome}
    endpoint = f'/api/incidents/{incident}/follow-up'
    assert actors['operator'].post(endpoint, json=body).status_code == 409
    assert decide(actors['operator'], case).status_code == 200
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: actors['operator'].post(endpoint, json=body), range(2)))
    assert all(r.status_code == 200 for r in responses)
    assert sorted(r.json()['duplicate'] for r in responses) == [False, True]
    assert len({r.json()['proposal_id'] for r in responses}) == 1
    assert actors['operator'].post(endpoint, json={**body, 'request_id': str(uuid4())}).status_code == 409
    with connect() as conn:
        successor = conn.execute('SELECT * FROM proposals WHERE followup_of=%s', (proposal,)).fetchone()
        assert successor['status'] == 'PENDING'
        assert successor['response_plan']['action']['channel'] == 'INTERNAL'
        assert successor['response_plan']['incident_severity'] == 3
        assert conn.execute('SELECT count(*) AS n FROM mock_actions WHERE proposal_id=%s', (successor['id'],)).fetchone()['n'] == 0


def test_expired_or_transferred_owner_cannot_edit_or_report(actors, case):
    incident, proposal, version = case
    assert decide(actors['operator'], case).status_code == 200
    with connect() as conn:
        conn.execute("UPDATE incidents SET assignment_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (incident,))
    assert actors['operator'].post(f'/api/incidents/{incident}/follow-up', json={
        'proposal_id': str(proposal), 'assignment_version': version, 'request_id': str(uuid4()), 'outcome': 'needs_help'}).status_code == 409


def test_quick_reasons_validate_kind_and_keep_human_audit(actors, case):
    incident, _, version = case
    path = f'/api/incidents/{incident}/resolve'
    for code in ['gps_restored', 'unknown', 'other']:
        assert actors['operator'].post(path, json={'assignment_version': version, 'reason_code': code}).status_code == 422
    assert actors['operator'].post(path, json={'assignment_version': version, 'reason_code': 'expected_stop'}).status_code == 200
    with connect() as conn:
        audit = conn.execute("SELECT body FROM incident_events WHERE incident_id=%s AND kind='resolved'", (incident,)).fetchone()['body']
        assert 'operator' in audit and '[expected_stop]' in audit and 'xác nhận' in audit


def test_prepare_legacy_draft_is_explicit_and_invalidates_old_approval(actors, case):
    incident, proposal, version = case
    with connect() as conn:
        conn.execute('UPDATE proposals SET response_plan=NULL WHERE id=%s', (proposal,))
    body = {'proposal_id': str(proposal), 'assignment_version': version}
    for _ in range(2):
        assert actors['operator'].post(f'/api/incidents/{incident}/prepare', json=body).status_code == 200
    detail = actors['operator'].get(f'/api/incidents/{incident}').json()['proposal']
    assert detail['revision'] == 2 and detail['response_plan']
    assert decide(actors['operator'], case).status_code == 409
    assert decide(actors['operator'], case, proposal_revision=2).status_code == 200
