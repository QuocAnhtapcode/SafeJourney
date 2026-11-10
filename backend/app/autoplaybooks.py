"""Durable, bounded routine contact: SMS -> call -> emergency human review.

All dispatches are simulations. A transport success is never a recipient reply.
Only backend policy may dispatch routine templates. No external emergency action
is sent here, even if the LLM asks for one.
"""
from datetime import timedelta
from uuid import uuid4
from psycopg.types.json import Jsonb
from .db import connect, log, changed
from .response_playbooks import build_response_plan

ROUTINE_KINDS = {'STOP', 'SPEED', 'DEVIATION', 'GPS_LOST'}


def dispatch_routine(conn, incident, proposal):
    plan = proposal['response_plan']
    if (incident['status'] != 'OPEN' or incident['severity'] >= 3 or incident['kind'] not in ROUTINE_KINDS
            or proposal['execution_mode'] != 'AUTO' or proposal['status'] != 'PENDING'
            or not plan or plan.get('requires_human') is not False
            or plan['action']['channel'] not in ('SMS', 'CALL') or plan.get('operator_edited')
            or proposal['contact_attempt'] not in (1, 2)):
        return False
    trip = conn.execute('SELECT driver_id FROM trips WHERE id=%s', (incident['trip_id'],)).fetchone()
    if conn.execute("SELECT 1 FROM incidents WHERE trip_id=%s AND status='OPEN' AND severity=3", (incident['trip_id'],)).fetchone():
        return False
    if plan['action']['recipient']['ref'] != trip['driver_id'] or plan['incident_severity'] != incident['severity']:
        return False
    inserted = conn.execute("""INSERT INTO mock_actions(id,proposal_id,approved_by,payload)
        VALUES (%s,%s,NULL,%s) ON CONFLICT (proposal_id) DO NOTHING RETURNING id""",
        (uuid4(), proposal['id'], Jsonb({'type': proposal['action_type'], 'mode': 'SIMULATION',
            'authorized_by': 'BACKEND_ROUTINE_POLICY_V1', 'body': plan['action']['message'],
            'recipient_ref': plan['action']['recipient']['ref'], 'response_plan': plan,
            'proposal_revision': proposal['revision'], 'delivery_status': 'SIMULATED',
            'recipient_confirmed': False}))).fetchone()
    if not inserted:
        return False
    conn.execute("""UPDATE proposals SET status='EXECUTED',follow_up_due_at=clock_timestamp()+interval '120 seconds'
        WHERE id=%s""", (proposal['id'],))
    conn.execute("UPDATE incidents SET automation_state='WAITING_RESPONSE',monitor_until=NULL,needs_plan=false WHERE id=%s", (incident['id'],))
    log(conn.cursor(), incident['id'], 'agent_contact',
        f"Agent chạy {plan['action']['channel']} MÔ PHỎNG, lần {proposal['contact_attempt']}/2. "
        'Chờ người nhận xác nhận; chưa có phản hồi thực tế.')
    return True


def escalate_to_human(conn, incident, reason):
    """Called while holding trip then incident locks; creates an unapproved emergency plan."""
    if incident['status'] != 'OPEN':
        return
    conn.execute("UPDATE proposals SET status='CANCELLED' WHERE incident_id=%s AND status='PENDING'", (incident['id'],))
    incident = {**incident, 'severity': 3}
    trip = conn.execute('SELECT id,driver_id FROM trips WHERE id=%s', (incident['trip_id'],)).fetchone()
    plan = build_response_plan(incident, trip, outcome='needs_help')
    # No response is uncertainty, not evidence that an accident happened.
    plan['title'] = 'Cần nhân viên đánh giá tình huống khẩn'
    plan['action']['message'] = f"Chuyến {trip['id']}: {reason} Chưa kết luận nguyên nhân. Nhân viên chọn phương án hỗ trợ và phê duyệt trước hành động khẩn."
    conn.execute("""INSERT INTO proposals(id,incident_id,action_type,recipient_ref,body,expires_at,response_plan,execution_mode,created_at)
        VALUES (%s,%s,'MOCK_EMERGENCY','safety-team-demo',%s,clock_timestamp()+interval '15 minutes',%s,'HUMAN',clock_timestamp())""",
        (uuid4(), incident['id'], reason, Jsonb(plan)))
    conn.execute("""UPDATE incidents SET severity=3,automation_state='ESCALATED',monitor_until=NULL,
        unassigned_since=CASE WHEN assigned_operator_id IS NULL THEN clock_timestamp() ELSE unassigned_since END,
        needs_plan=false,updated_at=clock_timestamp() WHERE id=%s""", (incident['id'],))
    log(conn.cursor(), incident['id'], 'agent_escalated', reason + ' Đã chuyển HITL; chưa thực thi hành động khẩn.')


def signal_clear(trip, kind, now):
    # Confirmation alone is insufficient: require fresh, good-quality telemetry
    # and a cleared flag. Unknown state fails closed into human review.
    state = trip.get('detector_state') or {}
    conditions = state.get('current_conditions')
    return (trip.get('last_seen') is not None and timedelta(0) <= now-trip['last_seen'] <= timedelta(seconds=30)
            and state.get('good_gps') is True and isinstance(conditions, dict)
            and (kind == 'GPS_LOST' or conditions.get(kind) is False))


def maintain_autoplaybooks():
    """Bounded due work; persisted deadlines survive restarts, no LLM calls or sleeping jobs."""
    with connect() as conn:
        rows = conn.execute("""SELECT i.id,i.trip_id FROM incidents i WHERE i.status='OPEN' AND i.severity<3 AND (
            (i.automation_state='MONITORING' AND i.monitor_until<=clock_timestamp()) OR
            (i.automation_state='WAITING_RESPONSE' AND EXISTS (
                SELECT 1 FROM proposals p WHERE p.incident_id=i.id AND p.execution_mode='AUTO'
                AND p.status='EXECUTED' AND p.follow_up_due_at<=clock_timestamp()
                AND NOT EXISTS (SELECT 1 FROM proposals n WHERE n.incident_id=i.id AND (n.created_at,n.id)>(p.created_at,p.id))
                AND NOT EXISTS (SELECT 1 FROM contact_replies r WHERE r.proposal_id=p.id))))
            ORDER BY i.created_at,i.id LIMIT 100""").fetchall()
    for row in rows:
        with connect() as conn:
            trip = conn.execute('SELECT * FROM trips WHERE id=%s FOR UPDATE', (row['trip_id'],)).fetchone()
            inc = conn.execute('SELECT * FROM incidents WHERE id=%s FOR UPDATE', (row['id'],)).fetchone()
            now = conn.execute('SELECT clock_timestamp() AS t').fetchone()['t']
            if not inc or inc['status'] != 'OPEN' or inc['severity'] >= 3:
                continue
            proposal = conn.execute('SELECT * FROM proposals WHERE incident_id=%s ORDER BY created_at DESC,id DESC LIMIT 1 FOR UPDATE', (inc['id'],)).fetchone()
            if not proposal or proposal['execution_mode'] != 'AUTO' or proposal['status'] != 'EXECUTED':
                continue
            if conn.execute("SELECT 1 FROM incidents WHERE trip_id=%s AND status='OPEN' AND severity=3", (trip['id'],)).fetchone():
                escalate_to_human(conn, inc, 'Cùng chuyến đang có hồ sơ khẩn; dừng playbook thông thường để nhân viên đánh giá.')
                changed(conn.cursor())
                continue
            if inc['automation_state'] == 'MONITORING' and inc['monitor_until'] and inc['monitor_until'] <= now:
                reply = conn.execute('SELECT * FROM contact_replies WHERE proposal_id=%s', (proposal['id'],)).fetchone()
                if reply and reply['outcome'] == 'safe' and signal_clear(trip, inc['kind'], now):
                    conn.execute("""UPDATE incidents SET status='RESOLVED',automation_state='COMPLETE',monitor_until=NULL,
                        needs_plan=false,updated_at=clock_timestamp(),assigned_operator_id=NULL,assigned_at=NULL,
                        assignment_expires_at=NULL,assignment_version=assignment_version+1,unassigned_since=NULL WHERE id=%s""", (inc['id'],))
                    log(conn.cursor(), inc['id'], 'agent_resolved', 'Người nhận xác nhận an toàn; hết thời gian theo dõi và tín hiệu mới nhất không còn điều kiện cảnh báo. Agent đóng hồ sơ theo policy, không phải kết luận y tế.')
                else:
                    escalate_to_human(conn, inc, 'Đã nhận xác nhận an toàn nhưng tín hiệu vẫn bất thường hoặc không đủ dữ liệu để kết thúc tự động.')
            elif (inc['automation_state'] == 'WAITING_RESPONSE' and proposal['follow_up_due_at']
                  and proposal['follow_up_due_at'] <= now):
                if conn.execute('SELECT 1 FROM contact_replies WHERE proposal_id=%s', (proposal['id'],)).fetchone():
                    continue
                if proposal['contact_attempt'] >= 2:
                    escalate_to_human(conn, inc, 'Không nhận được xác nhận sau hai lần liên hệ mô phỏng (SMS, gọi). Cần người đánh giá rủi ro; không mặc định đã có tai nạn.')
                else:
                    plan = build_response_plan(inc, trip)
                    plan['action']['channel'] = 'CALL'
                    plan['title'] = 'Gọi xác minh khi chưa nhận được phản hồi tin nhắn'
                    plan['action']['message'] = 'Cuộc gọi tự động MÔ PHỎNG. Chỉ trả lời khi đã dừng an toàn. ' + plan['action']['message']
                    next_plan = conn.execute("""INSERT INTO proposals(id,incident_id,action_type,recipient_ref,body,expires_at,
                        response_plan,execution_mode,contact_attempt,followup_of,created_at)
                        VALUES (%s,%s,'MOCK_CHECK_IN',%s,%s,clock_timestamp()+interval '15 minutes',%s,'AUTO',2,%s,clock_timestamp()) RETURNING *""",
                        (uuid4(), inc['id'], trip['driver_id'], 'Chưa có phản hồi SMS; chuyển bước gọi theo playbook.', Jsonb(plan), proposal['id'])).fetchone()
                    dispatch_routine(conn, inc, next_plan)
            else:
                continue
            conn.execute('UPDATE trips SET version=version+1 WHERE id=%s', (trip['id'],))
            changed(conn.cursor())
