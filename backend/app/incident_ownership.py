"""Incident leases checked inside the same transaction as each operator write."""
from datetime import timedelta
from fastapi import HTTPException
from . import config
from .db import log, changed


def database_now(conn):
    # Read after row locks: transaction-start now() may predate a long lock wait.
    return conn.execute('SELECT clock_timestamp() AS value').fetchone()['value']


def active_assignment(incident, now):
    return (incident.get('assigned_operator_id') is not None
            and incident.get('assignment_expires_at') is not None
            and incident['assignment_expires_at'] > now)


def escalation_key(seconds, version):
    return f'ESCALATION_{seconds}' + (f'_V{version}' if version else '')


def require_owner(conn, incident, user, version):
    now = database_now(conn)
    if incident['status'] != 'OPEN':
        raise HTTPException(409, 'Sự cố đã đóng')
    if not active_assignment(incident, now):
        raise HTTPException(409, 'Chưa có quyền xử lý hoặc quyền đã hết hạn. Hãy nhận xử lý lại.')
    if incident['assigned_operator_id'] != user['id']:
        raise HTTPException(409, 'Sự cố đang do nhân viên khác phụ trách. Hãy làm mới danh sách.')
    if version != incident['assignment_version']:
        raise HTTPException(409, 'Phiên xử lý đã thay đổi. Hãy làm mới hồ sơ trước khi thao tác.')
    return now


def assignment_view(incident, now):
    return {key: incident[key] for key in (
        'assigned_operator_id', 'assigned_at', 'assignment_expires_at', 'assignment_version')} | {
            'server_time': now, 'assignment_lease_seconds': config.INCIDENT_LEASE_SECONDS}


def assignment_changed(conn, incident):
    conn.execute('UPDATE trips SET version=version+1 WHERE id=%s', (incident['trip_id'],))
    changed(conn.cursor())


def claim(conn, incident, user):
    now = database_now(conn)
    if incident['status'] != 'OPEN':
        raise HTTPException(409, 'Sự cố đã đóng')
    if active_assignment(incident, now):
        if incident['assigned_operator_id'] != user['id']:
            raise HTTPException(409, 'Nhân viên khác đã nhận xử lý sự cố này.')
        return assignment_view(incident, now)  # Retry does not create another claim/version.
    if incident['assigned_operator_id']:
        log(conn.cursor(), incident['id'], 'assignment_expired',
            f"Phiên {incident['assignment_version']} của {incident['assigned_operator_id']} đã hết hạn trước khi nhận lại.")
    row = conn.execute("""UPDATE incidents SET assigned_operator_id=%s,assigned_at=%s,
        assignment_expires_at=%s,assignment_version=assignment_version+1,unassigned_since=NULL,
        acknowledged_at=COALESCE(acknowledged_at,%s),acknowledged_by=COALESCE(acknowledged_by,%s),updated_at=%s
        WHERE id=%s RETURNING *""", (user['id'], now, now+timedelta(seconds=config.INCIDENT_LEASE_SECONDS),
                                    now, user['id'], now, incident['id'])).fetchone()
    log(conn.cursor(), incident['id'], 'assignment_claimed',
        f"{user['username']} nhận xử lý, phiên {row['assignment_version']}.")
    assignment_changed(conn, incident)
    return assignment_view(row, now)


def renew(conn, incident, user, version):
    now = require_owner(conn, incident, user, version)
    row = conn.execute('UPDATE incidents SET assignment_expires_at=%s WHERE id=%s RETURNING *',
        (now+timedelta(seconds=config.INCIDENT_LEASE_SECONDS), incident['id'])).fetchone()
    # No audit spam or global revision write on every heartbeat. Readers refresh periodically.
    return assignment_view(row, now)


def release(conn, incident, user, version, reason):
    now = require_owner(conn, incident, user, version)
    row = conn.execute("""UPDATE incidents SET assigned_operator_id=NULL,assigned_at=NULL,
        assignment_expires_at=NULL,assignment_version=assignment_version+1,unassigned_since=%s,
        updated_at=%s WHERE id=%s RETURNING *""", (now, now, incident['id'])).fetchone()
    log(conn.cursor(), incident['id'], 'assignment_released',
        f"{user['username']} trả hồ sơ từ phiên {version}: {reason.strip()}")
    assignment_changed(conn, incident)
    return assignment_view(row, now)
