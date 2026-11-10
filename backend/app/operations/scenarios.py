"""Versioned synthetic operating assumptions anchored to a scoped trip snapshot.

No battery, weather, demand or fare observations are invented for a real driver:
the inputs below are explicitly an educational scenario, not vehicle telemetry.
"""
from copy import deepcopy

SCENARIO_VERSION = 'operations-demo-v1'
SCENARIOS = {
    'normal': {'label': 'Vận hành bình thường', 'description': 'Đối chiếu lộ trình, cước mẫu, pin và phân xe trong điều kiện giả lập.'},
    'rush_hour': {'label': 'Giờ cao điểm', 'description': 'Nhu cầu tăng và tốc độ giả định giảm; đo số yêu cầu không có xe phù hợp.'},
    'rain': {'label': 'Mưa và tăng thời gian di chuyển', 'description': 'Hệ số thời tiết giả định; chưa phải dự báo được huấn luyện với dữ liệu mưa.'},
    'low_battery': {'label': 'Pin thấp / trạm sạc có hàng chờ', 'description': 'Kiểm tra dự trữ pin, khả năng đến trạm và thời gian chờ/sạc theo công cụ.'},
    'fare_dispute': {'label': 'Đối soát cước / hoàn tiền mô phỏng', 'description': 'Tính lại cước mẫu và mức hoàn tối đa; dấu hiệu chênh lệch chưa chứng minh gian lận.'},
}


def catalog():
    return [{'id': key, **value} for key, value in SCENARIOS.items()]


def build_snapshot(trip, scenario_id, now):
    """`trip` geometry and metric length are read by PostGIS, never supplied by LLM."""
    scenario = SCENARIOS[scenario_id]
    origin = {'lat': trip['start_lat'], 'lon': trip['start_lon']}
    destination = {'lat': trip['end_lat'], 'lon': trip['end_lon']}
    profile = {'capacity_kwh': 50, 'soh_percent': 90, 'soc_percent': 65,
               'reserve_percent': 15, 'consumption_wh_per_km': 170, 'auxiliary_kw': 0.8}
    if scenario_id == 'low_battery':
        profile['soc_percent'] = 15.1
    factor = {'normal': 1, 'rush_hour': 2.5, 'rain': 1.5, 'low_battery': 1, 'fare_dispute': 1}[scenario_id]
    speed = {'rush_hour': 18, 'rain': 22}.get(scenario_id, 30)
    # Fixed historical counts are deliberately synthetic. Real TLC evaluation is separate.
    historical_counts = [3, 5, 4, 4, 6, 2, 4]
    vehicles = [{'id': f'sim-ev-{i+1}',
                 'position': {'lat': max(-90, min(90, origin['lat']+offset)), 'lon': origin['lon']},
                 'profile': deepcopy(profile),
                 'seats': 4, 'available': True} for i, offset in enumerate((0, .003, -.004, .009))]
    if scenario_id != 'low_battery':
        vehicles[-1]['profile']['soc_percent'] = 15.1
    return {
        'schema_version': 1, 'scenario_version': SCENARIO_VERSION, 'scenario_id': scenario_id,
        'scenario_label': scenario['label'], 'captured_at': now.isoformat(),
        'trip_id': trip['id'], 'trip_version': trip['version'], 'trip_status': trip['status'],
        'last_seen': trip['last_seen'].isoformat() if trip['last_seen'] else None,
        'has_open_emergency': bool(trip.get('has_open_emergency')),
        'origin': origin, 'destination': destination,
        'planned_distance_m': float(trip['planned_distance_m']),
        'profile': profile, 'vehicles': vehicles,
        'station': {'position': destination, 'station_power_kw': 50, 'vehicle_max_power_kw': 75,
                    'ports': 2, 'busy_remaining_minutes': [10, 20],
                    'queue_length': 6 if scenario_id == 'low_battery' else 2, 'queue_session_minutes': 30},
        'historical_counts': historical_counts, 'demand_factor': factor, 'speed_kmh': speed,
        'waiting_s': 600 if scenario_id in ('rush_hour', 'rain') else 0,
        'h3_resolution': 8,
        'source': 'synthetic_operations_with_stored_trip_route',
        'assumptions': [
            'Mốc đón/trả lấy từ tuyến đã lưu của chuyến; không phải vị trí hiện tại của xe.',
            'Đội xe 4 chiếc, pin, lịch nhu cầu, trạm sạc, thời tiết và cước tranh chấp đều là dữ liệu giả của kịch bản.',
            'Tuyến lưu trong PostGIS cho biết chiều dài hình học, chưa xác nhận đường đi được hoặc tình trạng giao thông.',
            'Chỉ đánh giá/đề xuất; không thay đổi tuyến, phân xe thật, chuyển tiền hoặc liên hệ khẩn.',
        ],
    }
