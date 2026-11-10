import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://journey:journey_local_change_me@127.0.0.1:5432/journey')
REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
ORIGINS = [x.strip() for x in os.getenv('ALLOWED_ORIGINS', 'http://localhost:5173').split(',') if x.strip()]
COOKIE_SECURE = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
STREAM = 'journey:telemetry'
GROUP = 'journey:detector'
STOP_SECONDS = int(os.getenv('STOP_SECONDS', '180'))
DEVIATION_SECONDS = int(os.getenv('DEVIATION_SECONDS', '45'))
SPEED_SECONDS = int(os.getenv('SPEED_SECONDS', '10'))
GPS_LOST_SECONDS = int(os.getenv('GPS_LOST_SECONDS', '60'))
SPEED_LIMIT_KMH = float(os.getenv('SPEED_LIMIT_KMH', '80'))

# Each process has its own bounded connection pool.
DB_POOL_MIN = int(os.getenv('DB_POOL_MIN', '2'))
DB_POOL_MAX = int(os.getenv('DB_POOL_MAX', '16'))
DB_POOL_TIMEOUT = float(os.getenv('DB_POOL_TIMEOUT', '5'))
DB_POOL_MAX_WAITING = int(os.getenv('DB_POOL_MAX_WAITING', '64'))
TELEMETRY_BATCH_SIZE = int(os.getenv('TELEMETRY_BATCH_SIZE', '200'))
TELEMETRY_FRESH_SECONDS = int(os.getenv('TELEMETRY_FRESH_SECONDS', '30'))
WATCHDOG_INTERVAL_SECONDS = float(os.getenv('WATCHDOG_INTERVAL_SECONDS', '5'))
INCIDENT_LEASE_SECONDS = int(os.getenv('INCIDENT_LEASE_SECONDS', '300'))
if not 1 <= DB_POOL_MIN <= DB_POOL_MAX <= 100:
    raise ValueError('Require 1 <= DB_POOL_MIN <= DB_POOL_MAX <= 100')
if not 1 <= TELEMETRY_BATCH_SIZE <= 1000:
    raise ValueError('TELEMETRY_BATCH_SIZE must be between 1 and 1000')
if DB_POOL_TIMEOUT <= 0 or DB_POOL_MAX_WAITING < 1 or TELEMETRY_FRESH_SECONDS <= 0 or WATCHDOG_INTERVAL_SECONDS <= 0:
    raise ValueError('Pool, freshness and watchdog settings must be positive')
if not 30 <= INCIDENT_LEASE_SECONDS <= 3600:
    raise ValueError('INCIDENT_LEASE_SECONDS must be between 30 and 3600')
