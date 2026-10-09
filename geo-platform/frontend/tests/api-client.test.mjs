import assert from 'node:assert/strict';
import test from 'node:test';
import { request } from '../src/api/client.ts';

test('read JSON and merge Headers without dropping content type', async t => {
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    assert.equal(url, '/api/test');
    assert.equal(init.headers.get('X-Test'), 'yes');
    assert.equal(init.headers.get('Content-Type'), 'application/json');
    return Response.json({ version: 'fixed-v1' });
  });
  assert.deepEqual(await request('/api/test', { headers: new Headers({ 'X-Test': 'yes' }) }), { version: 'fixed-v1' });
});

test('timeout aborts once and never retries a possibly accepted mutation', async t => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', (url, init) => {
    calls++;
    return new Promise((resolve, reject) => init.signal.addEventListener('abort', () => reject(init.signal.reason), { once: true }));
  });
  await assert.rejects(request('/api/test', { method: 'POST', body: '{}' }, 10), /请求超时.*不会自动重复提交/);
  assert.equal(calls, 1);
});

test('caller cancellation remains AbortError and is not mislabeled as timeout', async t => {
  const controller = new AbortController();
  controller.abort();
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    assert.equal(init.signal.aborted, true);
    throw init.signal.reason;
  });
  await assert.rejects(request('/api/test', { signal: controller.signal }), { name: 'AbortError' });
});

test('deadline covers response body, not just receipt of headers', async t => {
  t.mock.method(globalThis, 'fetch', async (url, init) => ({
    ok: true,
    headers: new Headers({ 'Content-Type': 'application/json' }),
    json: () => new Promise((resolve, reject) => init.signal.addEventListener('abort', () => reject(init.signal.reason), { once: true })),
  }));
  await assert.rejects(request('/api/test', undefined, 10), /请求超时/);
});

test('schema errors and frontend HTML are not treated as success', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json({ detail: [{ loc: ['body', 'name'], msg: 'required' }] }, { status: 422 }));
  await assert.rejects(request('/api/test'), /name：required/);
  fetch.mock.mockImplementation(async () => new Response('<!doctype html>', { headers: { 'Content-Type': 'text/html' } }));
  await assert.rejects(request('/api/test'), /后端接口没有返回 JSON/);
});
