import test from 'node:test';
import assert from 'node:assert/strict';
import { api, apiList } from '../src/api.js';

test('HTML/malformed success is rejected instead of becoming an empty success', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('<html>proxy error</html>', { status: 200 }));
  await assert.rejects(api('/api/trips'), /không hợp lệ/);
});

test('expired-session status survives a malformed error body', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('expired', { status: 401 }));
  await assert.rejects(api('/api/me'), error => error.status === 401);
});

test('list endpoints reject a valid JSON object that is not a list', async t => {
  t.mock.method(globalThis, 'fetch', async () => Response.json({ unexpected: 'object' }));
  await assert.rejects(apiList('/api/trips'), /danh sách không hợp lệ/);
});
