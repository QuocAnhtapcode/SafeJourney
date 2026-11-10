"""Small deterministic seasonal baseline, independent of database and model APIs.

Rows are (hour-start datetime, spatial-id string, nonnegative count). Missing
hours must be zero-filled by the caller: missing observations are not zeros.
The returned model contains aggregates only, never trip records.
"""
from collections import defaultdict
from datetime import datetime
from math import isfinite, sqrt


def _hour(value):
    if not isinstance(value, datetime) or value.minute or value.second or value.microsecond:
        raise ValueError('Timestamps must be datetime values aligned to an hour')
    return value


def fit_seasonal_mean(rows, cutoff):
    """Freeze a zone × weekday × hour model using only rows before cutoff."""
    _hour(cutoff)
    totals, samples = defaultdict(int), defaultdict(int)
    zone_totals, zone_samples = defaultdict(int), defaultdict(int)
    observed = set()
    for timestamp, zone, count in rows:
        _hour(timestamp)
        if timestamp >= cutoff:
            continue
        if not isinstance(zone, str) or not zone or '|' in zone:
            raise ValueError('Spatial IDs must be nonempty strings without |')
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError('Demand counts must be nonnegative integers')
        identity = (timestamp, zone)
        if identity in observed:
            raise ValueError('Duplicate zone-hour rows must be aggregated first')
        observed.add(identity)
        key = f'{zone}|{timestamp.weekday()}|{timestamp.hour}'
        totals[key] += count
        samples[key] += 1
        zone_totals[zone] += count
        zone_samples[zone] += 1
    if not observed:
        raise ValueError('No training observations before cutoff')
    return {
        'model': 'zone_weekday_hour_mean_v1', 'trained_before': cutoff.isoformat(),
        'training_buckets': len(observed),
        'seasonal_mean': {key: totals[key]/samples[key] for key in sorted(totals)},
        'zone_mean': {zone: zone_totals[zone]/zone_samples[zone] for zone in sorted(zone_totals)},
    }


def predict_seasonal(model, timestamp, zone):
    _hour(timestamp)
    if timestamp < datetime.fromisoformat(model['trained_before']):
        raise ValueError('Cannot predict a training timestamp with this fitted model')
    key = f'{zone}|{timestamp.weekday()}|{timestamp.hour}'
    return model['seasonal_mean'].get(key, model['zone_mean'].get(zone, 0.0))


def metrics(actual, predicted):
    """WAPE has an explicit undefined value when the observed sum is zero."""
    if len(actual) != len(predicted) or not actual:
        raise ValueError('Metrics need equal nonempty observations/predictions')
    if any(not isfinite(float(x)) or x < 0 for x in (*actual, *predicted)):
        raise ValueError('Metrics require finite nonnegative values')
    errors = [float(p)-float(y) for y, p in zip(actual, predicted)]
    absolute = sum(abs(e) for e in errors)
    actual_sum = sum(actual)
    return {
        'buckets': len(actual), 'actual_trips': int(actual_sum),
        'zero_observation_buckets': sum(y == 0 for y in actual),
        'mae_trips_per_bucket': round(absolute/len(actual), 6),
        'rmse_trips_per_bucket': round(sqrt(sum(e*e for e in errors)/len(actual)), 6),
        'wape_percent': round(100*absolute/actual_sum, 6) if actual_sum else None,
        'bias_trips_per_bucket': round(sum(errors)/len(actual), 6),
    }
