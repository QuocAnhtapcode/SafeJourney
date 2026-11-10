from fastapi import APIRouter, Depends
from ..db import connect, get_pool
from ..security import current_user, operator_only

router = APIRouter()

@router.get('/api/health')
def health():
    with connect() as conn:
        conn.execute('SELECT 1')
    return {'status': 'ok', 'mode': 'simulation'}


@router.get('/api/ops/metrics')
def metrics(user=Depends(current_user)):
    operator_only(user)
    with connect() as conn:
        queue = conn.execute("SELECT count(*) AS pending,COALESCE(EXTRACT(EPOCH FROM clock_timestamp()-min(received_at)),0) AS oldest_pending_seconds FROM telemetry_inbox WHERE processed_at IS NULL").fetchone()
        planning = conn.execute("SELECT count(*) AS pending FROM graph_jobs WHERE status='NEW'").fetchone()
    return {'telemetry_queue': queue, 'planner_queue': planning,
            'api_process_pool': get_pool().get_stats(), 'mode': 'simulation'}

