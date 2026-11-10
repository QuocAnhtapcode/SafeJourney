"""Real PostgreSQL locks and independent operator sessions on the isolated test DB."""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import connect
from app.planner import maintain_incidents

pytestmark = pytest.mark.skipif(os.getenv('RUN_DEMO_TESTS') != '1', reason='Requires isolated test DB')


@pytest.fixture(scope='module')
def actors():
    result = {name: TestClient(app) for name in ('operator', 'operator2', 'passenger')}
    for name, client in result.items():
        assert client.post('/api/login', json={'username': name, 'password': os.environ['DEMO_PASSWORD']}).status_code == 200
    yield result
    for client in result.values():
        client.close()


@pytest.fixture
def case():
    trip, incident, proposal = 'ownership-test-' + str(uuid4()), uuid4(), uuid4()
    with connect() as conn:
        conn.execute("INSERT INTO trips(id,label,driver_id,passenger_id,route_geom) SELECT %s,%s,'driver','passenger',route_geom FROM trips WHERE id='trip-001'", (trip, trip))
        conn.execute("INSERT INTO incidents(id,trip_id,kind,severity,summary,needs_plan) VALUES (%s,%s,'SOS',3,'Synthetic ownership regression',false)", (incident, trip))
        conn.execute("INSERT INTO proposals(id,incident_id,action_type,recipient_ref,body,expires_at) VALUES (%s,%s,'MOCK_EMERGENCY','demo','Synthetic proposal',now()+interval '15 minutes')", (proposal, incident))
    yield incident, proposal
    with connect() as conn:
        conn.execute('DELETE FROM mock_actions WHERE proposal_id=%s', (proposal,))
        conn.execute('DELETE FROM proposals WHERE incident_id=%s', (incident,))
        conn.execute('DELETE FROM incident_events WHERE incident_id=%s', (incident,))
        conn.execute('DELETE FROM incidents WHERE id=%s', (incident,))
        conn.execute('DELETE FROM trips WHERE id=%s', (trip,))


def take(client, incident):
    response = client.post(f'/api/incidents/{incident}/ack', json={})
    assert response.status_code == 200, response.text
    return response.json()['assignment_version']


def test_unclaimed_case_cannot_be_decided_replanned_or_closed(actors, case):
    incident, proposal = case
    for endpoint, body in [('decision', {'proposal_id': str(proposal), 'approve': True}),
                           ('replan', {'proposal_id': str(proposal)}), ('resolve', {'reason': 'Synthetic close'})]:
        assert actors['operator'].post(f'/api/incidents/{incident}/{endpoint}', json=body).status_code == 409
    with connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM mock_actions WHERE proposal_id=%s', (proposal,)).fetchone()['n'] == 0
        assert conn.execute('SELECT status FROM incidents WHERE id=%s', (incident,)).fetchone()['status'] == 'OPEN'


def test_two_operators_claim_concurrently_only_one_wins_and_retry_is_stable(actors, case):
    incident, _ = case
    barrier = Barrier(2)
    def attempt(name):
        barrier.wait(timeout=3)
        return name, actors[name].post(f'/api/incidents/{incident}/ack', json={})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ['operator', 'operator2']))
    assert sorted(response.status_code for _, response in results) == [200, 409]
    winner, first = next((name, response) for name, response in results if response.status_code == 200)
    assert take(actors[winner], incident) == first.json()['assignment_version']
    with connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM incident_events WHERE incident_id=%s AND kind='assignment_claimed'", (incident,)).fetchone()['n'] == 1


def test_nonowner_and_missing_or_stale_version_cannot_write(actors, case):
    incident, proposal = case
    version = take(actors['operator'], incident)
    for endpoint, body in [('decision', {'proposal_id': str(proposal), 'approve': True}),
                           ('replan', {'proposal_id': str(proposal)}), ('resolve', {'reason': 'Synthetic close'}),
                           ('release', {'reason': 'Synthetic handoff'}), ('lease', {})]:
        body['assignment_version'] = version
        assert actors['operator2'].post(f'/api/incidents/{incident}/{endpoint}', json=body).status_code == 409
        assert actors['passenger'].post(f'/api/incidents/{incident}/{endpoint}', json=body).status_code == 403
    for supplied in (None, version+1):
        assert actors['operator'].post(f'/api/incidents/{incident}/decision', json={
            'proposal_id': str(proposal), 'approve': True, 'assignment_version': supplied}).status_code == 409


def test_approval_race_keeps_one_mock_action(actors, case):
    incident, proposal = case
    version = take(actors['operator'], incident)
    body = {'proposal_id': str(proposal), 'approve': True, 'assignment_version': version}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda name: actors[name].post(f'/api/incidents/{incident}/decision', json=body), ['operator', 'operator2']))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert actors['operator'].post(f'/api/incidents/{incident}/decision', json=body).status_code == 409
    with connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM mock_actions WHERE proposal_id=%s', (proposal,)).fetchone()['n'] == 1
        action = conn.execute('SELECT approved_by,payload FROM mock_actions WHERE proposal_id=%s', (proposal,)).fetchone()
        assert action['approved_by'] == 'operator'
        assert action['payload']['assignment_version'] == version


def test_release_handoff_and_fencing_even_when_original_owner_returns(actors, case):
    incident, proposal = case
    first = take(actors['operator'], incident)
    def release_as(name, version):
        return actors[name].post(f'/api/incidents/{incident}/release', json={'reason': 'Synthetic shift handoff', 'assignment_version': version})
    assert release_as('operator', first).status_code == 200
    second = take(actors['operator2'], incident)
    assert second > first
    old_body = {'proposal_id': str(proposal), 'approve': True, 'assignment_version': first}
    assert actors['operator'].post(f'/api/incidents/{incident}/decision', json=old_body).status_code == 409
    assert release_as('operator2', second).status_code == 200
    third = take(actors['operator'], incident)
    assert third > second
    assert actors['operator'].post(f'/api/incidents/{incident}/decision', json=old_body).status_code == 409
    assert actors['operator'].post(f'/api/incidents/{incident}/decision', json={**old_body, 'assignment_version': third}).status_code == 200


def test_expired_lease_cannot_renew_or_act_and_can_be_reclaimed(actors, case):
    incident, proposal = case
    first = take(actors['operator'], incident)
    with connect() as conn:
        conn.execute("UPDATE incidents SET assignment_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (incident,))
    assert actors['operator'].post(f'/api/incidents/{incident}/lease', json={'assignment_version': first}).status_code == 409
    assert actors['operator'].post(f'/api/incidents/{incident}/decision', json={
        'proposal_id': str(proposal), 'approve': True, 'assignment_version': first}).status_code == 409
    assert take(actors['operator2'], incident) > first


def test_owner_heartbeat_extends_deadline_without_changing_generation_or_audit(actors, case):
    incident, _ = case
    version = take(actors['operator'], incident)
    with connect() as conn:
        before = conn.execute("UPDATE incidents SET assignment_expires_at=clock_timestamp()+interval '5 seconds' WHERE id=%s RETURNING assignment_expires_at", (incident,)).fetchone()['assignment_expires_at']
        audit_count = conn.execute('SELECT count(*) AS n FROM incident_events WHERE incident_id=%s', (incident,)).fetchone()['n']
    response = actors['operator'].post(f'/api/incidents/{incident}/lease', json={'assignment_version': version})
    assert response.status_code == 200
    assert response.json()['assignment_version'] == version
    with connect() as conn:
        assert conn.execute('SELECT assignment_expires_at FROM incidents WHERE id=%s', (incident,)).fetchone()['assignment_expires_at'] > before
        assert conn.execute('SELECT count(*) AS n FROM incident_events WHERE incident_id=%s', (incident,)).fetchone()['n'] == audit_count


def test_lease_deadline_is_checked_after_waiting_for_database_lock(actors, case):
    incident, proposal = case
    version = take(actors['operator'], incident)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with connect() as holder:
            holder.execute("UPDATE incidents SET assignment_expires_at=clock_timestamp()+interval '1 second' WHERE id=%s", (incident,))
            pending = pool.submit(actors['operator'].post, f'/api/incidents/{incident}/decision', json={
                'proposal_id': str(proposal), 'approve': True, 'assignment_version': version})
            time.sleep(1.2)
        assert pending.result(timeout=5).status_code == 409


def test_queue_filters_and_first_acknowledgement_survive_handoff(actors, case):
    incident, _ = case
    first = take(actors['operator'], incident)
    mine = actors['operator'].get('/api/incidents?assignment=mine').json()
    assert str(incident) in {row['id'] for row in mine}
    assert str(incident) not in {row['id'] for row in actors['operator2'].get('/api/incidents?assignment=mine').json()}
    assert actors['passenger'].get('/api/incidents?assignment=mine').status_code == 403
    response = actors['operator'].post(f'/api/incidents/{incident}/release', json={'assignment_version': first, 'reason': 'Synthetic shift handoff'})
    assert response.status_code == 200
    assert str(incident) in {row['id'] for row in actors['operator2'].get('/api/incidents?assignment=unassigned').json()}
    take(actors['operator2'], incident)
    with connect() as conn:
        row = conn.execute('SELECT acknowledged_by,assigned_operator_id FROM incidents WHERE id=%s', (incident,)).fetchone()
        assert row == {'acknowledged_by': 'operator', 'assigned_operator_id': 'operator2'}


def test_selected_detail_is_readable_after_claim_removes_case_from_unassigned_queue(actors, case):
    incident, proposal = case
    take(actors['operator'], incident)
    assert str(incident) not in {row['id'] for row in actors['operator'].get('/api/incidents?assignment=unassigned').json()}
    detail = actors['operator'].get(f'/api/incidents/{incident}')
    assert detail.status_code == 200
    row = detail.json()
    assert row['id'] == str(incident) and row['assigned_operator_id'] == 'operator'
    assert row['proposal']['id'] == str(proposal) and row['server_time']
    assert actors['operator2'].get(f'/api/incidents/{incident}').status_code == 200
    assert actors['passenger'].get(f'/api/incidents/{incident}').status_code == 403
    assert actors['operator'].get(f'/api/incidents/{uuid4()}').status_code == 404


def test_sos_escalation_resumes_when_acknowledged_case_loses_coverage(actors, case):
    incident, _ = case
    version = take(actors['operator'], incident)
    with connect() as conn:
        conn.execute("UPDATE incidents SET assignment_expires_at=clock_timestamp()-interval '80 seconds' WHERE id=%s", (incident,))
    maintain_incidents()
    maintain_incidents()
    with connect() as conn:
        events = {row['kind']: row['n'] for row in conn.execute("SELECT kind,count(*) AS n FROM incident_events WHERE incident_id=%s GROUP BY kind", (incident,))}
        assert events[f'ESCALATION_30_V{version}'] == events[f'ESCALATION_60_V{version}'] == 1
