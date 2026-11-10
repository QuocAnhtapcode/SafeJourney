from datetime import datetime, timedelta
from decimal import Decimal
import json
import httpx
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from research_benchmarks.demand import fit_seasonal_mean, predict_seasonal, metrics
from research_benchmarks import tlc


def test_model_freezes_before_cutoff_and_does_not_learn_holdout():
    cutoff = datetime(2025, 1, 25)
    past = datetime(2025, 1, 18, 10)
    future = datetime(2025, 1, 25, 10)
    rows = [(past, '42', 2), (past-timedelta(days=7), '42', 4), (future, '42', 900_000)]
    model = fit_seasonal_mean(rows, cutoff)
    assert predict_seasonal(model, future, '42') == 3
    assert model['training_buckets'] == 2
    assert predict_seasonal(model, future, '999') == 0
    with pytest.raises(ValueError, match='training timestamp'):
        predict_seasonal(model, past, '42')


def test_zero_observations_are_training_evidence_not_missing_rows():
    cutoff = datetime(2025, 1, 25)
    model = fit_seasonal_mean([(datetime(2025, 1, 18, 10), '1', 6),
                               (datetime(2025, 1, 11, 10), '1', 0)], cutoff)
    assert predict_seasonal(model, datetime(2025, 1, 25, 10), '1') == 3
    with pytest.raises(ValueError, match='Duplicate'):
        fit_seasonal_mean([(datetime(2025, 1, 18), '1', 1)]*2, cutoff)


@pytest.mark.parametrize('bad', [-1, True, 1.5, float('nan')])
def test_training_rejects_invalid_counts(bad):
    with pytest.raises(ValueError):
        fit_seasonal_mean([(datetime(2025, 1, 1), '1', bad)], datetime(2025, 1, 25))


def test_metrics_include_zero_buckets_and_handle_zero_denominator():
    result = metrics([0, 2], [1, 1])
    assert result['mae_trips_per_bucket'] == 1
    assert result['wape_percent'] == 100
    assert result['zero_observation_buckets'] == 1
    assert metrics([0, 0], [1, 0])['wape_percent'] is None
    with pytest.raises(ValueError):
        metrics([1], [float('inf')])


def test_download_url_does_not_accept_arbitrary_hosts_or_traversal():
    assert tlc.dataset_url('green', '2025-01').endswith('/green_tripdata_2025-01.parquet')
    for taxi, month in [('https://other.test', '2025-01'), ('green', '../secret'), ('green', '2025-13')]:
        with pytest.raises(ValueError):
            tlc.dataset_url(taxi, month)


def test_downloader_keeps_hash_manifest_and_will_not_overwrite(tmp_path):
    payload = b'PAR1synthetic-download-testPAR1'
    urls = []
    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, content=payload)
    manifest = tlc.download('green', '2025-01', tmp_path, transport=httpx.MockTransport(handler))
    target = tmp_path/'green_tripdata_2025-01.parquet'
    assert target.read_bytes() == payload
    assert manifest['sha256'] == tlc.sha256_file(target)
    assert manifest['bytes'] == len(payload)
    assert urls == [tlc.dataset_url('green', '2025-01')]
    with pytest.raises(FileExistsError):
        tlc.download('green', '2025-01', tmp_path, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize('kind', ['redirect', 'too_large', 'bad_magic', 'partial_http'])
def test_downloader_rejects_redirects_size_and_invalid_file(tmp_path, kind):
    def handler(request):
        if kind == 'redirect':
            return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
        if kind == 'too_large':
            return httpx.Response(200, headers={'content-length': str(tlc.MAX_BYTES+1)}, content=b'PAR1xPAR1')
        if kind == 'partial_http':
            return httpx.Response(206, content=b'PAR1xPAR1')
        return httpx.Response(200, content=b'not parquet')
    with pytest.raises((ValueError, httpx.HTTPStatusError)):
        tlc.download('green', '2025-01', tmp_path, transport=httpx.MockTransport(handler))
    assert not (tmp_path/'green_tripdata_2025-01.parquet').exists()
    assert (tmp_path/'green_tripdata_2025-01.parquet.partial').exists()


def test_fare_reconciliation_is_decimal_and_missing_money_is_not_zero():
    assert tlc.fare_residual({'fare_amount': 0.1, 'extra': 0.2, 'total_amount': 0.3}, ['fare_amount', 'extra']) == Decimal('0.00')
    assert tlc.fare_residual({'fare_amount': 4.0, 'total_amount': 4.0}, ['fare_amount', 'extra']) is None
    assert tlc.money(float('nan')) is None
    assert tlc.money(float('inf')) is None


def test_month_split_and_dst_are_explicit():
    start, end = tlc.month_window('2025-02')
    assert (end-timedelta(days=7)-start).days == 21
    with pytest.raises(ValueError, match='DST'):
        tlc.month_window('2025-03')


def sample_parquet(path):
    pickups = [datetime(2025, 1, 1, 10), datetime(2025, 1, 24, 10),
               datetime(2025, 1, 25, 10), datetime(2025, 1, 26, 10),
               datetime(2024, 12, 31, 10), datetime(2025, 1, 27, 10), None]
    n = len(pickups)
    values = {'lpep_pickup_datetime': pickups, 'PULocationID': [1, 1, 1, 2, 1, 264, 1]}
    for component in (*tlc.BASE_COMPONENTS, 'cbd_congestion_fee'):
        values[component] = [0.0]*n
    values['fare_amount'] = [10.0]*n
    values['total_amount'] = [10.0, 10.0, 11.0, 10.0, 10.0, 10.0, 10.0]
    pq.write_table(pa.table(values), path)


def test_parquet_evaluation_is_chronological_zero_filled_and_accounts_for_rejections(tmp_path):
    path = tmp_path/'sample.parquet'
    sample_parquet(path)
    report = tlc.evaluate(path, 'green', '2025-01', batch_size=2)
    assert report['coverage']['rows_read'] == 7
    assert report['coverage']['accepted_pickups'] == 4
    assert sum(report['coverage']['excluded_rows'].values()) == 3
    assert report['coverage']['train_pickups'] == 2
    assert report['coverage']['test_pickups'] == 2
    assert report['coverage']['test_zone_hours'] == 263*168
    assert report['coverage']['active_train_zones'] == 1
    assert report['coverage']['active_test_zones'] == 2
    assert report['protocol']['train_end_exclusive'] == '2025-01-25T00:00:00'
    assert report['source']['download_manifest_verified'] is False
    assert report['fare_data_quality']['row_counts']['residual_over_one_cent_rows'] == 1
    assert report['fare_data_quality']['absolute_residual_sum_usd'] == '1.00'
    assert report['demand_results']['lag_24h']['zone_hour']['buckets'] == 263*168
    assert report['implementation']['source_unchanged'] is True


def test_modified_input_cannot_reuse_verified_download_manifest(tmp_path):
    path = tmp_path/'sample.parquet'
    sample_parquet(path)
    path.with_suffix('.source.json').write_text(json.dumps({'sha256': 'bad'}), encoding='utf-8')
    with pytest.raises(ValueError, match='metadata'):
        tlc.evaluate(path, 'green', '2025-01')
