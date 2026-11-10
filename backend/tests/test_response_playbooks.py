import pytest
from app.response_playbooks import build_response_plan, confirmed_reason, reason_options, revised_message


@pytest.mark.parametrize('kind', ['SPEED', 'STOP', 'DEVIATION', 'GPS_LOST', 'SOS'])
def test_prepared_action_is_concrete_but_never_claims_execution_or_safety(kind):
    plan = build_response_plan({'kind': kind, 'severity': 3 if kind == 'SOS' else 2,
                               'evidence': {'private_note': 'PRIVATE', 'lat': 'PRIVATE'}},
                              {'id': 'synthetic-trip', 'driver_id': 'driver'})
    assert plan['action']['message'] and plan['action']['recipient']['ref']
    assert plan['simulation'] is True and plan['source'] == 'backend_playbook'
    assert 'PRIVATE' not in str(plan)
    assert plan['follow_up_seconds'] == 120
    if kind == 'SOS':
        assert plan['action']['channel'] == 'INTERNAL'
        assert plan['action']['recipient']['role'] == 'safety_team'
    else:
        assert plan['action']['recipient']['ref'] == 'driver'


def test_edit_is_copy_and_keeps_fixed_recipient_and_safety_boundary():
    plan = build_response_plan({'kind': 'SOS', 'severity': 3}, {'id': 'demo', 'driver_id': 'driver'})
    edited = revised_message(plan, '  Nội dung đã được nhân viên kiểm tra  ')
    assert edited['action']['message'] == 'Nội dung đã được nhân viên kiểm tra'
    assert plan['action']['message'] != edited['action']['message']
    assert plan['action']['recipient'] == edited['action']['recipient']
    with pytest.raises(ValueError):
        revised_message(plan, '      ')


def test_shortcuts_require_a_matching_confirmation_and_custom_exception_text():
    assert 'Nhân viên xác nhận' in confirmed_reason('SOS', 'verified_safe', None)
    assert 'gps_restored' not in {r['code'] for r in reason_options('SOS')}
    for code, text in [('gps_restored', None), ('unknown', None), ('verified_safe', 'override'), ('other', '     '), (None, None)]:
        with pytest.raises(ValueError):
            confirmed_reason('SOS', code, text)
    assert confirmed_reason('SOS', 'other', 'Đã kiểm tra riêng') == 'Đã kiểm tra riêng'
    assert 'Bàn giao' in confirmed_reason('SOS', 'shift_handoff', None, release=True)
