"""Participant confirmation of simulated contact; no operator impersonation."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from ..db import connect, log, changed
from ..security import current_user, check_trip
from ..schemas import ContactReply
from ..autoplaybooks import escalate_to_human

router = APIRouter()


@router.get('/api/contact-requests')
def contact_requests(user=Depends(current_user)):
    if user['role'] not in ('driver', 'passenger'):
        raise HTTPException(403, 'Dành cho người nhận yêu cầu xác nhận')
    with connect() as conn:
        # An explicit narrow projection: no incident evidence, assignment or LLM text.
        return conn.execute("""SELECT p.id,p.incident_id,i.trip_id,p.created_at,p.follow_up_due_at,
            p.response_plan->'action'->>'channel' AS channel,
            p.response_plan->'action'->>'message' AS message
            FROM proposals p JOIN incidents i ON i.id=p.incident_id JOIN trips t ON t.id=i.trip_id
            WHERE i.status='OPEN' AND i.automation_state='WAITING_RESPONSE'
              AND p.status='EXECUTED' AND p.execution_mode='AUTO' AND p.recipient_ref=%s
              AND (t.driver_id=%s OR t.passenger_id=%s)
              AND NOT EXISTS (SELECT 1 FROM contact_replies r WHERE r.proposal_id=p.id)
              AND NOT EXISTS (SELECT 1 FROM proposals n WHERE n.incident_id=i.id AND (n.created_at,n.id)>(p.created_at,p.id))
            ORDER BY p.created_at DESC,p.id LIMIT 100""", (user['id'], user['id'], user['id'])).fetchall()


@router.post('/api/contact-requests/{proposal_id}/reply')
def reply(proposal_id: UUID, body: ContactReply, user=Depends(current_user)):
    if user['role'] not in ('driver', 'passenger'):
        raise HTTPException(403, 'Chỉ người nhận được xác nhận, operator không được giả phản hồi')
    with connect() as conn:
        original = conn.execute('SELECT i.trip_id,i.id FROM incidents i JOIN proposals p ON p.incident_id=i.id WHERE p.id=%s', (proposal_id,)).fetchone()
        if not original:
            raise HTTPException(404, 'Không tìm thấy yêu cầu')
        trip = conn.execute('SELECT * FROM trips WHERE id=%s FOR UPDATE', (original['trip_id'],)).fetchone()
        check_trip(trip, user)
        inc = conn.execute('SELECT * FROM incidents WHERE id=%s FOR UPDATE', (original['id'],)).fetchone()
        proposal = conn.execute('SELECT * FROM proposals WHERE id=%s FOR UPDATE', (proposal_id,)).fetchone()
        if proposal['recipient_ref'] != user['id'] or proposal['execution_mode'] != 'AUTO' or proposal['status'] != 'EXECUTED':
            raise HTTPException(404, 'Không tìm thấy yêu cầu dành cho bạn')
        old = conn.execute('SELECT * FROM contact_replies WHERE request_id=%s OR proposal_id=%s', (body.request_id, proposal_id)).fetchall()
        if old:
            if len(old) == 1 and old[0]['request_id'] == body.request_id and old[0]['proposal_id'] == proposal_id and old[0]['actor_id'] == user['id'] and old[0]['outcome'] == body.outcome:
                return {'status': 'received', 'duplicate': True}
            raise HTTPException(409, 'Yêu cầu đã được xác nhận hoặc mã gửi đã sử dụng')
        if inc['status'] != 'OPEN':
            raise HTTPException(409, 'Hồ sơ đã kết thúc')
        latest = conn.execute('SELECT id FROM proposals WHERE incident_id=%s ORDER BY created_at DESC,id DESC LIMIT 1', (inc['id'],)).fetchone()
        if body.outcome == 'safe' and (latest['id'] != proposal_id or inc['severity'] == 3):
            raise HTTPException(409, 'Đã có bước xử lý mới; hãy làm mới. Xác nhận này không thể đóng hồ sơ khẩn.')
        inserted = conn.execute('INSERT INTO contact_replies(request_id,proposal_id,actor_id,outcome) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING request_id',
                               (body.request_id, proposal_id, user['id'], body.outcome)).fetchone()
        if not inserted:
            raise HTTPException(409, 'Mã xác nhận đã được sử dụng')
        if body.outcome == 'needs_help':
            escalate_to_human(conn, inc, 'Người nhận yêu cầu hỗ trợ qua phản hồi đã xác thực.')
        else:
            conn.execute("UPDATE incidents SET automation_state='MONITORING',monitor_until=clock_timestamp()+interval '60 seconds' WHERE id=%s", (inc['id'],))
        log(conn.cursor(), inc['id'], 'recipient_confirmation',
            f"{user['role']} {user['id']} phản hồi: {body.outcome}. "
            + ('Chuyển HITL.' if body.outcome == 'needs_help' else 'Tiếp tục đối chiếu tín hiệu; chưa đóng ngay.'))
        conn.execute('UPDATE trips SET version=version+1 WHERE id=%s', (trip['id'],))
        changed(conn.cursor())
    return {'status': 'received', 'duplicate': False}
