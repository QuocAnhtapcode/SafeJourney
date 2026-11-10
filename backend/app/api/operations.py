"""Operator-only, idempotent advisory assessments outside the telemetry path."""
import hashlib
import json
import logging
from threading import BoundedSemaphore
from typing import Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from psycopg.types.json import Jsonb
from ..db import connect
from ..security import current_user, operator_only, check_trip
from ..operations.scenarios import catalog, build_snapshot
from ..operations.workflow import assess

router = APIRouter()
logger = logging.getLogger(__name__)
_slots = BoundedSemaphore(2)


class AssessmentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    trip_id: str = Field(min_length=1, max_length=200)
    scenario_id: Literal['normal', 'rush_hour', 'rain', 'low_battery', 'fare_dispute'] = 'normal'


def public_run(row):
    return {key: row[key] for key in ('id', 'trip_id', 'scenario_id', 'created_at', 'status', 'report')}


@router.get('/api/operations/scenarios')
def scenarios(user=Depends(current_user)):
    operator_only(user)
    return catalog()


@router.get('/api/operations/plans')
def plans(trip_id: str | None = Query(None, max_length=200), limit: int = Query(10, ge=1, le=50), user=Depends(current_user)):
    operator_only(user)
    with connect() as conn:
        if trip_id is not None:
            check_trip(conn.execute('SELECT * FROM trips WHERE id=%s', (trip_id,)).fetchone(), user)
        return conn.execute('''SELECT id,trip_id,scenario_id,created_at,status FROM operations_runs
            WHERE (%s::text IS NULL OR trip_id=%s) ORDER BY created_at DESC,id DESC LIMIT %s''',
                            (trip_id, trip_id, limit)).fetchall()


@router.get('/api/operations/plans/{run_id}')
def plan_detail(run_id: UUID, user=Depends(current_user)):
    operator_only(user)
    with connect() as conn:
        row = conn.execute('SELECT * FROM operations_runs WHERE id=%s', (run_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Không tìm thấy phương án trong phạm vi được phép')
        check_trip(conn.execute('SELECT * FROM trips WHERE id=%s', (row['trip_id'],)).fetchone(), user)
        return public_run(row)


def reserve(body, user):
    """Short transaction reserves a run; no model or routing I/O under DB locks."""
    fingerprint = hashlib.sha256(json.dumps({'trip_id': body.trip_id, 'scenario_id': body.scenario_id},
                                           sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    token = uuid4()
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ('operations:'+user['id'],))
        trip = conn.execute('''SELECT id,driver_id,passenger_id,status,version,last_seen,
            ST_Y(ST_StartPoint(route_geom)) AS start_lat, ST_X(ST_StartPoint(route_geom)) AS start_lon,
            ST_Y(ST_EndPoint(route_geom)) AS end_lat, ST_X(ST_EndPoint(route_geom)) AS end_lon,
            ST_Length(route_geom::geography) AS planned_distance_m,
            EXISTS (SELECT 1 FROM incidents i WHERE i.trip_id=trips.id AND i.status='OPEN' AND i.severity=3) AS has_open_emergency
            FROM trips WHERE id=%s''', (body.trip_id,)).fetchone()
        check_trip(trip, user)
        row = conn.execute('SELECT * FROM operations_runs WHERE id=%s FOR UPDATE', (body.request_id,)).fetchone()
        now = conn.execute('SELECT clock_timestamp() AS t').fetchone()['t']
        if row:
            if row['actor_id'] != user['id'] or row['input_hash'] != fingerprint:
                raise HTTPException(409, 'Mã yêu cầu đã dùng cho dữ liệu hoặc người tạo khác')
            if row['status'] not in ('RUNNING', 'FAILED'):
                return row, None
            if row['status'] == 'RUNNING' and row['lease_until'] > now:
                raise HTTPException(409, 'Agent đang xử lý yêu cầu này; chờ rồi thử lại với cùng mã yêu cầu')
        if conn.execute("SELECT 1 FROM operations_runs WHERE actor_id=%s AND status='RUNNING' AND lease_until>%s AND id<>%s",
                        (user['id'], now, body.request_id)).fetchone():
            raise HTTPException(429, 'Tài khoản đang có một lượt phân tích; chờ hoàn tất rồi thử lại', headers={'Retry-After': '3'})
        # Bound new requests; retries reuse the snapshot and the actor lease.
        recent = conn.execute("SELECT count(*) AS n FROM operations_runs WHERE actor_id=%s AND created_at>%s-interval '1 minute'",
                              (user['id'], now)).fetchone()['n']
        if not row and recent >= 10:
            raise HTTPException(429, 'Tối đa 10 lượt mới mỗi phút; có thể xem lại lịch sử', headers={'Retry-After': '60'})
        if row:
            row = conn.execute("""UPDATE operations_runs SET status='RUNNING',execution_token=%s,
                lease_until=clock_timestamp()+interval '90 seconds',completed_at=NULL WHERE id=%s RETURNING *""",
                (token, body.request_id)).fetchone()
        else:
            snapshot = build_snapshot(trip, body.scenario_id, now)
            row = conn.execute("""INSERT INTO operations_runs(id,trip_id,actor_id,scenario_id,input_hash,snapshot,
                execution_token,lease_until) VALUES (%s,%s,%s,%s,%s,%s,%s,clock_timestamp()+interval '90 seconds')
                ON CONFLICT (id) DO NOTHING RETURNING *""",
                (body.request_id, body.trip_id, user['id'], body.scenario_id, fingerprint, Jsonb(snapshot), token)).fetchone()
            if row is None:
                raise HTTPException(409, 'Mã yêu cầu vừa được dùng; hãy làm mới')
        return row, token


@router.post('/api/operations/plans')
def create_plan(body: AssessmentRequest, user=Depends(current_user)):
    operator_only(user)
    if not _slots.acquire(blocking=False):
        raise HTTPException(429, 'Các agent vận hành đang bận; hãy thử lại cùng mã yêu cầu', headers={'Retry-After': '3'})
    try:
        row, token = reserve(body, user)
        if token is None:
            return {**public_run(row), 'duplicate': True}
        try:
            result = assess(row['snapshot'])
        except Exception as exc:
            logger.warning('Operations assessment failed: %s', type(exc).__name__)
            with connect() as conn:
                conn.execute("UPDATE operations_runs SET status='FAILED',lease_until=clock_timestamp() WHERE id=%s AND execution_token=%s",
                             (body.request_id, token))
            raise HTTPException(503, 'Chưa hoàn tất kiểm tra; không có hành động được thực thi. Thử lại cùng mã yêu cầu.') from None
        with connect() as conn:
            saved = conn.execute('''UPDATE operations_runs SET status=%s,report=%s,completed_at=clock_timestamp()
                WHERE id=%s AND execution_token=%s AND status='RUNNING' RETURNING *''',
                (result['status'], Jsonb(result['report']), body.request_id, token)).fetchone()
            if saved is None:
                raise HTTPException(409, 'Lượt xử lý đã được thay thế; xem lại phương án mới nhất')
        return {**public_run(saved), 'duplicate': False}
    finally:
        _slots.release()
