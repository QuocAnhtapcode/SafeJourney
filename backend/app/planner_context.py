"""Bounded evidence and verification playbooks; no identities or GPS coordinates."""
import math


NUMERIC_FIELDS = {
    'SPEED': ('speed_kmh', 'speed_threshold_kmh', 'observed_duration_seconds', 'threshold_seconds', 'accuracy_m'),
    'STOP': ('speed_kmh', 'stop_threshold_kmh', 'observed_duration_seconds', 'threshold_seconds', 'accuracy_m'),
    'DEVIATION': ('route_tolerance_m', 'observed_duration_seconds', 'threshold_seconds', 'accuracy_m'),
    'GPS_LOST': ('missing_seconds', 'threshold_seconds'),
}
CHECKS = {
    'SPEED': {
        'check_speed_samples': 'Đối chiếu chuỗi tốc độ trước/sau cảnh báo và chất lượng GPS để loại trừ điểm nhiễu.',
        'check_road_context': 'Đối chiếu loại đường và ngưỡng cảnh báo áp dụng cho chuyến.',
        'contact_driver_safely': 'Chọn kênh liên hệ an toàn, yêu cầu tài xế phản hồi khi có thể dừng an toàn.',
    },
    'STOP': {
        'check_stop_context': 'Đối chiếu điểm đón/trả, đèn đỏ hoặc ùn tắc để xác minh lý do dừng.',
        'check_stop_samples': 'Kiểm tra chuỗi mẫu và chất lượng GPS để xác nhận xe thực sự đứng yên.',
        'contact_driver_safely': 'Liên hệ tài xế qua kênh an toàn để xác minh tình trạng chuyến.',
    },
    'DEVIATION': {
        'check_route_and_gps': 'Đối chiếu tuyến đã được duyệt, vị trí gần đây và chất lượng GPS.',
        'check_detour_reason': 'Xác minh có đường cấm, đổi tuyến được chấp thuận hoặc chỉ dẫn giao thông hay không.',
        'contact_driver_safely': 'Chọn kênh liên hệ an toàn để hỏi lý do thay đổi hành trình.',
    },
    'GPS_LOST': {
        'check_device_network': 'Kiểm tra mạng di động, nguồn điện và ứng dụng gửi GPS của thiết bị.',
        'check_area_outage': 'Đối chiếu các xe cùng khu vực để nhận biết mất tín hiệu diện rộng.',
        'contact_driver_safely': 'Chọn kênh liên hệ thay thế an toàn để xác minh tình trạng chuyến.',
    },
    'SOS': {
        'choose_safe_channel': 'Ưu tiên tiếp nhận SOS và chọn kênh liên hệ không làm tăng rủi ro cho người gửi.',
        'verify_immediate_safety': 'Xác minh tình trạng an toàn và nhu cầu hỗ trợ; không tự suy đoán nguyên nhân SOS.',
        'human_emergency_review': 'Nhân viên xem xét mức khẩn và phê duyệt trước mọi hành động hỗ trợ khẩn.',
    },
}
DEFAULT_CHECKS = {'verify_evidence': 'Nhân viên kiểm tra bằng chứng còn thiếu và xác minh tình trạng chuyến.'}
FIRST_CHECK = {'SPEED': 'check_speed_samples', 'STOP': 'check_stop_samples',
               'DEVIATION': 'check_route_and_gps', 'GPS_LOST': 'check_device_network',
               'SOS': 'choose_safe_channel'}


def safe_evidence(kind, evidence):
    """Allow only finite scalar measurements relevant to this incident kind."""
    if not isinstance(evidence, dict):
        return {}
    result = {}
    for key in NUMERIC_FIELDS.get(kind, ()):
        value = evidence.get(key)
        if type(value) in (int, float) and 0 <= value <= 1e9 and math.isfinite(value):
            result[key] = value
    if kind == 'DEVIATION' and type(evidence.get('outside_route')) is bool:
        result['outside_route'] = evidence['outside_route']
    if kind == 'SOS' and evidence.get('source_role') in ('driver', 'passenger'):
        result['source_role'] = evidence['source_role']
    return result


def context(kind, evidence):
    e = safe_evidence(kind, evidence)
    facts = {}
    def measurement(key, label, unit):
        if key in e:
            facts[key] = f'{label}: {e[key]:.2f}'.rstrip('0').rstrip('.') + f' {unit}.'
    if kind in ('SPEED', 'STOP'):
        measurement('speed_kmh', 'Tốc độ ghi nhận', 'km/h')
        if kind == 'SPEED':
            measurement('speed_threshold_kmh', 'Ngưỡng luật SPEED là tốc độ lớn hơn', 'km/h')
        else:
            measurement('stop_threshold_kmh', 'Điều kiện STOP là tốc độ nhỏ hơn', 'km/h')
    if kind in ('SPEED', 'STOP', 'DEVIATION'):
        measurement('observed_duration_seconds', 'Điều kiện đã kéo dài', 'giây')
        measurement('threshold_seconds', 'Ngưỡng thời gian của luật', 'giây')
        measurement('accuracy_m', 'Độ chính xác GPS được thiết bị báo', 'm')
    if kind == 'DEVIATION':
        if 'outside_route' in e:
            facts['outside_route'] = 'Điểm GPS ngoài hành lang tuyến: ' + ('có.' if e['outside_route'] else 'không.')
        measurement('route_tolerance_m', 'Bán kính hành lang kiểm tra quanh tuyến', 'm')
    if kind == 'GPS_LOST':
        measurement('missing_seconds', 'Thời gian chưa nhận GPS mới', 'giây')
        measurement('threshold_seconds', 'Ngưỡng cảnh báo mất GPS', 'giây')
    if kind == 'SOS':
        roles = {'driver': 'tài xế', 'passenger': 'khách'}
        facts['signal'] = 'Đã nhận tín hiệu SOS' + (' từ ' + roles[e['source_role']] if 'source_role' in e else '') + '.'
    missing = []
    expected = {
        'SPEED': ('speed_kmh', 'speed_threshold_kmh', 'observed_duration_seconds', 'threshold_seconds'),
        'STOP': ('speed_kmh', 'stop_threshold_kmh', 'observed_duration_seconds', 'threshold_seconds'),
        'DEVIATION': ('outside_route', 'route_tolerance_m', 'observed_duration_seconds', 'threshold_seconds'),
        'GPS_LOST': ('missing_seconds', 'threshold_seconds'),
    }
    for key in expected.get(kind, ()):
        if key not in e:
            missing.append(key)
    return facts, CHECKS.get(kind, DEFAULT_CHECKS), missing


def selection_schema(facts, checks):
    return {'type': 'object', 'additionalProperties': False,
            'properties': {
                'evidence_keys': {'type': 'array', 'uniqueItems': True,
                    'minItems': 1 if facts else 0, 'maxItems': len(facts),
                    'items': {'type': 'string', 'enum': list(facts)} if facts else {'type': 'string'}},
                'check_ids': {'type': 'array', 'uniqueItems': True, 'minItems': 1,
                    'maxItems': min(3, len(checks)), 'items': {'type': 'string', 'enum': list(checks)}}},
            'required': ['evidence_keys', 'check_ids']}


def validate_selection(value, facts, checks):
    if not isinstance(value, dict) or set(value) != {'evidence_keys', 'check_ids'}:
        raise ValueError('Invalid selection fields')
    for key, choices, minimum in [('evidence_keys', facts, 1 if facts else 0), ('check_ids', checks, 1)]:
        values = value[key]
        maximum = min(3, len(choices)) if key == 'check_ids' else len(choices)
        if (not isinstance(values, list) or not minimum <= len(values) <= maximum
                or not all(isinstance(item, str) and item in choices for item in values)
                or len(set(values)) != len(values)):
            raise ValueError('Unknown or repeated evidence/check reference')
    return value['check_ids']


def render_advice(kind, evidence, selected=None):
    facts, checks, missing = context(kind, evidence)
    basis = ' '.join(facts.values()) or f'Hồ sơ {kind} chưa có số đo đủ dùng để giải thích.'
    if missing:
        basis += ' Hồ sơ thiếu một số số đo/ngưỡng tại lúc phát hiện; không suy ra từ cấu hình hiện tại.'
    selected = list(selected if selected is not None else list(checks)[:2])
    first = FIRST_CHECK.get(kind)
    if first:
        selected = [first] + [key for key in selected if key != first]
    steps = ' '.join(checks[key] for key in selected)
    limit = ('Mất GPS không xác nhận tai nạn hoặc vị trí hiện tại.' if kind == 'GPS_LOST' else
             'Tín hiệu SOS chưa xác nhận nguyên nhân; hành động khẩn cần nhân viên phê duyệt.' if kind == 'SOS' else
             'Bằng chứng này mô tả điều kiện cảnh báo, chưa xác nhận nguyên nhân thực tế.')
    return f'Căn cứ phát hiện: {basis}\nCần xác minh: {steps}\nGiới hạn: {limit}'
