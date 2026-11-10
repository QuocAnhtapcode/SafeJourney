"""Inspect one synthetic run; optionally finish its ACTIVE trips after a crash."""
import argparse
from collections import Counter
import os
import socket
import psycopg
from .common import prefix, validate_database_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--finish', action='store_true')
    parser.add_argument('--allow-local-loadtest', action='store_true', required=True)
    args = parser.parse_args()
    try:
        namespace = prefix(args.run_id)
        url = validate_database_url(os.environ.get('LOADTEST_DATABASE_URL', ''))
    except ValueError:
        parser.error('Require a valid run-id and the isolated local load-test database')
    if args.finish:
        with socket.socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex(('127.0.0.1', 18000)) == 0:
                parser.error('Stop the test API, detector and planner before finishing a run')
    with psycopg.connect(url, connect_timeout=5) as conn:
        if args.finish:
            for lock in (730012, 730013):
                if not conn.execute('SELECT pg_try_advisory_xact_lock(%s)', (lock,)).fetchone()[0]:
                    parser.error('A test detector/planner still owns its lock; stop it first')
        rows = conn.execute('SELECT status FROM trips WHERE id LIKE %s', (namespace+'trip-%',)).fetchall()
        if not rows:
            parser.error('No trips found for this run-id; nothing changed')
        print(f'Run {args.run_id}: {dict(Counter(row[0] for row in rows))}')
        if args.finish:
            result = conn.execute("UPDATE trips SET status='FINISHED' WHERE id LIKE %s AND status='ACTIVE'", (namespace+'trip-%',))
            print(f'Finished {result.rowcount} ACTIVE synthetic trips. Evidence retained.')
        else:
            print('Read-only inspection; no changes.')


if __name__ == '__main__':
    main()
