"""Create fresh, namespaced synthetic users/trips in a dedicated local DB."""
import argparse
import os
import sys
from pathlib import Path

import psycopg

from .common import driver_id, prefix, trip_id, validate_database_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--vehicles', type=int, default=1000)
    parser.add_argument('--allow-local-loadtest', action='store_true', required=True)
    args = parser.parse_args()
    if not 1 <= args.vehicles <= 10000:
        parser.error('vehicles must be 1–10000')
    namespace = prefix(args.run_id)
    url = validate_database_url(os.environ.get('LOADTEST_DATABASE_URL', ''))
    password = os.environ.get('LOADTEST_PASSWORD', '')
    if not 12 <= len(password) <= 128:
        parser.error('Set LOADTEST_PASSWORD to 12–128 characters; never pass it as a CLI argument')
    # Explicit test URL wins over any backend .env. Reuse the real password hasher.
    os.environ['DATABASE_URL'] = url
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
    from app.security import hash_password
    # This is test fixture setup, outside measured time. Every login still checks scrypt.
    encoded = hash_password(password)
    with psycopg.connect(url) as conn:
        conn.execute("SET statement_timeout='30s'")
        if conn.execute('SELECT current_database()').fetchone()[0] != 'safejourney_loadtest':
            raise ValueError('Wrong database')
        if conn.execute('SELECT 1 FROM users WHERE id LIKE %s LIMIT 1', (namespace+'%',)).fetchone():
            parser.error('run-id already exists. Choose a new run-id; fixtures are never overwritten/deleted')
        passenger = namespace + 'passenger'
        operator = namespace + 'operator'
        with conn.cursor() as cur:
            cur.executemany('INSERT INTO users(id,username,password_hash,role) VALUES (%s,%s,%s,%s)',
                            [(passenger, passenger, encoded, 'passenger'), (operator, operator, encoded, 'operator')]
                            + [(driver_id(args.run_id, i), driver_id(args.run_id, i), encoded, 'driver')
                               for i in range(args.vehicles)])
            cur.executemany("INSERT INTO trips(id,label,driver_id,passenger_id,status,route_geom) VALUES (%s,%s,%s,%s,'PLANNED',ST_GeomFromText('LINESTRING(106.7000 10.7700,106.7000 10.7900)',4326))",
                            [(trip_id(args.run_id, i), f'SYNTHETIC LOAD TEST {i}', driver_id(args.run_id, i), passenger)
                             for i in range(args.vehicles)])
    print(f'Created {args.vehicles} synthetic trips; run-id={args.run_id}. No credentials written.')


if __name__ == '__main__':
    main()
