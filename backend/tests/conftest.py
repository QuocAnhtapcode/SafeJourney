"""Integration tests require an explicitly isolated local database."""
import os
from urllib.parse import urlparse
import pytest


@pytest.fixture(scope='session', autouse=True)
def isolated_integration_guard():
    if os.getenv('RUN_DEMO_TESTS') != '1':
        return
    from app.config import DATABASE_URL, REDIS_URL
    database, redis = urlparse(DATABASE_URL), urlparse(REDIS_URL)
    if (database.hostname not in ('localhost', '127.0.0.1', '::1') or
        database.path.strip('/') not in ('safejourney_test', 'safejourney_loadtest') or
        database.query or database.fragment or
        redis.hostname not in ('localhost', '127.0.0.1', '::1') or redis.query or redis.fragment):
        pytest.fail('Integration tests require local safejourney_test/safejourney_loadtest and local Redis; see docs/06-kiem-thu-tai-1000-xe.md')
    # Repeatable test logins on the five known synthetic seed accounts only.
    # Keep the production rate limit unchanged; this runs after the DB guard.
    from app.db import connect
    with connect() as conn:
        conn.execute('DELETE FROM login_attempts WHERE username=ANY(%s)',
                     (['operator', 'operator2', 'driver', 'passenger', 'driver2', 'passenger2'],))
