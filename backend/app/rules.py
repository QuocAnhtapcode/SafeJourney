"""Pure rules: no database, no LLM; seconds use observation timestamps."""
from . import config

def evaluate(previous, point, outside_route, timestamp):
    state = dict(previous)
    flags = []
    # Missing/low-quality samples do not count as stationary or safe.
    good = 0 < point['accuracy_m'] <= 30
    conditions = {
        'STOP': good and point['speed_kmh'] < 3,
        'DEVIATION': good and outside_route,
        'SPEED': good and point['speed_kmh'] > config.SPEED_LIMIT_KMH + 10,
    }
    thresholds = {'STOP': config.STOP_SECONDS, 'DEVIATION': config.DEVIATION_SECONDS,
                  'SPEED': config.SPEED_SECONDS}
    # A long missing gap must not extend a continuous detection window.
    if timestamp - state.get('last_t', timestamp) > 15:
        state = {}
    for kind, active in conditions.items():
        key = kind + '_since'
        if active:
            state.setdefault(key, timestamp)
            if timestamp - state[key] >= thresholds[kind]:
                flags.append(kind)
        else:
            state.pop(key, None)
    state['last_t'] = timestamp
    state['good_gps'] = good
    state['current_conditions'] = conditions
    return state, flags
