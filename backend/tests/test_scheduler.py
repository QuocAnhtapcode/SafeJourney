from uuid import uuid4
import pytest
from app import planner


def test_failed_background_job_does_not_monopolize_its_lane(monkeypatch):
    broken, healthy = uuid4(), uuid4()
    calls = []
    monkeypatch.setattr(planner, 'maintain_incidents', lambda: None)

    def ready(*, urgent, excluded_ids, limit):
        if urgent:
            return []
        return [{'id': healthy if broken in excluded_ids else broken}]

    def run(url, job):
        calls.append(job['id'])
        if job['id'] == broken:
            raise ValueError('Synthetic broken checkpoint')

    monkeypatch.setattr(planner, 'ready_jobs', ready)
    monkeypatch.setattr(planner, 'run_checkpointed_job', run)
    scheduler = planner.PlannerScheduler('unused')
    try:
        scheduler.tick()
        with pytest.raises(ValueError):
            scheduler.inflight[False][0].result(timeout=3)
        scheduler.tick()
        scheduler.inflight[False][0].result(timeout=3)
        assert calls == [broken, healthy]
        assert broken in scheduler.retry_after
    finally:
        scheduler.close()
