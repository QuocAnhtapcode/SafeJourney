"""Pure time policy, shared by ingestion, detector and regression tests."""
from datetime import datetime


def sample_result(observed: datetime, received: datetime, last_seen: datetime | None,
                  active: bool, freshness_seconds: int = 30) -> str:
    # Queue delay must not turn a sample valid at ingestion into stale data.
    if not active:
        return 'INACTIVE'
    if not -freshness_seconds <= (received - observed).total_seconds() <= freshness_seconds:
        return 'STALE'
    if last_seen is not None and observed <= last_seen:
        return 'OUT_OF_ORDER'
    return 'APPLIED'
