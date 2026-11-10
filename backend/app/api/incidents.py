from uuid import UUID, uuid4
from datetime import timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.types.json import Jsonb
from ..db import connect, changed, log
from ..schemas import Decision, Replan, Resolve, OwnershipAction, ProposalEdit, FollowUp
from ..response_playbooks import build_response_plan, confirmed_reason, reason_options, revised_message
from ..autoplaybooks import escalate_to_human
from .. import config, incident_ownership as ownership
from ..security import current_user, check_trip, operator_only

router = APIRouter()

@router.get('/api/incidents')
def incidents(limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0),
              assignment: Literal['all', 'unassigned', 'mine', 'human', 'agent'] = 'all',
              owner: Literal['all', 'unassigned', 'mine'] = 'all',
              status: Literal['all', 'open', 'resolved'] = 'all', user=Depends(current_user)):
    if assignment != 'all' or owner != 'all' or status != 'all':
        operator_only(user)
    with connect() as conn:
        rows = conn.execute("""SELECT i.*,p.proposal,u.username AS assigned_operator_username,
            clock_timestamp() AS server_time FROM incidents i
            LEFT JOIN users u ON u.id=i.assigned_operator_id
            LEFT JOIN LATERAL (SELECT row_to_json(latest) AS proposal FROM
              (SELECT * FROM proposals WHERE incident_id=i.id ORDER BY created_at DESC,id DESC LIMIT 1) latest
            ) p ON %s='operator'
            WHERE (%s='operator' OR EXISTS
              (SELECT 1 FROM sos_events s WHERE s.incident_id=i.id AND s.actor_id=%s))
              AND (%s='all' OR (%s='unassigned' AND i.status='OPEN' AND
                    (i.assigned_operator_id IS NULL OR i.assignment_expires_at<=now()))
                OR (%s='mine' AND i.status='OPEN' AND i.assigned_operator_id=%s
                    AND i.assignment_expires_at>now())
                OR (%s='human' AND i.status='OPEN' AND i.severity=3)
                OR (%s='agent' AND i.status='OPEN' AND i.severity<3 AND i.automation_state IN ('WAITING_RESPONSE','MONITORING')))
              AND (%s='all' OR i.status=%s)
              AND (%s='all' OR (i.status='OPEN' AND (
                    (%s='unassigned' AND (i.assigned_operator_id IS NULL OR i.assignment_expires_at<=now()))
                    OR (%s='mine' AND i.assigned_operator_id=%s AND i.assignment_expires_at>now()))))
            ORDER BY (i.status='OPEN') DESC,i.severity DESC,i.created_at DESC,i.id
            LIMIT %s OFFSET %s""", (user['role'], user['role'], user['id'],
                                    assignment, assignment, assignment, user['id'], assignment, assignment,
                                    status, status.upper(), owner, owner, owner, user['id'], limit, offset)).fetchall()
        for row in rows:
            # Participants see only a generic receipt; private SOS evidence stays with operators.
            if user['role'] != 'operator':
                row['summary'] = 'Trung tâm đã ghi nhận tín hiệu của chuyến.'
                row['kind'] = 'MY_SOS'
                row['evidence'] = {}
                row['proposal'] = None
                for key in ('assigned_operator_id', 'assigned_operator_username', 'assigned_at',
                            'assignment_expires_at', 'assignment_version', 'unassigned_since', 'server_time', 'acknowledged_by', 'automation_state', 'monitor_until'):
                    row.pop(key, None)
            else:
                row['assignment_lease_seconds'] = config.INCIDENT_LEASE_SECONDS
        return rows


def locked_incident(conn, incident_id, user):
    inc = conn.execute('SELECT * FROM incidents WHERE id=%s', (incident_id,)).fetchone()
    if not inc:
        raise HTTPException(404, 'Không tìm thấy sự cố')
    trip = conn.execute('SELECT id,driver_id,passenger_id FROM trips WHERE id=%s FOR UPDATE', (inc['trip_id'],)).fetchone()
    check_trip(trip, user)
    return conn.execute('SELECT * FROM incidents WHERE id=%s FOR UPDATE', (incident_id,)).fetchone()


@router.get('/api/incidents/{incident_id}')
def incident_detail(incident_id: UUID, user=Depends(current_user)):
    operator_only(user)
    with connect() as conn:
        row = conn.execute("""SELECT i.*,u.username AS assigned_operator_username,p.proposal,
            clock_timestamp() AS server_time FROM incidents i
            LEFT JOIN users u ON u.id=i.assigned_operator_id
            LEFT JOIN LATERAL (SELECT row_to_json(latest) AS proposal FROM
                (SELECT * FROM proposals WHERE incident_id=i.id ORDER BY created_at DESC,id DESC LIMIT 1) latest
            ) p ON true WHERE i.id=%s""", (incident_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Không tìm thấy sự cố')
        row['assignment_lease_seconds'] = config.INCIDENT_LEASE_SECONDS
        row['resolution_options'] = reason_options(row['kind'])
        row['release_options'] = reason_options(row['kind'], release=True)
        return row


@router.get('/api/incidents/{incident_id}/timeline')
def timeline(incident_id: UUID, user=Depends(current_user)):
    operator_only(user)
    with connect() as conn:
        if not conn.execute('SELECT id FROM incidents WHERE id=%s', (incident_id,)).fetchone():
            raise HTTPException(404, 'Không tìm thấy sự cố')
        return conn.execute('SELECT * FROM (SELECT * FROM incident_events WHERE incident_id=%s ORDER BY id DESC LIMIT 500) recent ORDER BY id', (incident_id,)).fetchall()


@router.post('/api/incidents/{incident_id}/decision')
def decision(incident_id: UUID, body: Decision, user=Depends(current_user)):
    operator_only(user)
    error = None
    with connect() as conn:
        inc = locked_incident(conn, incident_id, user)
        now = ownership.require_owner(conn, inc, user, body.assignment_version)
        proposal = conn.execute('SELECT * FROM proposals WHERE id=%s AND incident_id=%s FOR UPDATE', (body.proposal_id, incident_id)).fetchone()
        if not proposal or proposal['status'] != 'PENDING' or inc['status'] != 'OPEN':
            raise HTTPException(409, 'Đề xuất không còn chờ duyệt')
        if proposal['execution_mode'] != 'HUMAN':
            raise HTTPException(409, 'Bước thông thường do agent xử lý; không cần phê duyệt thủ công')
        if proposal['response_plan']:
            if body.proposal_revision != proposal['revision']:
                raise HTTPException(409, 'Nội dung đề xuất đã thay đổi. Hãy đọc lại trước khi duyệt.')
            if proposal['response_plan']['incident_severity'] != inc['severity']:
                raise HTTPException(409, 'Mức độ sự cố đã thay đổi; cần đề xuất mới.')
        if proposal['expires_at'] <= now:
            conn.execute("UPDATE proposals SET status='EXPIRED' WHERE id=%s", (body.proposal_id,))
            log(conn.cursor(), incident_id, 'expired', 'Đề xuất hết hạn; không thực thi.')
            error = 'Đề xuất đã hết hạn'
        else:
            status = 'EXECUTED' if body.approve else 'REJECTED'
            if body.approve:
                plan = proposal['response_plan']
                payload = {'type': proposal['action_type'], 'body': plan['action']['message'] if plan else proposal['body'],
                           'recipient_ref': proposal['recipient_ref'], 'mode': 'SIMULATION',
                           'assignment_version': body.assignment_version, 'proposal_revision': proposal['revision'],
                           'response_plan': plan}
                conn.execute('INSERT INTO mock_actions(id,proposal_id,approved_by,payload) VALUES (%s,%s,%s,%s)',
                             (uuid4(), body.proposal_id, user['id'], Jsonb(payload)))
                if plan:
                    conn.execute('UPDATE proposals SET follow_up_due_at=%s WHERE id=%s',
                                 (now + timedelta(seconds=plan['follow_up_seconds']), body.proposal_id))
            conn.execute('UPDATE proposals SET status=%s,approved_by=%s WHERE id=%s', (status, user['id'], body.proposal_id))
            log(conn.cursor(), incident_id, status, f"{user['username']}, phiên xử lý {body.assignment_version}: {status}. Chỉ ghi kết quả mô phỏng trong database.")
        conn.execute('UPDATE trips SET version=version+1 WHERE id=%s', (inc['trip_id'],))
        changed(conn.cursor())
    if error:
        raise HTTPException(409, error)
    return {'status': status, 'simulation': True}


def pending_proposal(conn, incident_id, proposal_id, now):
    proposal = conn.execute('SELECT * FROM proposals WHERE id=%s AND incident_id=%s FOR UPDATE',
                            (proposal_id, incident_id)).fetchone()
    if not proposal or proposal['status'] != 'PENDING' or proposal['expires_at'] <= now:
        raise HTTPException(409, 'Đề xuất không còn chờ duyệt hoặc đã hết hạn')
    return proposal


@router.post('/api/incidents/{incident_id}/prepare')
def prepare_legacy_plan(incident_id: UUID, body: Replan, user=Depends(current_user)):
    """Upgrade an existing pending proposal explicitly; GET never changes a draft."""
    operator_only(user)
    with connect() as conn:
        inc = locked_incident(conn, incident_id, user)
        now = ownership.require_owner(conn, inc, user, body.assignment_version)
        proposal = pending_proposal(conn, incident_id, body.proposal_id, now)
        if not proposal['response_plan']:
            trip = conn.execute('SELECT id,driver_id FROM trips WHERE id=%s', (inc['trip_id'],)).fetchone()
            plan = build_response_plan(inc, trip)
            conn.execute('UPDATE proposals SET response_plan=%s,recipient_ref=%s,revision=revision+1 WHERE id=%s',
                         (Jsonb(plan), plan['action']['recipient']['ref'], proposal['id']))
            log(conn.cursor(), incident_id, 'plan_prepared', f"{user['username']} yêu cầu chuẩn bị gói xử lý; chưa duyệt.")
            ownership.assignment_changed(conn, inc)
    return {'status': 'prepared'}


@router.post('/api/incidents/{incident_id}/proposal-edit')
def edit_proposal(incident_id: UUID, body: ProposalEdit, user=Depends(current_user)):
    operator_only(user)
    with connect() as conn:
        inc = locked_incident(conn, incident_id, user)
        now = ownership.require_owner(conn, inc, user, body.assignment_version)
        proposal = pending_proposal(conn, incident_id, body.proposal_id, now)
        if not proposal['response_plan'] or proposal['revision'] != body.proposal_revision:
            raise HTTPException(409, 'Đề xuất đã thay đổi; hãy làm mới rồi kiểm tra lại')
        try:
            plan = revised_message(proposal['response_plan'], body.message)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if plan['action']['message'] == proposal['response_plan']['action']['message']:
            return {'revision': proposal['revision']}
        conn.execute('UPDATE proposals SET response_plan=%s,revision=revision+1 WHERE id=%s', (Jsonb(plan), proposal['id']))
        # Text changes remain in the private audit so superseded content can be reviewed.
        log(conn.cursor(), incident_id, 'plan_edited',
            f"{user['username']} sửa bản {proposal['revision']} → {proposal['revision']+1}. "
            f"Nội dung trước: {proposal['response_plan']['action']['message']}\nNội dung mới: {plan['action']['message']}")
        ownership.assignment_changed(conn, inc)
    return {'revision': proposal['revision'] + 1}


@router.post('/api/incidents/{incident_id}/follow-up')
def follow_up(incident_id: UUID, body: FollowUp, user=Depends(current_user)):
    """Human-reported outcome creates a new unapproved action, exactly once per parent."""
    operator_only(user)
    with connect() as conn:
        inc = locked_incident(conn, incident_id, user)
        ownership.require_owner(conn, inc, user, body.assignment_version)
        proposal = conn.execute('SELECT * FROM proposals WHERE id=%s AND incident_id=%s FOR UPDATE',
                                (body.proposal_id, incident_id)).fetchone()
        if not proposal or proposal['status'] != 'EXECUTED' or not proposal['response_plan']:
            raise HTTPException(409, 'Chỉ ghi nhận tiếp sau một gói xử lý đã được duyệt')
        recorded = proposal['operator_outcome']
        if recorded:
            if recorded['request_id'] == str(body.request_id) and recorded['code'] == body.outcome:
                return {'proposal_id': recorded['next_proposal_id'], 'duplicate': True}
            raise HTTPException(409, 'Bước này đã có kết quả xác minh; hãy làm mới hồ sơ')
        latest = conn.execute('SELECT id FROM proposals WHERE incident_id=%s ORDER BY created_at DESC,id DESC LIMIT 1',
                              (incident_id,)).fetchone()
        if latest['id'] != proposal['id'] or inc['needs_plan']:
            raise HTTPException(409, 'Đã có diễn biến hoặc đề xuất mới; hãy làm mới hồ sơ')
        if body.outcome == 'needs_help':
            inc['severity'] = 3
        trip = conn.execute('SELECT id,driver_id FROM trips WHERE id=%s', (inc['trip_id'],)).fetchone()
        plan = build_response_plan(inc, trip, outcome=body.outcome)
        next_id = uuid4()
        conn.execute("""INSERT INTO proposals(id,incident_id,action_type,recipient_ref,body,expires_at,response_plan,followup_of,created_at)
            VALUES (%s,%s,%s,%s,%s,clock_timestamp()+interval '15 minutes',%s,%s,clock_timestamp())""",
            (next_id, incident_id, 'MOCK_EMERGENCY' if inc['severity'] == 3 else 'MOCK_CHECK_IN',
             plan['action']['recipient']['ref'], 'Bước tiếp theo từ kết quả do nhân viên xác nhận; chưa thực thi.',
             Jsonb(plan), proposal['id']))
        conn.execute('UPDATE proposals SET operator_outcome=%s WHERE id=%s',
            (Jsonb({'code': body.outcome, 'reported_by': user['id'], 'request_id': str(body.request_id),
                    'next_proposal_id': str(next_id)}), proposal['id']))
        conn.execute('UPDATE incidents SET severity=%s,needs_plan=false,updated_at=clock_timestamp() WHERE id=%s',
                     (inc['severity'], incident_id))
        label = 'chưa liên hệ được' if body.outcome == 'no_response' else 'cần hỗ trợ'
        log(conn.cursor(), incident_id, 'operator_outcome',
            f"{user['username']} xác nhận: {label}. Tạo đề xuất {next_id}; vẫn cần phê duyệt mới.")
        ownership.assignment_changed(conn, inc)
    return {'proposal_id': str(next_id), 'duplicate': False}


@router.post('/api/incidents/{incident_id}/replan', status_code=202)
def replan(incident_id: UUID, body: Replan, user=Depends(current_user)):
    operator_only(user)
    with connect() as conn:
        inc = locked_incident(conn, incident_id, user)
        now = ownership.require_owner(conn, inc, user, body.assignment_version)
        proposal = conn.execute('SELECT * FROM proposals WHERE id=%s AND incident_id=%s FOR UPDATE', (body.proposal_id, incident_id)).fetchone()
        if not proposal:
            raise HTTPException(404, 'Không tìm thấy đề xuất của sự cố này')
        if proposal['replan_requested_at'] is not None:
            return {'status': 'requested', 'duplicate': True}
        latest = conn.execute('SELECT id FROM proposals WHERE incident_id=%s ORDER BY created_at DESC,id DESC LIMIT 1', (incident_id,)).fetchone()
        if latest['id'] != proposal['id']:
            raise HTTPException(409, 'Đã có đề xuất mới hơn; hãy làm mới danh sách')
        if proposal['status'] == 'PENDING' and proposal['expires_at'] <= now:
            conn.execute("UPDATE proposals SET status='EXPIRED' WHERE id=%s", (proposal['id'],))
            log(conn.cursor(), incident_id, 'expired', 'Đề xuất hết hạn; không thực thi.')
        elif proposal['status'] != 'EXPIRED':
            raise HTTPException(409, 'Chỉ yêu cầu tạo lại đề xuất đã hết hạn')
        conn.execute('UPDATE proposals SET replan_requested_at=now(),replan_requested_by=%s WHERE id=%s', (user['id'], proposal['id']))
        conn.execute('UPDATE incidents SET needs_plan=true,updated_at=now() WHERE id=%s', (incident_id,))
        log(conn.cursor(), incident_id, 'replan_requested', f"{user['username']} yêu cầu đề xuất mới thay {proposal['id']}; vẫn cần phê duyệt mới.")
        conn.execute('UPDATE trips SET version=version+1 WHERE id=%s', (inc['trip_id'],))
        changed(conn.cursor())
    return {'status': 'requested', 'duplicate': False}


@router.post('/api/incidents/{incident_id}/resolve')
def resolve(incident_id: UUID, body: Resolve, user=Depends(current_user)):
    operator_only(user)
    with connect() as conn:
        inc = locked_incident(conn, incident_id, user)
        ownership.require_owner(conn, inc, user, body.assignment_version)
        try:
            reason = confirmed_reason(inc['kind'], body.reason_code, body.reason)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        conn.execute("""UPDATE incidents SET status='RESOLVED',needs_plan=false,updated_at=now(),
            assigned_operator_id=NULL,assigned_at=NULL,assignment_expires_at=NULL,
            assignment_version=assignment_version+1,unassigned_since=NULL WHERE id=%s""", (incident_id,))
        conn.execute("UPDATE proposals SET status='CANCELLED' WHERE incident_id=%s AND status='PENDING'", (incident_id,))
        log(conn.cursor(), incident_id, 'resolved', user['username'] + ': ' + reason)
        conn.execute('UPDATE trips SET version=version+1 WHERE id=%s', (inc['trip_id'],))
        changed(conn.cursor())
    return {'status': 'RESOLVED'}


@router.post('/api/incidents/{incident_id}/ack')
def acknowledge(incident_id: UUID, user=Depends(current_user)):
    operator_only(user)
    with connect() as conn:
        inc = locked_incident(conn, incident_id, user)
        if inc['status'] == 'OPEN' and inc['severity'] < 3 and inc['automation_state'] in ('WAITING_RESPONSE', 'MONITORING'):
            escalate_to_human(conn, inc, f"{user['username']} yêu cầu can thiệp ngoại lệ; dừng quy trình tự động.")
        result = ownership.claim(conn, inc, user)
    return {'status': 'acknowledged', **result}


@router.post('/api/incidents/{incident_id}/lease')
def renew_lease(incident_id: UUID, body: OwnershipAction, user=Depends(current_user)):
    operator_only(user)
    with connect() as conn:
        inc = locked_incident(conn, incident_id, user)
        return ownership.renew(conn, inc, user, body.assignment_version)


@router.post('/api/incidents/{incident_id}/release')
def release_incident(incident_id: UUID, body: Resolve, user=Depends(current_user)):
    operator_only(user)
    with connect() as conn:
        inc = locked_incident(conn, incident_id, user)
        ownership.require_owner(conn, inc, user, body.assignment_version)
        try:
            reason = confirmed_reason(inc['kind'], body.reason_code, body.reason, release=True)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        result = ownership.release(conn, inc, user, body.assignment_version, reason)
    return {'status': 'released', **result}


@router.get('/api/area-alerts')
def area_alerts(user=Depends(current_user)):
    operator_only(user)
    with connect() as conn:
        return conn.execute("""
          WITH points AS (
            SELECT DISTINCT i.trip_id, i.kind,
              ST_Transform(ST_SetSRID(ST_MakePoint(t.last_lon,t.last_lat),4326),32648) AS geom
            FROM incidents i JOIN trips t ON t.id=i.trip_id
            WHERE i.status='OPEN' AND i.created_at>now()-interval '10 minutes'
              AND t.last_lon IS NOT NULL AND t.last_seen>now()-interval '5 minutes'
          ), clusters AS (
            SELECT *, ST_ClusterDBSCAN(geom,eps:=300,minpoints:=2)
              OVER (PARTITION BY kind ORDER BY trip_id) AS cluster_id FROM points
          ) SELECT kind,cluster_id,count(DISTINCT trip_id) AS trip_count,
              array_agg(DISTINCT trip_id) AS trip_ids
            FROM clusters WHERE cluster_id IS NOT NULL GROUP BY kind,cluster_id
        """).fetchall()

