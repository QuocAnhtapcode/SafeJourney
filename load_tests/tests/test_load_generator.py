import asyncio
from types import SimpleNamespace

import pytest

from load_tests.common import (distribution_ms, driver_id, phase_at, prefix,
                               scheduled_events, validate_base_url, validate_database_url, source_fingerprint)
from load_tests.run import Measurements, evaluate_gates, point, wait_until


@pytest.mark.parametrize('url', [
    'postgresql://u:p@127.0.0.1:5432/journey',
    'postgresql://u:p@db.example:25432/safejourney_loadtest',
    'postgresql://u:p@127.0.0.1:25432/journey',
    'postgresql://u:p@127.0.0.1:25432/safejourney_loadtest?host=production',
    '',
])
def test_database_guard_rejects_other_targets(url):
    with pytest.raises(ValueError):
        validate_database_url(url)


def test_guards_allow_only_namespaced_local_stack():
    assert validate_database_url('postgresql://u:p@127.0.0.1:25432/safejourney_loadtest')
    assert validate_base_url('http://localhost:18000/') == 'http://localhost:18000'
    for url in ['http://127.0.0.1:8000', 'https://example.com:18000', 'http://localhost:18000/api',
                'http://localhost:18000?target=other']:
        with pytest.raises(ValueError):
            validate_base_url(url)
    assert driver_id('baseline-a', 1) == 'sjlt-baseline-a-driver-00001'
    for run_id in ['bad_id', '../trip', 'x', 'percent%run']:
        with pytest.raises(ValueError):
            prefix(run_id)


def test_open_loop_schedule_has_full_1000_vehicle_steady_load():
    events = list(scheduled_events(1000, 3, 30, 66))
    assert [due for due, _, _ in events] == sorted(due for due, _, _ in events)
    steady = [(due, vehicle, seq) for due, vehicle, seq in events if phase_at(due, 30, 30) == 'steady']
    assert len(steady) == 2000  # 1000 vehicles / 3 seconds * 6 seconds.
    assert len({vehicle for _, vehicle, _ in steady}) == 1000
    for vehicle in [0, 500, 999]:
        times = [due for due, index, _ in events if index == vehicle]
        assert all(b-a == pytest.approx(3) for a, b in zip(times, times[1:]))


def test_zero_ramp_staggers_vehicle_arrivals():
    events = list(scheduled_events(1000, 3, 0, 3))
    assert len(events) == 1000
    assert sum(due == 0 for due, _, _ in events) == 1
    assert len(set(due for due, _, _ in events)) == 1000


def test_metric_exposes_drops_and_failures_separately():
    metric = Measurements(scheduled=10, sent=8, accepted=7, dropped_late=1, dropped_capacity=1,
                          latency=[.1, .2], successful_latency=[.1])
    result = metric.report()
    assert result['error_rate'] == .125
    assert result['dropped_rate'] == .2
    assert result['request_latency_ms']['p95'] == 195
    assert distribution_ms([])['p95'] is None


def test_processed_but_stale_does_not_pass_capacity_gate():
    metric = Measurements(scheduled=100, sent=100, accepted=100, latency=[.02]).report()
    report = {'http': {'steady': metric}, 'database': {
        'steady_received_window': {'received_to_processed_ms': {'p95': 100}},
        'after_drain': {'pending': 0, 'received': 100, 'processing_results': {'applied': 99, 'stale': 1}},
    }}
    args = SimpleNamespace(max_error_rate=.001, max_http_p95_ms=250, max_processing_p95_ms=2000)
    assert not evaluate_gates(report, args)['all_points_applied']
    report['database']['after_drain']['processing_results'] = None
    assert not evaluate_gates(report, args)['processing_outcomes_available']


def test_synthetic_route_stays_on_seed_route_and_ids_are_unique():
    points = [point(i) for i in range(401)]
    assert len({p['event_id'] for p in points}) == 401
    assert all(10.77 <= p['lat'] <= 10.79 and p['lon'] == 106.7 for p in points)
    assert all(p['speed_kmh'] == 30 for p in points)


def test_early_timer_wake_does_not_send_before_planned_arrival():
    readings = iter([0, .004, .008, .010])
    waits = []

    async def early_sleep(seconds):
        waits.append(seconds)

    asyncio.run(wait_until(.010, clock=lambda: next(readings), sleep=early_sleep))
    assert waits == pytest.approx([.010, .006, .002])


def test_source_fingerprint_tracks_code_but_excludes_secrets_and_reports(tmp_path):
    app = tmp_path/'backend/app'
    app.mkdir(parents=True)
    (app/'main.py').write_text('version = 1', encoding='utf-8')
    before = source_fingerprint(tmp_path)
    (tmp_path/'backend/.env').write_text('SECRET=synthetic', encoding='utf-8')
    assert source_fingerprint(tmp_path) == before
    (app/'main.py').write_text('version = 2', encoding='utf-8')
    assert source_fingerprint(tmp_path) != before
