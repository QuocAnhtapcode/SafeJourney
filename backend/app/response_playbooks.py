"""Prepared simulated actions and operator shortcuts; no model authorization.

Templates are deterministic. Identity resolution happens on the backend, never
in the LLM. Outcome labels describe what the human confirms, not inferred facts.
"""
from copy import deepcopy
from .planner_context import context

TEMPLATES = {
    'SPEED': ('Xác minh tốc độ qua tài xế',
              'Trung tâm ghi nhận cảnh báo tốc độ trong chuyến. Vui lòng ưu tiên lái xe an toàn, '
              'chỉ đọc và phản hồi khi đã dừng ở nơi an toàn. Bạn có cần hỗ trợ không?'),
    'STOP': ('Hỏi tình trạng dừng xe',
             'Trung tâm ghi nhận chuyến dừng lâu hơn ngưỡng theo dõi. Khi thuận tiện và an toàn, '
             'vui lòng xác nhận lý do dừng và bạn có cần hỗ trợ không.'),
    'DEVIATION': ('Xác minh thay đổi hành trình',
                  'Trung tâm ghi nhận vị trí ngoài hành lang tuyến dự kiến. Chỉ phản hồi khi đã dừng an toàn: '
                  'bạn có đang đi đường vòng được chấp thuận hoặc cần hỗ trợ không?'),
    'GPS_LOST': ('Xác minh thiết bị và tình trạng chuyến',
                 'Trung tâm chưa nhận được GPS mới của chuyến. Khi đã dừng an toàn, vui lòng kiểm tra '
                 'kết nối, nguồn thiết bị và xác nhận tình trạng chuyến. Mất GPS chưa có nghĩa là có tai nạn.'),
}

RESOLUTION_REASONS = {
    'verified_safe': ('Đã xác minh an toàn', 'Nhân viên xác nhận đã liên hệ và xác minh tình trạng an toàn của chuyến.'),
    'expected_stop': ('Dừng xe có lý do đã xác minh', 'Nhân viên xác nhận đã xác minh lý do dừng xe hợp lệ.'),
    'approved_detour': ('Đổi tuyến đã được xác minh', 'Nhân viên xác nhận đã kiểm tra và xác minh việc thay đổi tuyến được chấp thuận.'),
    'gps_restored': ('GPS đã phục hồi, đã kiểm tra', 'Nhân viên xác nhận đã kiểm tra tín hiệu GPS phục hồi và tình trạng chuyến.'),
    'duplicate': ('Hồ sơ trùng đã được đối chiếu', 'Nhân viên xác nhận đã đối chiếu hồ sơ trùng và có hồ sơ khác tiếp tục xử lý.'),
}
RELEASE_REASONS = {
    'shift_handoff': ('Bàn giao ca trực', 'Bàn giao ca trực; hồ sơ chưa đóng và cần người tiếp nhận.'),
    'specialist_review': ('Cần người có chuyên môn phù hợp', 'Cần nhân viên có chuyên môn phù hợp tiếp nhận xác minh; hồ sơ chưa đóng.'),
    'capacity': ('Chuyển bớt hồ sơ đang xử lý', 'Chuyển hồ sơ về hàng đợi để phân công lại do lượng việc hiện tại.'),
}


def reason_options(kind, *, release=False):
    options = RELEASE_REASONS if release else RESOLUTION_REASONS
    allowed = {'expected_stop': 'STOP', 'approved_detour': 'DEVIATION', 'gps_restored': 'GPS_LOST'}
    return [{'code': code, 'label': label, 'text': text} for code, (label, text) in options.items()
            if release or code not in allowed or allowed[code] == kind]


def confirmed_reason(kind, code, text, *, release=False):
    if code and code != 'other':
        option = next((item for item in reason_options(kind, release=release) if item['code'] == code), None)
        if not option:
            raise ValueError('Lựa chọn không phù hợp loại hồ sơ')
        if text and text.strip():
            raise ValueError('Chọn trường hợp đặc biệt nếu cần nhập lý do riêng')
        return f"[{code}] {option['text']}"
    if not text or not 5 <= len(text.strip()) <= 500:
        raise ValueError('Trường hợp đặc biệt cần lý do từ 5 đến 500 ký tự')
    return text.strip()


def build_response_plan(incident, trip, *, outcome=None):
    """Pure plan builder; no sending, calls, decisions, or invented observations."""
    kind, severity = incident['kind'], incident['severity']
    internal = kind == 'SOS' or severity == 3 or kind not in TEMPLATES or outcome is not None
    if internal:
        title = ('Chuyển ca trực xem xét hỗ trợ khẩn' if outcome == 'needs_help' or severity == 3
                 else 'Nhờ ca trực xác minh khi chưa liên hệ được')
        recipient = {'role': 'safety_team', 'ref': 'safety-team-demo', 'label': 'Ca trực an toàn (mô phỏng)'}
        trigger = ('Nhân viên báo cần hỗ trợ.' if outcome == 'needs_help' else
                   'Nhân viên báo chưa liên hệ được; chưa kết luận có tai nạn.' if outcome == 'no_response' else
                   'Có tín hiệu cần xác minh, chưa kết luận nguyên nhân.')
        message = (f'Hồ sơ {kind}, chuyến {trip["id"]}, mức {severity}. {trigger} '
                   'Vui lòng rà soát kênh liên hệ an toàn và nhu cầu hỗ trợ. '
                   'Mọi liên hệ lực lượng khẩn cần người có thẩm quyền phê duyệt riêng.')
        channel = 'INTERNAL'
    else:
        title, message = TEMPLATES[kind]
        recipient = {'role': 'driver', 'ref': trip['driver_id'], 'label': 'Tài xế của chuyến'}
        channel = 'SMS'
    facts, checks, missing = context(kind, incident.get('evidence'))
    return {'schema_version': 1, 'playbook': f'{kind.lower()}-v1', 'incident_kind': kind,
            'incident_severity': severity, 'title': title,
            'action': {'channel': channel, 'recipient': recipient, 'message': message},
            'facts': list(facts.values()), 'missing_evidence': missing,
            'checklist': list(checks.values()), 'follow_up_seconds': 120,
            'follow_up': ('Ghi nhận kết quả xác minh. Nếu chưa liên hệ được hoặc cần hỗ trợ, agent chuẩn bị bước tiếp theo để duyệt.' if internal else
                          'Agent chờ người nhận xác nhận; hết hạn sẽ tự chuyển bước theo policy, chỉ nhánh khẩn cần HITL.'),
            'safety_note': ('Chỉ thông báo nội bộ; chưa tự liên hệ người gửi SOS hay lực lượng khẩn.' if internal else
                            'Không yêu cầu tài xế đọc hoặc thao tác khi đang lái xe.'),
            'source': 'backend_playbook', 'simulation': True, 'requires_human': internal}


def revised_message(plan, message):
    if not 5 <= len(message.strip()) <= 1500:
        raise ValueError('Nội dung cần từ 5 đến 1.500 ký tự')
    result = deepcopy(plan)
    result['action']['message'] = message.strip()
    result['operator_edited'] = True
    return result
