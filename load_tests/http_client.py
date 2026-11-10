"""Low-overhead load transport; session cookies are explicit per synthetic actor."""
import json
from dataclasses import dataclass
import aiohttp


@dataclass
class Response:
    status_code: int
    cookies: dict
    body: bytes

    def json(self):
        return json.loads(self.body)


class LoadClient:
    def __init__(self, base_url, timeout, max_connections):
        self.base_url = base_url
        self.timeout = timeout
        self.max_connections = max_connections
        self.cookies = {}  # No shared cookie jar: every request supplies its actor.

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            base_url=self.base_url, cookie_jar=aiohttp.DummyCookieJar(), trust_env=False,
            timeout=aiohttp.ClientTimeout(total=self.timeout),
            connector=aiohttp.TCPConnector(limit=self.max_connections, keepalive_timeout=4))
        return self

    async def __aexit__(self, *args):
        await self.session.close()

    async def request(self, method, path, **kwargs):
        if 'timeout' in kwargs:
            kwargs['timeout'] = aiohttp.ClientTimeout(total=kwargs['timeout'])
        async with self.session.request(method, path, allow_redirects=False, **kwargs) as response:
            return Response(response.status, {key: value.value for key, value in response.cookies.items()},
                            await response.read())

    async def get(self, path, **kwargs):
        return await self.request('GET', path, **kwargs)

    async def post(self, path, **kwargs):
        return await self.request('POST', path, **kwargs)
