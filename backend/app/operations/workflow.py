"""A bounded team of specialist graph nodes; tools own every numeric result.

The LLM may choose which report deserves focus. It cannot bypass a specialist,
change a cost, dispatch a vehicle, refund money, or authorize emergency actions.
"""
from decimal import Decimal
import math
import os
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

from .calculations import quote_fare, calculate_refund, check_energy, estimate_charge
from .spatial import OSRMClient, RoutingError, great_circle_route, h3_aggregate
from .optimizer import optimize_dispatch
from .supervisor import choose_focus

WORKFLOW_VERSION = 'operations-team-v1'


class OperationState(TypedDict, total=False):
    snapshot: dict
    supervisor: dict
    route: dict
    pickup_matrix: dict
    fare: dict
    refund: dict
    battery: dict
    charging: dict
    demand: dict
    allocation: dict
    route_error: bool
    report: dict
    status: str


def routing_agent(state):
    data = state['snapshot']
    provider_url = os.getenv('OSRM_URL', '').strip()
    origins = [vehicle['position'] for vehicle in data['vehicles']]
    destination, origin = data['destination'], data['origin']
    distances, durations = [], []
    for position in origins:
        point = great_circle_route(position, origin, data['speed_kmh'])
        distances.append([point['distance_m']])
        durations.append([point['duration_s']])
    route = {'distance_m': data['planned_distance_m'],
             'duration_s': data['planned_distance_m']/(data['speed_kmh']/3.6),
             'source': 'postgis_stored_geometry_with_assumed_speed', 'verified': False,
             'assumptions': ['Chiều dài tuyến lưu tính bằng PostGIS geography; thời gian từ tốc độ giả định.']}
    matrix = {'distance_matrix_m': distances, 'duration_matrix_s': durations,
              'source': 'great_circle_estimate', 'verified': False}
    route_error = False
    if provider_url:
        try:
            client = OSRMClient(provider_url, float(os.getenv('OSRM_TIMEOUT_SECONDS', '3')))
            checked_route = client.route(origin, destination)
            checked_matrix = client.table(origins, [origin])
            route, matrix = checked_route, checked_matrix
            # OSRM has no current weather or traffic measurement in this demo.
            if data['scenario_id'] in ('rush_hour', 'rain'):
                multiplier = 30/data['speed_kmh']
                route = {**route, 'duration_s': route['duration_s']*multiplier,
                         'scenario_time_multiplier': multiplier}
                matrix['duration_matrix_s'] = [[None if value is None else value*multiplier for value in row]
                                               for row in matrix['duration_matrix_s']]
        except (RoutingError, ValueError):
            # Keep clearly marked geometry calculations for explanation, but do
            # not create assignments when a configured routing engine fails.
            route_error = True
            route['source'] = 'osrm_failed_geometry_reference_only'
            route['verified'] = False
    return {'route': route, 'pickup_matrix': matrix, 'route_error': route_error}


def finance_agent(state):
    data, route = state['snapshot'], state['route']
    fare = quote_fare({'distance_m': route['distance_m'], 'duration_s': route['duration_s'],
                       'waiting_s': data['waiting_s']})
    fare.update({'currency': 'VND', 'policy_version': fare['policy']['id'], 'breakdown': fare['components_vnd']})
    paid = Decimal(fare['total_vnd']) + (Decimal(50000) if data['scenario_id'] == 'fare_dispute' else 0)
    refund = calculate_refund({'paid_vnd': paid, 'expected_vnd': fare['total_vnd'], 'already_refunded_vnd': 0})
    refund['paid_source'] = 'synthetic_scenario'
    return {'fare': fare, 'refund': refund}


def energy_agent(state):
    data, route = state['snapshot'], state['route']
    battery = check_energy({'profile': data['profile'], 'distance_m': route['distance_m'],
                            'duration_s': route['duration_s']+data['waiting_s']})
    station = data['station']
    # In these fixtures the station is at the destination; same checked path.
    arrival_profile = {**data['profile'], 'soc_percent': battery['remaining_soc_percent']}
    charging = estimate_charge({'profile': arrival_profile, 'target_soc_percent': 80,
                                **{key: value for key, value in station.items() if key != 'position'}})
    charging.update({'reachable_with_reserve': battery['feasible'], 'conditional_on_arrival': True,
                     'travel_minutes': route['duration_s']/60})
    return {'battery': battery, 'charging': charging}


def demand_agent(state):
    data = state['snapshot']
    count = sum(data['historical_counts'])/len(data['historical_counts'])
    expected = math.ceil(count*data['demand_factor'])
    cell = h3_aggregate([data['origin']], data['h3_resolution'])['cells'][0]['cell']
    return {'demand': {'area_id': cell, 'cell_system': 'H3', 'resolution': data['h3_resolution'],
                      'historical_expected': count, 'scenario_expected': expected,
                      'available_vehicles': len(data['vehicles']), 'shortfall': max(0, expected-len(data['vehicles'])),
                      'source': 'synthetic_seasonal_counts_with_explicit_scenario_factor',
                      'factor': data['demand_factor'], 'window_minutes': 60,
                      'real_forecast_evaluated': False}}


def allocation_agent(state):
    data, route, matrix = state['snapshot'], state['route'], state['pickup_matrix']
    requests = [{'id': f'sim-request-{index+1}', 'pickup': data['origin'], 'destination': data['destination'],
                 'distance_m': route['distance_m'], 'duration_s': route['duration_s']+data['waiting_s'],
                 'max_wait_s': 600, 'passengers': 1} for index in range(state['demand']['scenario_expected'])]
    blocked = state['route_error'] or data['has_open_emergency']
    distances = [[None if blocked else row[0] for _ in requests] for row in matrix['distance_matrix_m']]
    durations = [[None if blocked else row[0] for _ in requests] for row in matrix['duration_matrix_s']]
    allocation = optimize_dispatch({'vehicles': data['vehicles'], 'requests': requests,
                                    'distance_matrix_m': distances, 'duration_matrix_s': durations,
                                    'routing_verified': route['verified'] and matrix['verified']})
    for item in allocation['assignments']:
        item['pickup_seconds'] = item['pickup_duration_s']
    return {'allocation': allocation}


def reviewer_agent(state):
    """Independent guards before a result is saved; this is not an approval."""
    data, fare, refund = state['snapshot'], state['fare'], state['refund']
    allocations = state['allocation']['assignments']
    signals = []
    invariant_ok = (len({a['vehicle_id'] for a in allocations}) == len(allocations)
                    and len({a['request_id'] for a in allocations}) == len(allocations)
                    and all(a['energy']['feasible'] for a in allocations)
                    and Decimal(0) <= Decimal(refund['refund_vnd']) <= Decimal(refund['remaining_refundable_vnd'])
                    and Decimal(fare['total_vnd']) >= 0
                    and fare['money_moved'] is False and refund['money_moved'] is False)
    if not invariant_ok:
        raise ValueError('Operations invariant rejected')
    if state['route_error']:
        signals.append({'code': 'ROUTE_UNAVAILABLE', 'severity': 'blocking', 'summary': 'OSRM lỗi hoặc không có tuyến hợp lệ; đã chặn đề xuất phân xe.'})
    elif not state['route']['verified']:
        signals.append({'code': 'ROAD_UNVERIFIED', 'severity': 'warning', 'summary': 'Chưa xác minh đường bộ; phân xe chỉ minh họa trên khoảng cách giả định.'})
    if not state['battery']['feasible']:
        signals.append({'code': 'ENERGY_RESERVE', 'severity': 'warning', 'summary': 'Xe mẫu không đủ pin giữ mức dự trữ đến đích/trạm; không khuyến nghị tự lái đến trạm.'})
    if data['has_open_emergency']:
        signals.append({'code': 'OPEN_EMERGENCY', 'severity': 'blocking', 'summary': 'Chuyến đang có hồ sơ khẩn; ưu tiên HITL hiện có, không đề xuất phân xe trong kịch bản này.'})
    if Decimal(refund['refund_vnd']) > 0:
        signals.append({'code': 'FARE_MISMATCH', 'severity': 'review', 'summary': 'Có chênh lệch trong cước giả lập cần đối soát; chưa kết luận gian lận và chưa hoàn tiền.'})
    if state['allocation']['unserved']:
        signals.append({'code': 'UNSERVED_DEMAND', 'severity': 'warning', 'summary': f"{len(state['allocation']['unserved'])} yêu cầu giả lập chưa có xe thỏa điều kiện."})
    blocked = state['route_error'] or data['has_open_emergency'] or not state['allocation']['constraints_checked']
    status = 'BLOCKED' if blocked else ('PARTIAL' if signals else 'COMPLETED')
    descriptions = [
        ('supervisor', 'Agent điều phối', f"Ưu tiên {dict(energy='pin / sạc', fare='cước phí', demand='cung – cầu')[state['supervisor']['focus']]}; mọi kiểm tra bắt buộc đều đã chạy."),
        ('routing', 'Agent không gian / lộ trình', 'PostGIS/H3 và OSRM nếu được cấu hình; nguồn/độ xác minh được giữ trong kết quả.'),
        ('finance', 'Agent cước / hoàn tiền', 'Công cụ Decimal tính biểu giá mẫu và trần hoàn; không chuyển tiền.'),
        ('energy', 'Agent pin / sạc', 'Đối chiếu năng lượng, dự trữ, đường đến trạm và hàng chờ giả định.'),
        ('demand', 'Agent nhu cầu', 'Tổng hợp ô H3 và áp dụng hệ số kịch bản được ghi rõ; không gọi là mô hình thời tiết thực.'),
        ('allocation', 'Agent phân xe', 'OR-Tools chọn nhiều yêu cầu phục vụ nhất rồi giảm thời gian tới điểm đón.'),
        ('reviewer', 'Agent kiểm chứng', 'Kiểm tra không dùng trùng xe/yêu cầu, pin đủ theo mô hình và hoàn tiền trong giới hạn.'),
    ]
    report = {key: state[key] for key in ('route', 'fare', 'refund', 'battery', 'charging', 'demand', 'allocation')}
    report.update({'schema_version': 1, 'workflow_version': WORKFLOW_VERSION,
                   'scenario_version': data['scenario_version'], 'simulation': True, 'advisory_only': True,
                   'source': data['source'], 'supervisor': state['supervisor'],
                   'captured_at': data['captured_at'], 'trip_version': data['trip_version'],
                   'summary': f"{data['scenario_label']}: {len(allocations)}/{state['demand']['scenario_expected']} yêu cầu giả lập có phương án phân xe. "
                              + ('Có ràng buộc đang chặn.' if blocked else 'Kết quả là đề xuất mô phỏng theo dữ liệu và giả định đã ghi.'),
                   'trace': [{'agent': agent, 'label': label, 'status': 'checked', 'summary': summary}
                             for agent, label, summary in descriptions],
                   'signals': signals, 'assumptions': data['assumptions'],
                   'limitations': ['Không phải dữ liệu pin/đơn hàng/thời tiết live của xe đang chọn.',
                       'OSRM xác minh kết quả định tuyến trên bản đồ, không xác nhận an toàn đường hoặc giao thông hiện tại.',
                       'Cước mẫu VND và pin tuyến tính chưa được hiệu chuẩn bằng dữ liệu vận hành thực.',
                       'Phương án một lượt, tối đa một yêu cầu/xe; chưa tối ưu cả ca, đa điểm đón hoặc đặt chỗ sạc.',
                       'Mọi hành động khẩn tiếp tục cần phê duyệt phía backend theo quy trình sự cố.'],
                   'invariants_checked': True})
    return {'status': status, 'report': report}


def build_operations_graph():
    graph = StateGraph(OperationState)
    graph.add_node('supervisor', lambda state: {'supervisor': choose_focus(state['snapshot'])})
    for name, node in [('routing', routing_agent), ('finance', finance_agent), ('energy', energy_agent),
                       ('demand', demand_agent), ('allocation', allocation_agent), ('reviewer', reviewer_agent)]:
        graph.add_node(name, node)
    graph.add_edge(START, 'supervisor')
    graph.add_edge('supervisor', 'routing')
    # All specialists run; the focus changes finance/energy processing order.
    graph.add_conditional_edges('routing', lambda state: 'energy' if state['supervisor']['focus'] == 'energy' else 'finance')
    graph.add_conditional_edges('finance', lambda state: 'demand' if 'battery' in state else 'energy')
    graph.add_conditional_edges('energy', lambda state: 'demand' if 'fare' in state else 'finance')
    graph.add_edge('demand', 'allocation')
    graph.add_edge('allocation', 'reviewer')
    graph.add_edge('reviewer', END)
    return graph.compile()


_graph = build_operations_graph()


def assess(snapshot):
    result = _graph.invoke({'snapshot': snapshot}, config={'recursion_limit': 16})
    return {'status': result['status'], 'report': result['report']}
