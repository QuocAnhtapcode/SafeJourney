"""Arithmetic/optimization boundary tests; OSRM HTTP is mocked, never public."""
from decimal import Decimal
from itertools import permutations
import asyncio
import time

import httpx
import pytest
from pydantic import ValidationError

from app.operations.calculations import quote_fare, calculate_refund, check_energy, estimate_charge
from app.operations.models import FareInput, EnergyInput, DispatchInput
from app.operations.optimizer import optimize_dispatch
from app.operations.spatial import great_circle_route, h3_aggregate, OSRMClient, RoutingError


PROFILE = {'capacity_kwh': 60, 'soh_percent': 80, 'soc_percent': 40, 'reserve_percent': 20,
           'consumption_wh_per_km': 200, 'auxiliary_kw': 1}
A, B = {'lat': 0, 'lon': 0}, {'lat': 0, 'lon': .01}


def test_fare_uses_decimal_and_one_final_vnd_rounding():
    result = quote_fare({'distance_m': 1250, 'duration_s': 600, 'waiting_s': 120,
                         'surcharge_vnd': 2000, 'discount_vnd': 500})
    assert result['total_vnd'] == '35000'
    assert result['policy']['id'] == 'safejourney-demo-v1'
    assert result['money_moved'] is False
    assert quote_fare({'distance_m': '0.05', 'duration_s': 0})['total_vnd'] == '15001'
    assert quote_fare({'distance_m': 0, 'duration_s': 0, 'discount_vnd': 999999})['total_vnd'] == '0'


def test_route_engine_floats_keep_precision_without_schema_rounding():
    distance, duration = 1234.1234567891234, 85.12345678912345
    item = FareInput(distance_m=distance, duration_s=duration)
    assert item.distance_m == Decimal(str(distance))
    assert item.duration_s == Decimal(str(duration))
    assert quote_fare(item)['calculation_verified'] is True
    assert check_energy({'profile': PROFILE, 'distance_m': distance, 'duration_s': duration})['feasible'] is True


def test_refund_deducts_previous_refunds_and_never_rounds_above_paid():
    assert calculate_refund({'paid_vnd': 1000, 'expected_vnd': 700, 'already_refunded_vnd': 200})['refund_vnd'] == '100'
    assert calculate_refund({'paid_vnd': 1000, 'expected_vnd': 700, 'already_refunded_vnd': 400})['refund_vnd'] == '0'
    value = calculate_refund({'paid_vnd': '1000.9', 'expected_vnd': 0})
    assert Decimal(value['refund_vnd']) <= Decimal('1000.9')
    assert value['money_moved'] is False
    with pytest.raises(ValidationError):
        calculate_refund({'paid_vnd': 1000, 'expected_vnd': 500, 'already_refunded_vnd': 1001})


@pytest.mark.parametrize('number', [-1, float('nan'), float('inf'), '-Infinity'])
def test_invalid_arithmetic_inputs_are_rejected(number):
    with pytest.raises(ValidationError):
        FareInput(distance_m=number, duration_s=1)
    with pytest.raises(ValidationError):
        EnergyInput(profile={**PROFILE, 'capacity_kwh': number}, distance_m=1, duration_s=1)


def test_energy_includes_health_reserve_and_auxiliary_load_without_rounding_eligibility():
    result = check_energy({'profile': PROFILE, 'distance_m': 40000, 'duration_s': 3600})
    assert Decimal(result['usable_capacity_kwh']) == Decimal(48)
    assert Decimal(result['current_kwh']) == Decimal('19.2')
    assert Decimal(result['available_kwh']) == Decimal('9.6')
    assert Decimal(result['required_kwh']) == Decimal(9)
    assert result['feasible'] is True
    assert check_energy({'profile': PROFILE, 'distance_m': 43000, 'duration_s': 3600})['feasible'] is True
    assert check_energy({'profile': PROFILE, 'distance_m': '43000.000001', 'duration_s': 3600})['feasible'] is False


def test_charging_queue_accounts_for_ports_power_limit_and_efficiency():
    result = estimate_charge({'profile': {**PROFILE, 'soh_percent': 100, 'soc_percent': 20},
        'target_soc_percent': 80, 'station_power_kw': 100, 'vehicle_max_power_kw': 50,
        'efficiency': '.9', 'ports': 2, 'busy_remaining_minutes': [10, 40], 'queue_length': 3,
        'queue_session_minutes': 30})
    assert Decimal(result['wait_minutes']) == 70
    assert Decimal(result['charge_minutes']) == 48
    assert Decimal(result['total_minutes']) == 118
    assert Decimal(result['effective_power_kw']) == 45


def test_charging_snapshot_must_match_ports_and_target():
    values = {'profile': PROFILE, 'station_power_kw': 50, 'vehicle_max_power_kw': 50}
    for change in ({'ports': 2}, {'target_soc_percent': 30}, {'efficiency': 0}, {'queue_length': -1}):
        with pytest.raises(ValidationError):
            estimate_charge({**values, **change})
    assert Decimal(estimate_charge({**values, 'target_soc_percent': 40,
                                  'busy_remaining_minutes': [300], 'queue_length': 99})['total_minutes']) == 0


def test_h3_counts_locations_and_rejects_bad_coordinates():
    data = h3_aggregate([{'lat': 10.78, 'lon': 106.7}, {'lat': 10.78, 'lon': 106.7}, {'lat': 40.7, 'lon': -74}])
    assert data['point_count'] == 3
    assert sorted(cell['count'] for cell in data['cells']) == [1, 2]
    with pytest.raises(ValidationError):
        h3_aggregate([{'lat': 100, 'lon': 1}])
    with pytest.raises(ValueError):
        h3_aggregate([], resolution=True)


def test_great_circle_is_explicitly_unverified_and_handles_antimeridian():
    route = great_circle_route({'lat': 0, 'lon': 179.5}, {'lat': 0, 'lon': -179.5})
    assert 111_000 < route['distance_m'] < 111_300
    assert route['verified'] is False and route['source'] == 'great_circle_estimate'
    assert great_circle_route(A, A)['duration_s'] == 0
    with pytest.raises(ValueError):
        great_circle_route(A, B, float('nan'))


def route_payload():
    return {'code': 'Ok', 'waypoints': [{'location': [0, 0], 'distance': 0}, {'location': [.01, 0], 'distance': 0}],
            'routes': [{'distance': 1200, 'duration': 120,
                        'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [.01, 0]]}}]}


def client(payload, *, code=200):
    return OSRMClient('http://127.0.0.1:5000', transport=httpx.MockTransport(
        lambda request: httpx.Response(code, json=payload)))


def test_osrm_route_uses_lon_lat_and_validates_result_without_public_server():
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=route_payload())
    value = OSRMClient('http://127.0.0.1:5000', transport=httpx.MockTransport(respond)).route(A, B)
    assert value['verified'] is True and value['distance_m'] == 1200
    assert '/0.0000000,0.0000000;0.0100000,0.0000000' in requests[0].url.path
    assert requests[0].url.params['geometries'] == 'geojson'


@pytest.mark.parametrize('mutation', ['negative', 'missing_geometry', 'distant_snap', 'wrong_endpoint', 'no_route', 'too_short', 'zero_duration'])
def test_osrm_invalid_response_never_becomes_verified_route(mutation):
    payload = route_payload()
    if mutation == 'negative': payload['routes'][0]['duration'] = -1
    if mutation == 'missing_geometry': payload['routes'][0].pop('geometry')
    if mutation == 'distant_snap': payload['waypoints'][0]['location'] = [100, 50]
    if mutation == 'wrong_endpoint': payload['routes'][0]['geometry']['coordinates'][-1] = [1, 0]
    if mutation == 'no_route': payload['code'] = 'NoRoute'
    if mutation == 'too_short': payload['routes'][0]['distance'] = 1
    if mutation == 'zero_duration': payload['routes'][0]['duration'] = 0
    with pytest.raises(RoutingError):
        client(payload).route(A, B)


def test_osrm_timeout_and_redirect_fail_explicitly():
    def timeout(request):
        raise httpx.ReadTimeout('synthetic test', request=request)
    with pytest.raises(RoutingError):
        OSRMClient('http://127.0.0.1:5000', transport=httpx.MockTransport(timeout)).route(A, B)
    with pytest.raises(RoutingError):
        client(route_payload(), code=302).route(A, B)
    for url in ('', 'file:///map', 'https://user:secret@example.test', 'https://example.test?redirect=1'):
        with pytest.raises(ValueError): OSRMClient(url)


def test_osrm_whole_request_deadline_cancels_slow_stream_and_bounds_response():
    class Trickle(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(.02)
                yield b' '
    bounded = OSRMClient('http://127.0.0.1:5000', timeout_seconds=.1,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Trickle())))
    started = time.monotonic()
    with pytest.raises(RoutingError): bounded.route(A, B)
    assert time.monotonic()-started < 1
    oversized = OSRMClient('http://127.0.0.1:5000', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=b'x'*2_000_001)))
    with pytest.raises(RoutingError, match='kích thước'): oversized.route(A, B)


def test_osrm_table_preserves_unreachable_edges_and_rejects_estimated_cells():
    payload = {'code': 'Ok', 'sources': [{'location': [0, 0], 'distance': 0}],
               'destinations': [{'location': [.01, 0], 'distance': 0}, {'location': [0, 0], 'distance': 0}],
               'distances': [[None, 0]], 'durations': [[None, 0]]}
    result = client(payload).table([A], [B, A])
    assert result['distance_matrix_m'] == [[None, 0]] and result['verified'] is True
    payload['durations'] = [[1, 0]]
    with pytest.raises(RoutingError): client(payload).table([A], [B, A])
    payload['durations'] = [[None, 0]]
    payload['fallback_speed_cells'] = [[0, 0]]
    with pytest.raises(RoutingError): client(payload).table([A], [B, A])


@pytest.mark.parametrize('distance,duration', [(0, 20), (1200, 0)])
def test_osrm_table_rejects_impossible_measurements(distance, duration):
    payload = {'code': 'Ok', 'sources': [{'location': [0, 0], 'distance': 0}],
               'destinations': [{'location': [.01, 0], 'distance': 0}],
               'distances': [[distance]], 'durations': [[duration]]}
    with pytest.raises(RoutingError):
        client(payload).table([A], [B])


def dispatch_problem(costs):
    return {'vehicles': [{'id': f'v{i}', 'position': A, 'profile': PROFILE} for i in range(len(costs))],
            'requests': [{'id': f'r{j}', 'pickup': A, 'destination': B, 'distance_m': 1000,
                          'duration_s': 120, 'max_wait_s': 604800} for j in range(len(costs[0]))],
            'distance_matrix_m': [[None if cost is None else 100 for cost in row] for row in costs],
            'duration_matrix_s': costs, 'routing_verified': True}


def test_optimizer_matches_bruteforce_global_optimum_not_greedy():
    costs = [[9, 2, 7], [6, 4, 3], [5, 8, 1]]
    result = optimize_dispatch(dispatch_problem(costs))
    expected = min(sum(costs[v][r] for v, r in enumerate(order)) for order in permutations(range(3)))
    assert result['served_count'] == 3 and result['total_pickup_seconds'] == expected
    assert len({entry['vehicle_id'] for entry in result['assignments']}) == 3
    assert len({entry['request_id'] for entry in result['assignments']}) == 3
    assert result['advisory_only'] is True


def test_optimizer_coverage_precedes_cost_even_for_large_costs():
    # The long pickups need a profile with no auxiliary draw to remain eligible.
    problem = dispatch_problem([[0, 600000], [600000, None]])
    for vehicle in problem['vehicles']: vehicle['profile'] = {**PROFILE, 'auxiliary_kw': 0}
    result = optimize_dispatch(problem)
    assert result['served_count'] == 2 and result['total_pickup_seconds'] == 1_200_000


def test_optimizer_rejects_unreachable_insufficient_battery_capacity_and_wait():
    problem = dispatch_problem([[None, 20, 20, 700]])
    problem['requests'][1]['passengers'] = 5
    problem['requests'][2]['distance_m'] = 100000
    problem['requests'][3]['max_wait_s'] = 600
    result = optimize_dispatch(problem)
    assert result['served_count'] == 0
    reasons = {row['request_id']: row['reasons'] for row in result['unserved']}
    assert reasons == {'r0': ['unreachable'], 'r1': ['insufficient_seats'],
                       'r2': ['insufficient_energy_reserve'], 'r3': ['pickup_wait_exceeded']}


def test_optimizer_includes_pickup_energy_and_reports_capacity_conflicts():
    problem = dispatch_problem([[1, 2]])
    problem['vehicles'][0]['profile'] = {**PROFILE, 'auxiliary_kw': 0}
    problem['requests'][0]['distance_m'] = 47000
    problem['distance_matrix_m'][0][0] = 2000  # Trip fits alone; trip+pickup exceeds 9.6 kWh.
    result = optimize_dispatch(problem)
    assert [row['request_id'] for row in result['assignments']] == ['r1']
    assert result['unserved'][0]['reasons'] == ['insufficient_energy_reserve']
    result = optimize_dispatch(dispatch_problem([[1, 2]]))
    assert result['unserved'][0]['reasons'] == ['assignment_capacity_unavailable']


@pytest.mark.parametrize('bad_matrix', [[[1]], [[float('nan'), 2]], [[-1, 2]], [[None, 2]]])
def test_optimizer_input_matrices_are_bounded_finite_and_consistent(bad_matrix):
    problem = dispatch_problem([[1, 2]])
    problem['duration_matrix_s'] = bad_matrix
    with pytest.raises(ValidationError): DispatchInput.model_validate(problem)


def test_optimizer_empty_fleet_and_unverified_routes_stay_explicit():
    problem = dispatch_problem([[1]])
    problem.update(vehicles=[], distance_matrix_m=[], duration_matrix_s=[], routing_verified=False)
    result = optimize_dispatch(problem)
    assert result['unserved'] == [{'request_id': 'r0', 'reasons': ['no_vehicles']}]
    assert result['routing_verified'] is False and result['advisory_only'] is True
