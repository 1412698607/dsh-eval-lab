import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import test from 'node:test';
import { createToolBridge, registerStatefulTools } from '../scripts/lib/tool-bridge.js';

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
  assert.equal(h.channel.request.type, 'tool-cancel');
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

test('write registration is opt-in and forwards exact content', async () => {
  const registered = new Map();
  const ctx = { tools: { register: (tool) => registered.set(tool.name, tool) } };
  const calls = [];
  const bridge = { request: (...args) => { calls.push(args); return Promise.resolve('WROTE'); } };
  registerStatefulTools(ctx, (tool) => tool, bridge);
  assert.equal(registered.has('eval_write'), false);
  registerStatefulTools(ctx, (tool) => tool, bridge, ['eval_write']);
  const tool = registered.get('eval_write');
  assert.equal(tool.parameters.content.required, true);
  const args = { path: 'file', content: '' }, exec = {};
  await tool.execute(args, exec);
  assert.deepEqual(calls, [['write', args, exec]]);
});

test('tool timeout responses are recoverable and independent of bridge failure', async () => {
  const h = harness();
  try {
    const result = h.bridge.request('write', { path: 'file', content: 'x' }, h.exec);
    h.respond({ isError: true, text: 'TOOL_TIMEOUT: file' });
    await assert.rejects(result, /TOOL_TIMEOUT/);
    const retry = h.bridge.request('write', { path: 'file', content: 'x' }, h.exec);
    h.respond({ text: 'WROTE: file' });
    assert.equal(await retry, 'WROTE: file');
    assert.deepEqual(h.failures, []);
  } finally { h.bridge.close(); }
});

test('configured per-tool policy gives the bridge a separate watchdog', async () => {
  const channel = new EventEmitter();
  channel.connected = true;
  channel.send = (message, done) => { channel.request = message; done?.(); };
  const failures = [];
  const bridge = createToolBridge(channel, 'case', (error) => failures.push(error), 1,
    { toolTimeoutMs: 5, toolTimeoutsMs: { eval_write: 100 } });
  try {
    const request = bridge.request('write', { path: 'file', content: 'x' },
      { agent: { session: { id: 'session' } }, signal: new AbortController().signal });
    await new Promise((resolve) => setTimeout(resolve, 20));
    channel.emit('message', { ...channel.request, type: 'tool-response', isError: true, text: 'TOOL_TIMEOUT: file' });
    await assert.rejects(request, /TOOL_TIMEOUT/);
    assert.deepEqual(failures, []);
  } finally { bridge.close(); }
});
