"""Download official NYC TLC Parquet and evaluate zone-hour demand offline.

No requests reach the SafeJourney API. Reported fare residuals are data-quality
checks in USD, not fraud labels and not validation of the demo VND tariff.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import sys
import time
from zoneinfo import ZoneInfo

import httpx
from .demand import fit_seasonal_mean, predict_seasonal, metrics

TLC_PAGE = 'https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page'
TLC_HOST = 'https://d37ci6vzurychx.cloudfront.net'
MONTH_RE = re.compile(r'20\d{2}-(0[1-9]|1[0-2])\Z')
MAX_BYTES = 128 * 1024 * 1024
MAX_ROWS = 10_000_000
MAX_SECONDS = 180
CENT = Decimal('.01')
BASE_COMPONENTS = ('fare_amount', 'extra', 'mta_tax', 'tip_amount', 'tolls_amount',
                   'improvement_surcharge', 'congestion_surcharge')


def month_window(month):
    if not MONTH_RE.fullmatch(month):
        raise ValueError('Month must be YYYY-MM, year 2000–2099')
    start = datetime.strptime(month, '%Y-%m')
    end = (start.replace(day=28)+timedelta(days=4)).replace(day=1)
    ny = ZoneInfo('America/New_York')
    if start.replace(tzinfo=ny).utcoffset() != (end-timedelta(seconds=1)).replace(tzinfo=ny).utcoffset():
        raise ValueError('This baseline rejects DST transition months: TLC wall-clock timestamps cannot disambiguate repeated/missing hours. Use January for this evaluation.')
    return start, end


def dataset_url(taxi, month):
    if taxi not in ('green', 'yellow') or not MONTH_RE.fullmatch(month):
        raise ValueError('Only official green/yellow monthly TLC files are allowed')
    return f'{TLC_HOST}/trip-data/{taxi}_tripdata_{month}.parquet'


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def source_fingerprint():
    digest = hashlib.sha256()
    folder = Path(__file__).resolve().parent
    files = sorted(folder.glob('*.py'))
    for path in files:
        digest.update(path.name.encode()+b'\0'+path.read_bytes())
    return {'sha256': digest.hexdigest(), 'file_count': len(files)}


def download(taxi, month, directory, *, transport=None):
    """No arbitrary URL, credentials, redirects, overwrite, or unlimited download."""
    url = dataset_url(taxi, month)
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder/f'{taxi}_tripdata_{month}.parquet'
    metadata_path = dest.with_suffix('.source.json')
    if dest.exists() or metadata_path.exists():
        raise FileExistsError('Source or metadata exists; use evaluate or a new download directory')
    partial = dest.with_suffix('.parquet.partial')
    start = time.monotonic()
    written = 0
    # Exclusive create avoids replacing another concurrent downloader's file.
    with partial.open('xb') as stream:
        with httpx.Client(timeout=httpx.Timeout(20, connect=5), follow_redirects=False,
                          trust_env=False, transport=transport) as client:
            with client.stream('GET', url, headers={'Accept-Encoding': 'identity'}) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError('Expected complete HTTP 200, redirects/ranges are not accepted')
                length = response.headers.get('content-length')
                if length and (int(length) <= 0 or int(length) > MAX_BYTES):
                    raise ValueError('Dataset exceeds the bounded download size')
                for chunk in response.iter_bytes(64*1024):
                    written += len(chunk)
                    if written > MAX_BYTES or time.monotonic()-start > MAX_SECONDS:
                        raise ValueError('Dataset exceeds byte/time limit; partial file retained')
                    stream.write(chunk)
    if written < 8:
        raise ValueError('Downloaded file is not Parquet; partial file retained')
    with partial.open('rb') as stream:
        first = stream.read(4)
        stream.seek(-4, 2)
        last = stream.read(4)
    if first != b'PAR1' or last != b'PAR1':
        raise ValueError('Downloaded file has invalid Parquet magic; partial file retained')
    partial.rename(dest)
    provenance = {
        'publisher': 'NYC Taxi and Limousine Commission', 'landing_page': TLC_PAGE,
        'download_url': url, 'downloaded_at_utc': datetime.now(timezone.utc).isoformat(),
        'taxi': taxi, 'month': month, 'bytes': written, 'sha256': sha256_file(dest),
        'redistribution_note': 'Raw file is kept locally and ignored by Git. Review NYC Open Data terms for your intended reuse.',
    }
    with metadata_path.open('x', encoding='utf-8') as stream:
        json.dump(provenance, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return provenance


def money(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    if not result.is_finite() or abs(result) > 1_000_000:
        return None
    return result.quantize(CENT, rounding=ROUND_HALF_EVEN)


def fare_residual(row, components):
    values = [money(row.get(key)) for key in (*components, 'total_amount')]
    if any(value is None for value in values):
        return None
    return values[-1] - sum(values[:-1], Decimal(0))


def _rows(path, required, optional, batch_size):
    import pyarrow.parquet as pq
    parquet = pq.ParquetFile(path)
    names = set(parquet.schema_arrow.names)
    missing = set(required)-names
    if missing:
        raise ValueError(f'Missing required dataset columns: {sorted(missing)}')
    if parquet.metadata.num_rows > MAX_ROWS:
        raise ValueError(f'This local benchmark is limited to {MAX_ROWS:,} rows')
    columns = list(dict.fromkeys([*required, *(column for column in optional if column in names)]))
    return names, parquet.iter_batches(batch_size=batch_size, columns=columns, use_threads=False)


def evaluate(path, taxi, month, *, test_days=7, batch_size=32768):
    path = Path(path)
    if not 1 <= batch_size <= 65536:
        raise ValueError('Batch size must be between 1 and 65,536')
    if test_days != 7:
        raise ValueError('Version 1 fixes the holdout to the last 7 days; do not tune it after seeing results')
    start, end = month_window(month)
    cutoff = end-timedelta(days=test_days)
    if (cutoff-start).days < 21:
        raise ValueError('Need at least 21 training days')
    expected_url = dataset_url(taxi, month)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('Missing input or file exceeds bounded local benchmark size')
    fingerprint_before = source_fingerprint()
    input_hash = sha256_file(path)
    source_meta = path.with_suffix('.source.json')
    provenance = None
    if source_meta.exists():
        provenance = json.loads(source_meta.read_text(encoding='utf-8'))
        if (provenance.get('sha256') != input_hash or provenance.get('bytes') != path.stat().st_size
                or provenance.get('download_url') != expected_url):
            raise ValueError('Input differs from downloaded source metadata')
    pickup_column = 'lpep_pickup_datetime' if taxi == 'green' else 'tpep_pickup_datetime'
    required = [pickup_column, 'PULocationID']
    names, batches = _rows(path, required, (*BASE_COMPONENTS, 'cbd_congestion_fee', 'airport_fee', 'total_amount'), batch_size)
    components = [*BASE_COMPONENTS]
    if int(month[:4]) >= 2025:
        components.append('cbd_congestion_fee')
    if 'airport_fee' in names:
        components.append('airport_fee')
    missing_fare_columns = sorted(set([*components, 'total_amount'])-names)
    counts, excluded = Counter(), Counter()
    quality = Counter()
    fare_abs_total = Decimal(0)
    fare_abs_max = Decimal(0)
    rows_read = 0
    for batch in batches:
        for row in batch.to_pylist():
            rows_read += 1
            pickup, zone = row[pickup_column], row['PULocationID']
            if not isinstance(pickup, datetime) or pickup.tzinfo is not None:
                excluded['missing_or_nonlocal_pickup_timestamp'] += 1
                continue
            if not start <= pickup < end:
                excluded['pickup_outside_named_month'] += 1
                continue
            if isinstance(zone, bool) or not isinstance(zone, int) or not 1 <= zone <= 263:
                excluded['unknown_or_missing_pickup_zone'] += 1
                continue
            hour = pickup.replace(minute=0, second=0, microsecond=0)
            counts[(hour, str(zone))] += 1
            if missing_fare_columns:
                continue
            residual = fare_residual(row, components)
            if residual is None:
                quality['missing_nonfinite_or_extreme_money_rows'] += 1
                continue
            quality['comparable_rows'] += 1
            quality['within_one_cent_rows' if abs(residual) <= CENT else 'residual_over_one_cent_rows'] += 1
            if any(money(row[key]) < 0 for key in (*components, 'total_amount')):
                quality['negative_component_or_total_rows'] += 1
            fare_abs_total += abs(residual)
            fare_abs_max = max(fare_abs_max, abs(residual))
    if not counts or not any(ts >= cutoff for ts, _ in counts):
        raise ValueError('No valid pickup demand in month/holdout')
    if sum(counts.values())+sum(excluded.values()) != rows_read:
        raise AssertionError('Row accounting failed')
    zones = tuple(str(zone) for zone in range(1, 264))
    train_hours = [start+timedelta(hours=i) for i in range(int((cutoff-start).total_seconds()/3600))]
    test_hours = [cutoff+timedelta(hours=i) for i in range(test_days*24)]
    model = fit_seasonal_mean(((hour, zone, counts[(hour, zone)]) for hour in train_hours for zone in zones), cutoff)
    weekly_totals, weekly_samples = Counter(), Counter()
    for hour in train_hours:
        key = (hour.weekday(), hour.hour)
        weekly_totals[key] += sum(counts[(hour, zone)] for zone in zones)
        weekly_samples[key] += 1
    peak_keys = sorted(weekly_totals, key=lambda key: (-weekly_totals[key]/weekly_samples[key], key))[:34]
    peak_set = set(peak_keys)
    predictions = {name: [] for name in ('seasonal_mean', 'lag_24h', 'lag_168h', 'zero')}
    actual, peak_mask = [], []
    city_actual, city_predictions = [], {name: [] for name in predictions}
    for hour in test_hours:
        city_actual.append(sum(counts[(hour, zone)] for zone in zones))
        hourly_predictions = {name: 0.0 for name in predictions}
        for zone in zones:
            actual.append(counts[(hour, zone)])
            peak_mask.append((hour.weekday(), hour.hour) in peak_set)
            values = {'seasonal_mean': predict_seasonal(model, hour, zone),
                      'lag_24h': counts[(hour-timedelta(hours=24), zone)],
                      'lag_168h': counts[(hour-timedelta(hours=168), zone)], 'zero': 0}
            for name, value in values.items():
                predictions[name].append(value)
                hourly_predictions[name] += value
        for name in predictions:
            city_predictions[name].append(hourly_predictions[name])
    results = {}
    for name, predicted in predictions.items():
        results[name] = {'zone_hour': metrics(actual, predicted),
            'peak_zone_hour': metrics([x for x, peak in zip(actual, peak_mask) if peak], [x for x, peak in zip(predicted, peak_mask) if peak]),
            'off_peak_zone_hour': metrics([x for x, peak in zip(actual, peak_mask) if not peak], [x for x, peak in zip(predicted, peak_mask) if not peak]),
            'city_hour': metrics(city_actual, city_predictions[name])}
    comparable = quality['comparable_rows']
    fingerprint_after = source_fingerprint()
    if fingerprint_before != fingerprint_after or input_hash != sha256_file(path):
        raise ValueError('Measured source or input changed during evaluation')
    return {
        'schema_version': 1, 'benchmark': 'tlc_zone_hour_forecast_v1',
        'completed_at_utc': datetime.now(timezone.utc).isoformat(), 'source': {
            'publisher': 'NYC Taxi and Limousine Commission', 'landing_page': TLC_PAGE,
            'expected_official_url': expected_url, 'file_name': path.name, 'bytes': path.stat().st_size,
            'sha256': input_hash, 'provenance': provenance,
            'download_manifest_verified': provenance is not None,
            'input_assertion': 'Official downloader manifest matches' if provenance else 'Caller-supplied file; source not independently authenticated',
        },
        'implementation': {'source_fingerprint': fingerprint_before, 'source_unchanged': True,
                           'python': sys.version.split()[0], 'pyarrow': importlib.metadata.version('pyarrow')},
        'protocol': {'spatial_unit': 'TLC taxi zone, IDs 1–263; not H3/GPS',
            'time_unit': 'one local New York wall-clock hour; DST transition months rejected',
            'month': month, 'train_start_inclusive': start.isoformat(), 'train_end_exclusive': cutoff.isoformat(),
            'test_start_inclusive': cutoff.isoformat(), 'test_end_exclusive': end.isoformat(),
            'forecast_horizon': 'one hour ahead; lag models may use earlier observed holdout hours, never target/future hours',
            'seasonal_fit': 'frozen using training interval only, mean per zone × weekday × hour',
            'zero_filling': 'all 263 zones × every train/test hour, independent of test demand',
            'peak_definition': 'top 34 of 168 weekday/hour slots by train-only mean total pickups; tie-break weekday/hour',
            'peak_weekday_hours': [{'weekday_monday_zero': day, 'hour': hour} for day, hour in peak_keys],
            'duplicates': 'No trip ID is provided; coincident records retained rather than guessed duplicate trips',
            'batch_size': batch_size},
        'coverage': {'rows_read': rows_read, 'accepted_pickups': sum(counts.values()), 'excluded_rows': dict(excluded),
            'train_pickups': sum(counts[(hour, zone)] for hour in train_hours for zone in zones),
            'test_pickups': sum(actual), 'train_hours': len(train_hours), 'test_hours': len(test_hours),
            'zone_count': len(zones), 'train_zone_hours': len(train_hours)*len(zones), 'test_zone_hours': len(actual),
            'active_train_zones': sum(any(counts[(hour, zone)] for hour in train_hours) for zone in zones),
            'active_test_zones': sum(any(counts[(hour, zone)] for hour in test_hours) for zone in zones)},
        'demand_results': results,
        'fare_data_quality': {'currency': 'USD', 'components': components, 'missing_columns': missing_fare_columns,
            'status': 'NOT_AVAILABLE' if missing_fare_columns else 'MEASURED', 'row_counts': dict(quality),
            'absolute_residual_sum_usd': str(fare_abs_total), 'absolute_residual_max_usd': str(fare_abs_max),
            'mean_absolute_residual_usd': str((fare_abs_total/comparable).quantize(CENT)) if comparable else None,
            'method': 'Decimal from source value text, each component rounded to cents HALF_EVEN; total minus component sum; tolerance 0.01 USD',
            'interpretation': 'Reconciliation only; residuals can reflect source/schema issues and are not fraud labels or a recalculated legal fare.'},
        'limitations': [
            'Observed pickups measure completed recorded service, not unmet demand or supply availability.',
            'TLC zones and trip records do not provide raw GPS trajectories, SOS labels, weather, battery SOC or charger queues.',
            'No safety/fraud precision or recall, road-route accuracy, EV model accuracy, causal weather effect or throughput claim is derived.',
            'One city and one held-out week; no threshold tuned to force a PASS and no claim a seasonal model always beats naive baselines.',
            'This offline forecast/data-quality benchmark is separate from API load tests and synthetic operational scenarios.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    download_parser = sub.add_parser('download', help='Bounded official TLC download')
    download_parser.add_argument('--taxi', choices=('green', 'yellow'), default='green')
    download_parser.add_argument('--month', default='2025-01')
    download_parser.add_argument('--directory', type=Path, default=Path('research_benchmarks/data'))
    evaluate_parser = sub.add_parser('evaluate', help='Chronological demand and fare-data-quality evaluation')
    evaluate_parser.add_argument('--input', type=Path, required=True)
    evaluate_parser.add_argument('--taxi', choices=('green', 'yellow'), default='green')
    evaluate_parser.add_argument('--month', default='2025-01')
    evaluate_parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'download':
            result = download(args.taxi, args.month, args.directory)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if args.output.exists():
                raise FileExistsError('Preserve existing reports; choose a new output filename')
            result = evaluate(args.input, args.taxi, args.month)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x', encoding='utf-8') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write('\n')
            print(json.dumps({'report': str(args.output), 'coverage': result['coverage'],
                              'demand_results': result['demand_results']}, ensure_ascii=False, indent=2))
    except (ValueError, OSError, httpx.HTTPError) as exc:
        parser.exit(2, f'{type(exc).__name__}: {exc}\n')


if __name__ == '__main__':
    main()
