import asyncio
from fastapi import APIRouter, WebSocket
from .config import ORIGINS
from .db import connect
from .security import COOKIE, session_user

router = APIRouter()

def get_refresh_state(token):
    with connect() as conn:
        user = session_user(token, conn)
        if not user:
            return None
        if user['role'] == 'operator':
            return conn.execute('SELECT s.version+(SELECT COALESCE(sum(version),0) FROM trips) AS version FROM system_state s WHERE s.id=1').fetchone()['version']
        return conn.execute('SELECT COALESCE(sum(version),0) AS version FROM trips WHERE driver_id=%s OR passenger_id=%s',
                            (user['id'], user['id'])).fetchone()['version']


@router.websocket('/ws')
async def websocket(ws: WebSocket):
    token = ws.cookies.get(COOKIE)
    if ws.headers.get('origin') not in ORIGINS or await asyncio.to_thread(get_refresh_state, token) is None:
        await ws.close(code=1008)
        return
    await ws.accept()
    last = -1
    try:
        while True:
            version = await asyncio.to_thread(get_refresh_state, token)
            if version is None:
                await ws.close(code=1008)
                return
            await ws.send_json({'type': 'refresh' if version != last else 'heartbeat'})
            last = version
            await asyncio.sleep(1)
    except Exception:
        # Disconnect/database outage: frontend reconnects and falls back to REST.
        try:
            await ws.close(code=1011)
        except Exception:
            pass

