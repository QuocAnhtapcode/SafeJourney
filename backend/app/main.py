"""Application composition. API, detector and planner stay separately runnable."""
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import PoolTimeout, TooManyRequests
from .db import get_pool, close_pool
from .security import same_origin
from .api import auth, trips, incidents, monitoring, contacts, operations
from . import realtime


@asynccontextmanager
async def lifespan(app):
    await asyncio.to_thread(get_pool().wait, timeout=15)
    try:
        yield
    finally:
        close_pool()


app = FastAPI(title='SafeJourney — MVP', lifespan=lifespan)


@app.middleware('http')
async def origin_guard(request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        try:
            same_origin(request)
        except HTTPException as exc:
            return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
    return await call_next(request)


@app.exception_handler(PoolTimeout)
@app.exception_handler(TooManyRequests)
async def database_busy(request, exc):
    return JSONResponse({'detail': 'Hệ thống đang bận; hãy thử lại với cùng event_id.'},
                        status_code=503, headers={'Retry-After': '1'})


for module in (auth, trips, incidents, monitoring, contacts, operations, realtime):
    app.include_router(module.router)

static_dir = os.getenv('STATIC_DIR')
if static_dir and Path(static_dir).is_dir():
    app.mount('/', StaticFiles(directory=static_dir, html=True), name='frontend')
