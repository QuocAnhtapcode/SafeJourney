"""Queue dimensions compose before pagination; participant receipts stay private."""
import os
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import connect

pytestmark = pytest.mark.skipif(os.getenv('RUN_DEMO_TESTS') != '1', reason='Requires isolated test DB')


@pytest.fixture(scope='module')
def actors():
    clients = {name: TestClient(app) for name in ('operator', 'operator2', 'driver', 'passenger')}
    for name, client in clients.items():
        assert client.post('/api/login', json={'username': name, 'password': os.environ['DEMO_PASSWORD']}).status_code == 200
    yield clients
    for client in clients.values():
        client.close()


@pytest.fixture
def cases():
    trip = 'filter-test-' + str(uuid4())
    ids = {key: uuid4() for key in ('unassigned', 'mine', 'other', 'expired', 'agent', 'closed')}
    with connect() as conn:
        conn.execute("INSERT INTO trips(id,label,driver_id,passenger_id,route_geom) SELECT %s,%s,'driver','passenger',route_geom FROM trips WHERE id='trip-001'", (trip, trip))
        for key, kind, severity, status, owner, lease, state in [
            ('unassigned', 'SOS', 3, 'OPEN', None, None, 'ESCALATED'),
            ('mine', 'SPEED', 3, 'OPEN', 'operator', '1 hour', 'ESCALATED'),
            ('other', 'DEVIATION', 3, 'OPEN', 'operator2', '1 hour', 'ESCALATED'),
            ('expired', 'GPS_LOST', 3, 'OPEN', 'operator', '-1 minute', 'ESCALATED'),
            ('agent', 'STOP', 2, 'OPEN', None, None, 'WAITING_RESPONSE'),
            ('closed', 'STOP', 3, 'RESOLVED', None, None, 'COMPLETE'),
        ]:
            conn.execute("""INSERT INTO incidents(id,trip_id,kind,severity,status,summary,needs_plan,
                assigned_operator_id,assigned_at,assignment_expires_at,automation_state)
                VALUES (%s,%s,%s,%s,%s,'Synthetic filter regression',false,%s,
                    CASE WHEN %s::text IS NOT NULL THEN clock_timestamp()-interval '2 minutes' ELSE NULL END,
                    clock_timestamp()+%s::interval,%s)""",
                (ids[key], trip, kind, severity, status, owner, owner, lease, state))
        conn.execute('INSERT INTO sos_events(event_id,trip_id,actor_id,incident_id) VALUES (%s,%s,%s,%s)',
                     (uuid4(), trip, 'passenger', ids['unassigned']))
    yield {key: str(value) for key, value in ids.items()}
    with connect() as conn:
        conn.execute('DELETE FROM sos_events WHERE trip_id=%s', (trip,))
        conn.execute('DELETE FROM incidents WHERE trip_id=%s', (trip,))
        conn.execute('DELETE FROM trips WHERE id=%s', (trip,))


def selected(client, cases, query):
    response = client.get('/api/incidents?' + query)
    assert response.status_code == 200, response.text
    return {row['id'] for row in response.json()} & set(cases.values())


def test_human_and_unassigned_intersect_and_include_expired_ownership(actors, cases):
    assert selected(actors['operator'], cases, 'assignment=human&owner=unassigned&status=open') == {cases['unassigned'], cases['expired']}


def test_mine_depends_on_the_authenticated_operator_and_excludes_expired_leases(actors, cases):
    query = 'assignment=human&owner=mine&status=open'
    assert selected(actors['operator'], cases, query) == {cases['mine']}
    assert selected(actors['operator2'], cases, query) == {cases['other']}


def test_status_separates_closed_history_from_active_cases(actors, cases):
    assert selected(actors['operator'], cases, 'assignment=all&status=resolved') == {cases['closed']}
    assert selected(actors['operator'], cases, 'assignment=all&status=open') == set(cases.values()) - {cases['closed']}


def test_agent_scope_is_not_confused_with_unassigned_human_work(actors, cases):
    assert selected(actors['operator'], cases, 'assignment=agent&owner=all&status=open') == {cases['agent']}
    assert selected(actors['operator'], cases, 'assignment=all&owner=unassigned&status=open') == {cases['unassigned'], cases['expired'], cases['agent']}


def test_legacy_assignment_filters_and_default_all_remain_compatible(actors, cases):
    assert selected(actors['operator'], cases, 'assignment=mine') == {cases['mine']}
    assert selected(actors['operator'], cases, 'assignment=unassigned') == {cases['unassigned'], cases['expired'], cases['agent']}
    assert selected(actors['operator'], cases, '') == set(cases.values())


def test_filters_are_applied_before_limit_and_offset(actors, cases):
    query = 'assignment=human&owner=unassigned&status=open'
    full = actors['operator'].get('/api/incidents?' + query).json()
    assert len(full) >= 2
    for offset in (0, 1):
        page = actors['operator'].get(f'/api/incidents?{query}&limit=1&offset={offset}').json()
        assert [row['id'] for row in page] == [full[offset]['id']]


@pytest.mark.parametrize('role', ['driver', 'passenger'])
def test_operator_filters_do_not_expose_incident_history_to_participants(actors, cases, role):
    for query in ('owner=mine', 'status=open', 'assignment=all&status=resolved'):
        assert actors[role].get('/api/incidents?' + query).status_code == 403
    expected = {cases['unassigned']} if role == 'passenger' else set()
    assert selected(actors[role], cases, '') == expected


def test_unknown_filter_values_are_rejected(actors):
    for query in ('owner=someone_else', 'status=hidden', 'assignment=unknown'):
        assert actors['operator'].get('/api/incidents?' + query).status_code == 422
