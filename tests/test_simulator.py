import json
from datetime import datetime
from types import SimpleNamespace
import httpx
import pytest
from simulator import send_scenario


@pytest.mark.parametrize('scenario', ['normal', 'stop', 'deviation', 'speed'])
def test_demo_sends_valid_utc_telemetry_for_each_scenario(scenario):
    requests = []

    def receive(request):
        requests.append(json.loads(request.content))
        assert request.url.path == '/api/trips/trip-001/telemetry'
        return httpx.Response(200, json={'status': 'durable'})

    with httpx.Client(base_url='http://test', transport=httpx.MockTransport(receive)) as client:
        send_scenario(client, SimpleNamespace(trip='trip-001', scenario=scenario, seconds=6), pause=lambda _: None)
    assert len(requests) == 2
    assert requests[0]['event_id'] != requests[1]['event_id']
    assert all(datetime.fromisoformat(p['event_time']).utcoffset().total_seconds() == 0 for p in requests)
    assert all(p['speed_kmh'] == {'normal': 25, 'stop': 0, 'deviation': 25, 'speed': 105}[scenario] for p in requests)
    assert all(p['lon'] == (106.705 if scenario == 'deviation' else 106.7) for p in requests)
