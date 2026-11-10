from datetime import datetime, timedelta, timezone
import pytest
from app.telemetry_policy import sample_result


@pytest.mark.parametrize('age,last_seen,active,expected', [
    (2, None, True, 'APPLIED'),
    (31, None, True, 'STALE'),
    (-31, None, True, 'STALE'),
    (2, 1, True, 'OUT_OF_ORDER'),
    (2, 2, True, 'OUT_OF_ORDER'),
    (2, None, False, 'INACTIVE'),
])
def test_sample_time_policy(age, last_seen, active, expected):
    received = datetime(2026, 1, 1, tzinfo=timezone.utc)
    observed = received - timedelta(seconds=age)
    previous = received - timedelta(seconds=last_seen) if last_seen is not None else None
    assert sample_result(observed, received, previous, active) == expected


def test_queue_delay_does_not_discard_valid_sample():
    # Deliberately historical receive time; processing happens much later.
    received = datetime(2020, 1, 1, tzinfo=timezone.utc)
    assert sample_result(received-timedelta(seconds=1), received, None, True) == 'APPLIED'
