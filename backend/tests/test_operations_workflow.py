"""Graph tests use real deterministic solvers; external routing/model are mocked."""
from datetime import datetime, timezone
from decimal import Decimal
import asyncio
import time
import pytest
import httpx
from app.operations.scenarios import build_snapshot, SCENARIOS
from app.operations import workflow, supervisor


def snapshot(scenario='normal', emergency=False):
    return build_snapshot({'id': 'synthetic-trip', 'version': 1, 'status': 'ACTIVE',
        'last_seen': None, 'start_lat': 10.77, 'start_lon': 106.69,
        'end_lat': 10.79, 'end_lon': 106.71, 'planned_distance_m': 3134.567891234,
        'has_open_emergency': emergency}, scenario, datetime.now(timezone.utc))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv('OSRM_URL', raising=False)
    monkeypatch.setenv('OPERATIONS_LLM_MODE', 'mock')


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_every_scenario_runs_mandatory_tools_without_authorizing_actions(scenario):
    result = workflow.assess(snapshot(scenario))
    report = result['report']
    assert report['invariants_checked'] and report['simulation'] and report['advisory_only']
    assert len(report['trace']) == 7
    assert report['fare']['money_moved'] is False
    assert report['refund']['money_moved'] is False
    assert report['demand']['cell_system'] == 'H3'
    assert report['allocation']['constraints_checked']
    if scenario == 'low_battery':
        assert not report['battery']['feasible']
        assert not report['charging']['reachable_with_reserve']
        assert not report['allocation']['assignments']
    if scenario == 'fare_dispute':
        assert Decimal(report['refund']['refund_vnd']) == 50000
    if scenario == 'rush_hour':
        assert report['demand']['scenario_expected'] == 10


def test_emergency_blocks_all_allocations():
    result = workflow.assess(snapshot(emergency=True))
    assert result['status'] == 'BLOCKED'
    assert not result['report']['allocation']['assignments']
    assert any(s['code'] == 'OPEN_EMERGENCY' for s in result['report']['signals'])


def test_configured_routing_failure_blocks_instead_of_claiming_verified(monkeypatch):
    monkeypatch.setenv('OSRM_URL', 'http://routing.example')
    monkeypatch.setattr(workflow.OSRMClient, 'route', lambda *args: {'distance_m': 4200, 'duration_s': 600, 'verified': True, 'source': 'osrm'})
    def fail(*args):
        raise workflow.RoutingError('No table')
    monkeypatch.setattr(workflow.OSRMClient, 'table', fail)
    result = workflow.assess(snapshot())
    assert result['status'] == 'BLOCKED'
    assert not result['report']['route']['verified']
    assert not result['report']['allocation']['assignments']


def test_verified_provider_still_has_no_action_authority(monkeypatch):
    monkeypatch.setenv('OSRM_URL', 'http://routing.example')
    monkeypatch.setattr(workflow.OSRMClient, 'route', lambda *args: {'distance_m': 4200, 'duration_s': 600, 'verified': True, 'source': 'osrm'})
    monkeypatch.setattr(workflow.OSRMClient, 'table', lambda *args: {'distance_matrix_m': [[0], [500], [600], [900]], 'duration_matrix_s': [[0], [60], [70], [100]], 'verified': True})
    report = workflow.assess(snapshot('rain'))['report']
    assert report['route']['verified'] and report['allocation']['routing_verified']
    assert report['advisory_only']
    assert report['route']['duration_s'] > 600


@pytest.mark.parametrize('content', ['{"focus":"energy"}', '{"focus":"energy","refund_vnd":999}', '{"focus":"authorize_rescue"}', '['*1100+'0'+']'*1100])
def test_llm_is_limited_to_priority_and_receives_no_location(monkeypatch, content):
    monkeypatch.setenv('OPERATIONS_LLM_MODE', 'ollama')
    def respond(url, payload, seconds):
        prompt = payload['messages'][-1]['content']
        assert 'synthetic-trip' not in prompt and '106.69' not in prompt
        return {'message': {'content': content}}
    monkeypatch.setattr(supervisor, '_request_selection', respond)
    report = workflow.assess(snapshot())['report']
    assert report['supervisor']['model_used'] == (content == '{"focus":"energy"}')
    assert report['invariants_checked'] and len(report['trace']) == 7


def test_supervisor_request_has_whole_exchange_deadline_and_byte_limit():
    class Trickle(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(.02)
                yield b' '
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        supervisor._request_selection('http://model.test/api/chat', {}, .1,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Trickle())))
    assert time.monotonic()-started < 1
    with pytest.raises(ValueError, match='size limit'):
        supervisor._request_selection('http://model.test/api/chat', {}, .5,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b'x'*32_769)))


def test_supervisor_timeout_falls_back_and_still_runs_tools(monkeypatch):
    monkeypatch.setenv('OPERATIONS_LLM_MODE', 'ollama')
    def timeout(*args):
        raise TimeoutError('synthetic model deadline')
    monkeypatch.setattr(supervisor, '_request_selection', timeout)
    report = workflow.assess(snapshot('low_battery'))['report']
    assert report['supervisor'] == {'focus': 'energy', 'source': 'backend_fallback', 'model_used': False}
    assert report['invariants_checked'] and not report['battery']['feasible']
