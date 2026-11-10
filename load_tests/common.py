"""Guardrails and deterministic schedule primitives; no network at import time."""
import heapq
import math
import re
import hashlib
from pathlib import Path
from urllib.parse import urlparse

RUN_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,30}\Z")


def validate_run_id(run_id):
    if not RUN_RE.fullmatch(run_id):
        raise ValueError('run-id: 3–31 lowercase letters, digits or hyphens')
    return run_id


def prefix(run_id):
    return 'sjlt-' + validate_run_id(run_id) + '-'


def trip_id(run_id, index):
    return f'{prefix(run_id)}trip-{index:05d}'


def driver_id(run_id, index):
    return f'{prefix(run_id)}driver-{index:05d}'


def validate_database_url(url):
    """Only the dedicated local Compose database, never the demo/default DB."""
    parsed = urlparse(url)
    if (parsed.scheme not in ('postgres', 'postgresql')
            or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.port != 25432 or parsed.path != '/safejourney_loadtest'
            or parsed.query or parsed.fragment):
        raise ValueError('Use only local port 25432, database safejourney_loadtest, without URL options')
    return url


def validate_base_url(url):
    parsed = urlparse(url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.port != 18000 or parsed.path not in ('', '/')
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('Load generation is restricted to http://127.0.0.1:18000 (or localhost/::1)')
    return url.rstrip('/')


def scheduled_events(vehicles, interval, ramp, end):
    """Open-loop: next arrival depends only on time, never response completion.

    Ramp staggers vehicle activation; an interval-sized phase offset avoids an
    artificial 1000-request burst when ramp=0 or ramp is an interval multiple.
    All vehicles have started by ramp+interval. Warmup must be >= interval.
    """
    queue = [(ramp * i / vehicles + interval * i / vehicles, i, 0) for i in range(vehicles)]
    heapq.heapify(queue)
    while queue:
        due, vehicle, seq = heapq.heappop(queue)
        if due >= end:
            return
        yield due, vehicle, seq
        heapq.heappush(queue, (due + interval, vehicle, seq + 1))


def phase_at(due, ramp, warmup):
    if due < ramp:
        return 'ramp'
    if due < ramp + warmup:
        return 'warmup'
    return 'steady'


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    at = (len(ordered) - 1) * fraction
    lo, hi = math.floor(at), math.ceil(at)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (at - lo)


def distribution_ms(values):
    ordered = sorted(values)  # Sort once, not once per percentile.
    result = {}
    for name, fraction in [('p50', .50), ('p95', .95), ('p99', .99), ('max', 1)]:
        if not ordered:
            result[name] = None
            continue
        at = (len(ordered)-1)*fraction
        lo, hi = math.floor(at), math.ceil(at)
        result[name] = round((ordered[lo] + (ordered[hi]-ordered[lo])*(at-lo))*1000, 3)
    return result


def source_fingerprint(root=None):
    """Identify measured source without reading secrets, datasets or reports."""
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    paths = set()
    for pattern in ('backend/app/**/*.py', 'backend/migrations/*.sql', 'backend/schema.sql',
                    'backend/requirements.txt', 'load_tests/*.py', 'load_tests/requirements.txt',
                    'frontend/src/*', 'frontend/package*.json', 'load_tests/compose.yaml'):
        paths.update(p for p in root.glob(pattern) if p.is_file())
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode()+b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return {'sha256': digest.hexdigest(), 'file_count': len(paths)}
