"""Exercise the actual worker loop without contacting services."""
from types import SimpleNamespace
import psycopg
import pytest
import redis
from app import worker


@pytest.mark.parametrize('watchdog_fails', [False, True])
def test_redis_outage_does_not_skip_gps_watchdog(monkeypatch, watchdog_fails):
    calls = {'redis': 0, 'watchdog': 0}
    clock = [0]

    class EndProbe(BaseException):
        pass

    class Guard:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): return self
        def fetchone(self): return [True]

    class OfflineRedis:
        def xgroup_create(self, *args, **kwargs):
            calls['redis'] += 1
            raise redis.ConnectionError('Synthetic outage')
        def close(self): pass

    def check_gps():
        calls['watchdog'] += 1
        if watchdog_fails:
            raise psycopg.OperationalError('Synthetic temporary database error')

    def retry_sleep(_):
        clock[0] += 6
        if calls['redis'] == 2:
            raise EndProbe()

    monkeypatch.setattr(worker, 'psycopg', SimpleNamespace(connect=lambda *a, **k: Guard(), Error=psycopg.Error))
    monkeypatch.setattr(worker, 'redis', SimpleNamespace(Redis=SimpleNamespace(from_url=lambda *a, **k: OfflineRedis()), RedisError=redis.RedisError, ResponseError=redis.ResponseError))
    monkeypatch.setattr(worker, 'time', SimpleNamespace(monotonic=lambda: clock[0], sleep=retry_sleep))
    monkeypatch.setattr(worker.config, 'WATCHDOG_INTERVAL_SECONDS', 5)
    monkeypatch.setattr(worker, 'watchdog', check_gps)
    monkeypatch.setattr(worker, 'close_pool', lambda: None)
    with pytest.raises(EndProbe):
        worker.main()
    assert calls == {'redis': 2, 'watchdog': 2}


def test_reader_recovers_failed_delivery_before_reading_new_work(monkeypatch):
    calls = []
    own_pending = []
    class FakeRedis:
        def xgroup_create(self, *args, **kwargs): calls.append('group')
        def xreadgroup(self, group, consumer, streams, **kwargs):
            cursor = streams[worker.config.STREAM]
            calls.append(cursor)
            return [(worker.config.STREAM, list(own_pending))] if cursor == '0' else []
        def xautoclaim(self, *args, **kwargs):
            calls.append('claim')
            return ['0-0', [], []]
    monkeypatch.setattr(worker.time, 'monotonic', lambda: 100)
    reader = worker.StreamReader(FakeRedis())
    reader.ensure_group()
    reader.read()
    calls.clear()
    reader.ensure_group()
    reader.read()
    assert calls == ['>']  # No repeated group/pending/claim roundtrips when healthy.
    own_pending.append(('1-0', {'event_id': 'synthetic'}))
    reader.retry(psycopg.OperationalError('retry after failed processing'))
    assert reader.read() == own_pending
    reader.retry(redis.ConnectionError('restart'))
    assert not reader.group_ready
