import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import test from 'node:test';
import { createToolBridge } from '../scripts/lib/tool-bridge.js';

function harness(timeout = 200) {
  const channel = new EventEmitter();
  channel.connected = true;
  channel.send = (request, done) => { channel.request = request; done?.(); };
  const failures = [];
  const bridge = createToolBridge(channel, 'case', (error) => failures.push(error), timeout);
  const controller = new AbortController();
  const exec = { agent: { session: { id: 'session' } }, signal: controller.signal };
  const respond = (patch = {}) => channel.emit('message', { ...channel.request, type: 'tool-response', isError: false, text: 'value', ...patch });
  return { channel, bridge, controller, exec, respond, failures };
}

test('live bridge matches responses and returns expected tool errors', async () => {
  const h = harness();
  try {
    const result = h.bridge.request('read', { path: 'file' }, h.exec);
    h.respond();
    assert.equal(await result, 'value');
    h.respond(); // duplicate is ignored
    const failed = h.bridge.request('read', { path: 'file' }, h.exec);
    h.respond({ isError: true, text: 'TEMPORARY_READ_FAILURE' });
    await assert.rejects(failed, /TEMPORARY_READ_FAILURE/);
    assert.deepEqual(h.failures, []);
  } finally { h.bridge.close(); }
});

test('wrong identity and deadline are infrastructure failures', async () => {
  for (const mode of ['identity', 'deadline', 'disconnect']) {
    const h = harness(10);
    try {
      const result = h.bridge.request('read', { path: 'file' }, h.exec);
      if (mode === 'identity') h.respond({ sessionId: 'other' });
      if (mode === 'disconnect') h.channel.emit('disconnect');
      await assert.rejects(result, /Invalid bridge|deadline|disconnected/);
      assert.equal(h.failures.length, 1);
    } finally { h.bridge.close(); }
  }
});

test('abort and disposal reject pending work and late replies cannot resume it', async () => {
  const h = harness();
  const result = h.bridge.request('read', { path: 'file' }, h.exec);
  h.controller.abort();
  h.respond();
  await assert.rejects(result, /cancelled/);
  h.bridge.close();
  assert.equal(h.channel.listenerCount('message'), 0);
  assert.deepEqual(h.failures, []);
  const next = harness();
  const pending = next.bridge.request('read', { path: 'file' }, next.exec);
  next.bridge.close();
  await assert.rejects(pending, /closed/);
  await assert.rejects(next.bridge.request('read', { path: 'file' }, next.exec), /unavailable/);
});
