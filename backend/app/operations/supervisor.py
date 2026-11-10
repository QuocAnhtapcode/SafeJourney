"""Optional LLM chooses a specialist priority, never tool values or authority."""
import json
import os
import logging
import asyncio
import httpx

logger = logging.getLogger(__name__)
FOCI = ('energy', 'fare', 'demand')
MAX_MODEL_RESPONSE_BYTES = 32_768


async def _request_selection_async(url, payload, seconds, *, transport=None):
    # Limit the entire exchange, not only each read: a slow trickle must not
    # hold an operations slot past its lease or accumulate an unbounded body.
    async with asyncio.timeout(seconds):
        async with httpx.AsyncClient(timeout=httpx.Timeout(seconds, connect=min(3.0, seconds)),
                                     trust_env=False, follow_redirects=False, transport=transport) as client:
            async with client.stream('POST', url, json=payload) as response:
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    data.extend(chunk)
                    if len(data) > MAX_MODEL_RESPONSE_BYTES:
                        raise ValueError('Supervisor response exceeds size limit')
    return json.loads(data)


def _request_selection(url, payload, seconds, *, transport=None):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_request_selection_async(url, payload, seconds, transport=transport))
    raise ValueError('Synchronous supervisor must run in a worker thread')


def choose_focus(snapshot):
    default = {'low_battery': 'energy', 'fare_dispute': 'fare'}.get(snapshot['scenario_id'], 'demand')
    mode = os.getenv('OPERATIONS_LLM_MODE', 'mock').strip().lower()
    if mode != 'ollama':
        return {'focus': default, 'source': 'backend_policy', 'model_used': False}
    try:
        seconds = float(os.getenv('OPERATIONS_LLM_TIMEOUT_SECONDS', '8'))
        if not 0 < seconds <= 15:
            raise ValueError('Invalid operations LLM timeout')
        payload = {'model': os.getenv('OLLAMA_MODEL', 'qwen2.5:3b'), 'stream': False,
                  'format': {'type': 'object', 'properties': {'focus': {'type': 'string', 'enum': list(FOCI)}},
                             'required': ['focus'], 'additionalProperties': False},
                  'options': {'temperature': 0, 'num_predict': 32},
                  'messages': [
                      {'role': 'system', 'content': 'Chọn ưu tiên energy, fare hoặc demand cho nhóm agent. Chỉ trả JSON focus. '
                       'Không tính số, không chọn người nhận, không cấp quyền. Mọi công cụ bắt buộc vẫn phải chạy.'},
                      {'role': 'user', 'content': json.dumps({'scenario': snapshot['scenario_id'],
                        'low_battery': snapshot['profile']['soc_percent'] <= 20,
                        'high_demand': snapshot['demand_factor'] > 1})}]}
        response = _request_selection(os.getenv('OLLAMA_URL', 'http://localhost:11434').strip().rstrip('/')+'/api/chat',
                                      payload, seconds)
        value = json.loads(response['message']['content'])
        if not isinstance(value, dict) or set(value) != {'focus'} or value['focus'] not in FOCI:
            raise ValueError('Invalid supervisor selection')
        return {'focus': value['focus'], 'source': 'ollama_validated_selection', 'model_used': True}
    except (TimeoutError, httpx.HTTPError, ValueError, KeyError, TypeError, RecursionError):
        # Never log endpoints, prompts, raw model replies or trip identity.
        logger.warning('Operations supervisor fallback: model unavailable or invalid selection')
        return {'focus': default, 'source': 'backend_fallback', 'model_used': False}
