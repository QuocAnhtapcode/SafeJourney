from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from .. import config
from ..db import connect, create_incident
from ..schemas import Telemetry, SOS, TripView
from ..security import current_user, check_trip

router = APIRouter()

@router.get('/api/trips', response_model=list[TripView])
def trips(include_route: bool = True, active_only: bool = False, user=Depends(current_user)):
    with connect() as conn:
        return conn.execute("SELECT id,label,driver_id,status,last_lat,last_lon,last_seen,version,CASE WHEN %s THEN ST_AsGeoJSON(route_geom)::json ELSE NULL END AS route FROM trips WHERE (NOT %s OR status='ACTIVE') AND (%s='operator' OR driver_id=%s OR passenger_id=%s) ORDER BY id", (include_route, active_only, user['role'], user['id'], user['id'])).fetchall()


@router.get('/api/trips/{trip_id}', response_model=TripView)
def trip_detail(trip_id: str, user=Depends(current_user)):
    with connect() as conn:
        row = conn.execute('SELECT id,label,driver_id,passenger_id,status,last_lat,last_lon,last_seen,version,ST_AsGeoJSON(route_geom)::json AS route FROM trips WHERE id=%s', (trip_id,)).fetchone()
        check_trip(row, user)
        row.pop('passenger_id')
        return row


@router.post('/api/trips/{trip_id}/telemetry')
def telemetry(trip_id: str, body: Telemetry, user=Depends(current_user)):
    if (body.event_time - datetime.now(timezone.utc)).total_seconds() > config.TELEMETRY_FRESH_SECONDS:
        raise HTTPException(422, f'Đồng hồ thiết bị đi trước máy chủ quá {config.TELEMETRY_FRESH_SECONDS} giây')
    with connect() as conn:
        trip = conn.execute('SELECT id,driver_id,passenger_id,status FROM trips WHERE id=%s FOR UPDATE', (trip_id,)).fetchone()
        check_trip(trip, user, write=True)
        payload = body.model_dump(mode='json')
        inserted = conn.execute('INSERT INTO telemetry_inbox(event_id,trip_id,actor_id,payload) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING event_id', (body.event_id, trip_id, user['id'], Jsonb(payload))).fetchone()
        if not inserted:
            old = conn.execute('SELECT trip_id,actor_id,payload FROM telemetry_inbox WHERE event_id=%s', (body.event_id,)).fetchone()
            if old['trip_id'] != trip_id or old['actor_id'] != user['id'] or old['payload'] != payload:
                raise HTTPException(409, 'event_id đã dùng cho dữ liệu khác')
            return {'status': 'durable', 'duplicate': True}
        # A retry of an already committed event remains acknowledged after the
        # trip ends. A new event for an inactive trip rolls this insert back.
        if trip['status'] != 'ACTIVE':
            raise HTTPException(409, 'Chuyến không hoạt động')
        conn.execute('INSERT INTO telemetry_outbox(event_id) VALUES (%s)', (body.event_id,))
        # Late/offline samples remain auditable but cannot hide GPS_LOST.
        conn.execute("UPDATE trips SET last_received_at=clock_timestamp() WHERE id=%s AND %s>=clock_timestamp()-(%s*interval '1 second')", (trip_id, body.event_time, config.TELEMETRY_FRESH_SECONDS))
    return {'status': 'durable', 'event_id': str(body.event_id)}


@router.post('/api/trips/{trip_id}/sos')
def sos(trip_id: str, body: SOS, user=Depends(current_user)):
    with connect() as conn:
        # Serialize only attempts sharing the SOS UUID, including cross-trip reuse.
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (str(body.event_id),))
        trip = conn.execute('SELECT id,driver_id,passenger_id,status FROM trips WHERE id=%s FOR UPDATE', (trip_id,)).fetchone()
        check_trip(trip, user)
        if user['role'] == 'operator':
            raise HTTPException(403, 'Dùng tài khoản khách hoặc tài xế cho SOS')
        old = conn.execute('SELECT * FROM sos_events WHERE event_id=%s', (body.event_id,)).fetchone()
        if old:
            if old['trip_id'] != trip_id or old['actor_id'] != user['id']:
                raise HTTPException(409, 'event_id đã được sử dụng')
            return {'status': 'received', 'incident_id': old['incident_id']}
        cur = conn.cursor()
        inc = create_incident(cur, trip_id, 'SOS', 3, 'SOS đã nhận; nguyên nhân chưa xác minh.', {'source_role': user['role'], 'event_id': str(body.event_id)})
        conn.execute('INSERT INTO sos_events(event_id,trip_id,actor_id,incident_id) VALUES (%s,%s,%s,%s)', (body.event_id, trip_id, user['id'], inc))
    return {'status': 'received', 'incident_id': inc}

