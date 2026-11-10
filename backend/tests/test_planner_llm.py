"""LLM adapter behavior without a database or an Ollama service."""
import logging

import httpx
import pytest

from app import planner


@pytest.fixture(autouse=True)
def ollama_config(monkeypatch):
    monkeypatch.setenv('LLM_MODE', 'ollama')
    monkeypatch.setenv('OLLAMA_URL', 'http://localhost:11434/')
    monkeypatch.delenv('LLM_TIMEOUT_SECONDS', raising=False)


def test_mock_does_not_call_model(monkeypatch):
    monkeypatch.setenv('LLM_MODE', 'mock')

    def unexpected_request(*args, **kwargs):
        pytest.fail('Mock mode must not call Ollama')

    monkeypatch.setattr(planner.httpx, 'post', unexpected_request)
    assert planner.analyze({'kind': 'SOS', 'severity': 3})['advice'].startswith('[Mẫu dự phòng, chưa dùng LLM]')


def test_valid_advice_uses_cold_start_budget_and_local_connection(monkeypatch):
    monkeypatch.setenv('LLM_MODE', ' Ollama ')

    def response(url, **kwargs):
        assert url == 'http://localhost:11434/api/chat'
        assert kwargs['timeout'].read == 60
        assert kwargs['timeout'].connect == 3
        assert kwargs['trust_env'] is False
        assert kwargs['json']['format']['additionalProperties'] is False
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'message': {'content': '{"evidence_keys": ["signal"], "check_ids": ["choose_safe_channel", "human_emergency_review"]}'}})

    monkeypatch.setattr(planner.httpx, 'post', response)
    result = planner.analyze({'kind': 'SOS', 'severity': 3})
    assert result['advice'].startswith('[LLM đề xuất; nhân viên cần kiểm tra]')
    assert 'Đã nhận tín hiệu SOS' in result['advice']
    assert 'chọn kênh liên hệ' in result['advice']
    assert set(result) == {'advice'}  # Model output never grants execution rights.


def test_measurements_reach_model_without_private_evidence(monkeypatch):
    def response(url, **kwargs):
        user_message = kwargs['json']['messages'][1]['content']
        assert '105' in user_message and '90' in user_message
        assert 'PRIVATE' not in user_message
        return httpx.Response(200, request=httpx.Request('POST', url), json={'message': {
            'content': '{"evidence_keys": ["speed_kmh", "speed_threshold_kmh"], "check_ids": ["check_speed_samples"]}'}})

    monkeypatch.setattr(planner.httpx, 'post', response)
    result = planner.analyze({'kind': 'SPEED', 'severity': 2, 'evidence': {
        'speed_kmh': 105, 'speed_threshold_kmh': 90, 'lat': 'PRIVATE', 'summary': 'PRIVATE'}})
    assert '105 km/h' in result['advice'] and '90 km/h' in result['advice']
    assert 'chuỗi tốc độ' in result['advice']


@pytest.mark.parametrize('error,reason', [
    (httpx.ReadTimeout('PRIVATE URL or evidence'), 'timeout'),
    (httpx.ConnectError('PRIVATE URL or evidence'), 'connection'),
])
def test_network_failure_falls_back_with_private_diagnostics(monkeypatch, caplog, error, reason):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(planner.httpx, 'post', fail)
    with caplog.at_level(logging.WARNING, logger='app.planner'):
        result = planner.analyze({'kind': 'SOS', 'severity': 3})
    assert result['advice'].startswith('[LLM lỗi/quá hạn; dùng mẫu]')
    assert f'reason={reason}' in caplog.text
    assert 'PRIVATE' not in caplog.text


def test_missing_model_status_is_reported_without_response_body(monkeypatch, caplog):
    monkeypatch.setattr(planner.httpx, 'post', lambda url, **kwargs: httpx.Response(
        404, request=httpx.Request('POST', url), json={'error': 'PRIVATE model response'}))
    with caplog.at_level(logging.WARNING, logger='app.planner'):
        result = planner.analyze({'kind': 'SPEED', 'severity': 2})
    assert result['advice'].startswith('[LLM lỗi/quá hạn; dùng mẫu]')
    assert 'reason=http_status' in caplog.text and 'status=404' in caplog.text
    assert 'PRIVATE' not in caplog.text


@pytest.mark.parametrize('content', ['{"advice": "unfinished', '{"advice": 123}', '{}'])
def test_bad_model_content_remains_a_fallback(monkeypatch, caplog, content):
    monkeypatch.setattr(planner.httpx, 'post', lambda url, **kwargs: httpx.Response(
        200, request=httpx.Request('POST', url), json={'message': {'content': content}}))
    with caplog.at_level(logging.WARNING, logger='app.planner'):
        result = planner.analyze({'kind': 'SPEED', 'severity': 2})
    assert result['advice'].startswith('[LLM lỗi/quá hạn; dùng mẫu]')
    assert 'reason=invalid_response_or_config' in caplog.text


@pytest.mark.parametrize('timeout', ['0', '-1', 'nan', 'inf', 'invalid'])
def test_invalid_timeout_never_turns_into_an_unbounded_call(monkeypatch, caplog, timeout):
    monkeypatch.setenv('LLM_TIMEOUT_SECONDS', timeout)

    def unexpected_request(*args, **kwargs):
        pytest.fail('Invalid configuration must be rejected before requesting')

    monkeypatch.setattr(planner.httpx, 'post', unexpected_request)
    with caplog.at_level(logging.WARNING, logger='app.planner'):
        result = planner.analyze({'kind': 'SPEED', 'severity': 2})
    assert result['advice'].startswith('[LLM lỗi/quá hạn; dùng mẫu]')
    assert 'reason=invalid_response_or_config' in caplog.text
