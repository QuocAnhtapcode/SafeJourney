"""Planner regressions against an explicitly opted-in synthetic database.

Run alongside test_integration.py after schema + seed on an isolated local DB.
These tests use the real LangGraph/PostgreSQL checkpointer, not an LLM service.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres import PostgresSaver

from app import planner
from app.config import DATABASE_URL
from app.db import connect
from fastapi.testclient import TestClient
from app.main import app


pytestmark = pytest.mark.skipif(
    os.getenv('RUN_DEMO_TESTS') != '1',
    reason='Set RUN_DEMO_TESTS=1 on an isolated local test DB only',
)


@pytest.fixture
def cases(monkeypatch):
    """Create scoped fixtures and remove only rows belonging to this test."""
    monkeypatch.setenv('LLM_MODE', 'mock')
    trip_ids, incident_ids = [], []

    def create(*, severity=2, age_seconds=0, kind='SPEED'):
        trip_id, incident_id = 'planner-test-' + str(uuid4()), uuid4()
        with connect() as conn:
            conn.execute("""
                INSERT INTO trips(id,label,driver_id,passenger_id,route_geom)
                SELECT %s,%s,'driver','passenger',route_geom FROM trips WHERE id='trip-001'
            """, (trip_id, trip_id))
            conn.execute("""
                INSERT INTO incidents(id,trip_id,kind,severity,summary,created_at)
                VALUES (%s,%s,%s,%s,'Synthetic planner regression',
                        now()-(%s*interval '1 second'))
            """, (incident_id, trip_id, kind, severity, age_seconds))
        trip_ids.append(trip_id)
        incident_ids.append(incident_id)
        return incident_id

    yield create

    if incident_ids:
        with connect() as conn:
            jobs = conn.execute('SELECT id FROM graph_jobs WHERE incident_id=ANY(%s)', (incident_ids,)).fetchall()
        with PostgresSaver.from_conn_string(DATABASE_URL) as saver:
            for job in jobs:
                saver.delete_thread(str(job['id']))
        with connect() as conn:
            conn.execute('DELETE FROM mock_actions WHERE proposal_id IN (SELECT id FROM proposals WHERE incident_id=ANY(%s))', (incident_ids,))
            conn.execute('DELETE FROM proposals WHERE incident_id=ANY(%s)', (incident_ids,))
            conn.execute('DELETE FROM graph_jobs WHERE incident_id=ANY(%s)', (incident_ids,))
            conn.execute('DELETE FROM incident_events WHERE incident_id=ANY(%s)', (incident_ids,))
            conn.execute('DELETE FROM incidents WHERE id=ANY(%s)', (incident_ids,))
            conn.execute('DELETE FROM trips WHERE id=ANY(%s)', (trip_ids,))


def test_fifty_human_waits_do_not_block_new_or_decided_jobs(cases):
    waiting = [cases(age_seconds=120, severity=3) for _ in range(51)]
    with PostgresSaver.from_conn_string(DATABASE_URL) as saver:
        saver.setup()
        graph = planner.build_graph(saver)
        for _ in range(3):
            planner.plan_pending(graph)
        with connect() as conn:
            assert conn.execute("SELECT count(*) AS n FROM proposals WHERE incident_id=ANY(%s) AND status='PENDING'", (waiting,)).fetchone()['n'] == 51
            # A committed rejection is a valid wake-up without any external action.
            conn.execute("UPDATE proposals SET status='REJECTED' WHERE incident_id=%s", (waiting[-1],))
        fresh = cases(severity=3)
        planner.plan_pending(graph)

    with connect() as conn:
        assert conn.execute('SELECT status FROM proposals WHERE incident_id=%s', (fresh,)).fetchone()['status'] == 'PENDING'
        assert conn.execute('SELECT status FROM graph_jobs WHERE incident_id=%s', (waiting[-1],)).fetchone()['status'] == 'DONE'
        assert conn.execute("SELECT count(*) AS n FROM proposals WHERE incident_id=ANY(%s) AND status='PENDING'", (waiting,)).fetchone()['n'] == 50
        assert conn.execute('SELECT count(*) AS n FROM mock_actions WHERE proposal_id IN (SELECT id FROM proposals WHERE incident_id=ANY(%s))', (waiting + [fresh],)).fetchone()['n'] == 0


def test_escalation_during_analysis_replans_without_stale_advice(cases, monkeypatch):
    incident_id = cases()
    original_analyze = planner.analyze

    def escalate_during_analysis(state):
        if state['incident_id'] == str(incident_id) and state['severity'] == 2:
            with connect() as conn:
                conn.execute('UPDATE incidents SET severity=3,needs_plan=true WHERE id=%s', (incident_id,))
            return {'advice': 'Advice generated before escalation'}
        return original_analyze(state)

    monkeypatch.setattr(planner, 'analyze', escalate_during_analysis)
    with PostgresSaver.from_conn_string(DATABASE_URL) as saver:
        saver.setup()
        graph = planner.build_graph(saver)
        planner.plan_pending(graph)
        with connect() as conn:
            assert conn.execute('SELECT needs_plan FROM incidents WHERE id=%s', (incident_id,)).fetchone()['needs_plan']
            assert conn.execute('SELECT count(*) AS n FROM proposals WHERE incident_id=%s', (incident_id,)).fetchone()['n'] == 0
        planner.plan_pending(graph)

    with connect() as conn:
        proposal = conn.execute('SELECT * FROM proposals WHERE incident_id=%s', (incident_id,)).fetchone()
        assert proposal['action_type'] == 'MOCK_EMERGENCY'
        assert proposal['status'] == 'PENDING'
        assert 'before escalation' not in proposal['body']
        assert conn.execute('SELECT count(*) AS n FROM mock_actions WHERE proposal_id=%s', (proposal['id'],)).fetchone()['n'] == 0


def test_evidence_snapshot_reaches_graph_and_proposal_without_private_fields(cases):
    incident_id = cases()
    with connect() as conn:
        from psycopg.types.json import Jsonb
        conn.execute('UPDATE incidents SET evidence=%s WHERE id=%s', (Jsonb({
            'speed_kmh': 105, 'speed_threshold_kmh': 90,
            'observed_duration_seconds': 12, 'threshold_seconds': 9,
            'lat': 10.78, 'private_note': 'PRIVATE'}), incident_id))
    with PostgresSaver.from_conn_string(DATABASE_URL) as saver:
        saver.setup()
        graph = planner.build_graph(saver)
        planner.plan_pending(graph)
        with connect() as conn:
            proposal = conn.execute('SELECT * FROM proposals WHERE incident_id=%s', (incident_id,)).fetchone()
        snapshot = graph.get_state({'configurable': {'thread_id': str(proposal['id'])}})
    assert snapshot.values['evidence'] == {'speed_kmh': 105, 'speed_threshold_kmh': 90,
        'observed_duration_seconds': 12, 'threshold_seconds': 9}
    assert all(value in proposal['body'] for value in ['105 km/h', '90 km/h', '12 giây', '9 giây'])
    assert proposal['status'] == 'EXECUTED'
    assert proposal['execution_mode'] == 'AUTO'
    assert 'PRIVATE' not in proposal['body']


def test_failed_job_does_not_stop_other_incidents(cases, monkeypatch):
    broken, healthy = cases(age_seconds=120, severity=3), cases(severity=3)
    original_analyze = planner.analyze

    def fail_one(state):
        if state['incident_id'] == str(broken):
            raise ValueError('Synthetic failure before proposal')
        return original_analyze(state)

    monkeypatch.setattr(planner, 'analyze', fail_one)
    with PostgresSaver.from_conn_string(DATABASE_URL) as saver:
        saver.setup()
        planner.plan_pending(planner.build_graph(saver))
    with connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM proposals WHERE incident_id=%s', (broken,)).fetchone()['n'] == 0
        assert conn.execute('SELECT status FROM proposals WHERE incident_id=%s', (healthy,)).fetchone()['status'] == 'PENDING'


def test_maintenance_escalates_and_expires_once_without_executing(cases):
    incident_id = cases(severity=3, age_seconds=80)
    proposal_id = uuid4()
    with connect() as conn:
        conn.execute("INSERT INTO proposals(id,incident_id,action_type,recipient_ref,body,expires_at) VALUES (%s,%s,'MOCK_EMERGENCY','safety-team-demo','Synthetic expired proposal',now()-interval '1 second')", (proposal_id, incident_id))
    planner.maintain_incidents()
    planner.maintain_incidents()
    with connect() as conn:
        assert conn.execute('SELECT status FROM proposals WHERE id=%s', (proposal_id,)).fetchone()['status'] == 'EXPIRED'
        events = conn.execute('SELECT kind,count(*) AS n FROM incident_events WHERE incident_id=%s GROUP BY kind', (incident_id,)).fetchall()
        assert {row['kind']: row['n'] for row in events} == {'ESCALATION_30': 1, 'ESCALATION_60': 1, 'expired': 1}
        assert conn.execute('SELECT count(*) AS n FROM mock_actions WHERE proposal_id=%s', (proposal_id,)).fetchone()['n'] == 0


@pytest.fixture(scope='module')
def actors():
    clients = {role: TestClient(app) for role in ('operator', 'driver', 'passenger')}
    for name, client in clients.items():
        assert client.post('/api/login', json={'username': name, 'password': os.environ['DEMO_PASSWORD']}).status_code == 200
    yield clients
    for client in clients.values():
        client.close()


def test_renew_expired_proposal_once_and_require_new_human_approval(cases, actors):
    incident_id = cases(severity=3, kind='SOS')
    with PostgresSaver.from_conn_string(DATABASE_URL) as saver:
        saver.setup()
        graph = planner.build_graph(saver)
        planner.plan_pending(graph)
        with connect() as conn:
            old = conn.execute('SELECT * FROM proposals WHERE incident_id=%s', (incident_id,)).fetchone()
            conn.execute("UPDATE proposals SET expires_at=now()-interval '1 second' WHERE id=%s", (old['id'],))
        path = f'/api/incidents/{incident_id}/replan'
        claim = actors['operator'].post(f'/api/incidents/{incident_id}/ack', json={})
        assert claim.status_code == 200
        version = claim.json()['assignment_version']
        body = {'proposal_id': str(old['id']), 'assignment_version': version}
        for role in ('driver', 'passenger'):
            assert actors[role].post(path, json=body).status_code == 403
        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [pool.submit(actors['operator'].post, path, json=body) for _ in range(2)]
            responses = [job.result() for job in requests]
        assert [r.status_code for r in responses] == [202, 202]
        assert sorted(r.json()['duplicate'] for r in responses) == [False, True]
        # Replay the pre-checkpoint persist after the renewal was committed.
        planner.persist_proposal({'job_id': str(old['id']), 'incident_id': str(incident_id), 'severity': 3, 'advice': old['body']})
        with connect() as conn:
            assert conn.execute('SELECT needs_plan FROM incidents WHERE id=%s', (incident_id,)).fetchone()['needs_plan']
            assert conn.execute("SELECT count(*) AS n FROM incident_events WHERE incident_id=%s AND kind='replan_requested'", (incident_id,)).fetchone()['n'] == 1
        planner.plan_pending(graph)  # Complete the expired graph's human wait.
        planner.plan_pending(graph)  # Create a new graph/proposal identity.
    with connect() as conn:
        proposals = conn.execute('SELECT * FROM proposals WHERE incident_id=%s ORDER BY created_at,id', (incident_id,)).fetchall()
        assert len(proposals) == 2
        new = next(p for p in proposals if p['id'] != old['id'])
        assert new['status'] == 'PENDING' and new['approved_by'] is None
        assert conn.execute('SELECT count(*) AS n FROM mock_actions WHERE proposal_id=ANY(%s)', ([old['id'], new['id']],)).fetchone()['n'] == 0
    assert actors['operator'].post(path, json=body).json()['duplicate'] is True
    with connect() as conn:
        assert not conn.execute('SELECT needs_plan FROM incidents WHERE id=%s', (incident_id,)).fetchone()['needs_plan']
    decision_path = f'/api/incidents/{incident_id}/decision'
    assert actors['operator'].post(decision_path, json={'proposal_id': str(old['id']), 'approve': True, 'assignment_version': version}).status_code == 409
    assert actors['operator'].post(decision_path, json={'proposal_id': str(new['id']), 'proposal_revision': new['revision'], 'approve': True, 'assignment_version': version}).status_code == 200
    with connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM mock_actions WHERE proposal_id=%s', (new['id'],)).fetchone()['n'] == 1


@pytest.mark.parametrize('status,closed', [('PENDING', False), ('EXECUTED', False), ('REJECTED', False), ('CANCELLED', False), ('EXPIRED', True)])
def test_renewal_rejects_ineligible_proposals(cases, actors, status, closed):
    incident_id, proposal_id = cases(), uuid4()
    claim = actors['operator'].post(f'/api/incidents/{incident_id}/ack', json={})
    assert claim.status_code == 200
    with connect() as conn:
        conn.execute("INSERT INTO proposals(id,incident_id,action_type,recipient_ref,body,status,expires_at) VALUES (%s,%s,'MOCK_CHECK_IN','demo','Synthetic proposal',%s,now()+interval '5 minutes')", (proposal_id, incident_id, status))
        if closed:
            conn.execute("UPDATE incidents SET status='RESOLVED' WHERE id=%s", (incident_id,))
    assert actors['operator'].post(f'/api/incidents/{incident_id}/replan', json={'proposal_id': str(proposal_id), 'assignment_version': claim.json()['assignment_version']}).status_code == 409
    with connect() as conn:
        assert conn.execute('SELECT replan_requested_at FROM proposals WHERE id=%s', (proposal_id,)).fetchone()['replan_requested_at'] is None


def test_slow_normal_llm_does_not_block_escalation_or_sos(cases, monkeypatch):
    normal = cases(age_seconds=50000)
    entered, release = Event(), Event()
    normal_calls = []
    original = planner.analyze

    def slow_model(state):
        if state['incident_id'] == str(normal):
            normal_calls.append(state['job_id'])
            entered.set()
            assert release.wait(10), 'Test did not release the simulated LLM'
        return original(state)

    monkeypatch.setattr(planner, 'analyze', slow_model)
    with PostgresSaver.from_conn_string(DATABASE_URL) as saver:
        saver.setup()
    scheduler = planner.PlannerScheduler(DATABASE_URL)
    try:
        scheduler.tick()
        assert entered.wait(5)
        normal_future = scheduler.inflight[False][0]
        urgent = cases(severity=3, age_seconds=80, kind='SOS')
        scheduler.next_maintenance = 0
        scheduler.tick()
        scheduler.inflight[True][0].result(timeout=5)
        assert not normal_future.done()
        with connect() as conn:
            kinds = {row['kind'] for row in conn.execute('SELECT kind FROM incident_events WHERE incident_id=%s', (urgent,))}
            assert {'ESCALATION_30', 'ESCALATION_60'} <= kinds
            assert conn.execute('SELECT status FROM proposals WHERE incident_id=%s', (urgent,)).fetchone()['status'] == 'PENDING'
            # Changing lanes mid-flight must not run the same graph twice.
            conn.execute('UPDATE incidents SET severity=3,needs_plan=true WHERE id=%s', (normal,))
        scheduler.tick()
        assert len(normal_calls) == 1
        assert True not in scheduler.inflight
    finally:
        release.set()
        scheduler.close()
    normal_future.result(timeout=5)
