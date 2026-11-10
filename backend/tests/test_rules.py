from app.rules import evaluate
from app import config

def point(speed=25, accuracy=10):
    return {'speed_kmh': speed, 'accuracy_m': accuracy}

def test_deviation_requires_duration():
    state = {}
    for t in range(config.DEVIATION_SECONDS + 1):
        state, flags = evaluate(state, point(), True, t)
        assert ('DEVIATION' in flags) == (t >= config.DEVIATION_SECONDS)

def test_bad_gps_resets_window():
    state, _ = evaluate({}, point(), True, 0)
    state, _ = evaluate(state, point(accuracy=200), True, 5)
    assert 'DEVIATION_since' not in state

def test_gap_does_not_count_as_stopped():
    state, _ = evaluate({}, point(speed=0), False, 0)
    _, flags = evaluate(state, point(speed=0), False, config.STOP_SECONDS + 20)
    assert 'STOP' not in flags

def test_normal_data_has_no_alert():
    state = {}
    for t in range(200):
        state, flags = evaluate(state, point(), False, t)
        assert not flags
