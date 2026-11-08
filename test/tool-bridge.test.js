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

test('delete and exact edit are opt-in with distinct argument schemas', async () => {
  const registered = new Map(), calls = [];
  const ctx = { tools: { register: (tool) => registered.set(tool.name, tool) } };
  const bridge = { request: (...args) => { calls.push(args); return Promise.resolve('OK'); } };
  registerStatefulTools(ctx, (tool) => tool, bridge);
  assert.deepEqual([...registered.keys()], ['eval_read', 'eval_list']);
  registerStatefulTools(ctx, (tool) => tool, bridge, ['eval_delete', 'eval_edit']);
  assert.deepEqual(Object.keys(registered.get('eval_delete').parameters), ['path']);
  const edit = registered.get('eval_edit');
  assert.deepEqual(Object.keys(edit.parameters), ['path', 'oldText', 'newText']);
  assert.equal(edit.parameters.oldText.required, true);
  assert.equal(edit.parameters.newText.required, true);
  const args = { path: 'file', oldText: '旧值\r\n', newText: '' }, exec = {};
  await edit.execute(args, exec);
  await registered.get('eval_delete').execute({ path: 'file' }, exec);
  assert.deepEqual(calls, [['edit', args, exec], ['delete', { path: 'file' }, exec]]);
});

test('edit ambiguity and missing delete target leave the bridge usable', async () => {
  const h = harness();
  try {
    for (const [operation, text] of [['edit', 'AMBIGUOUS_MATCH: file'], ['delete', 'NOT_FOUND: file']]) {
      const result = h.bridge.request(operation, { path: 'file' }, h.exec);
      h.respond({ isError: true, text });
      await assert.rejects(result, (error) => error.message === text);
    }
    const result = h.bridge.request('read', { path: 'file' }, h.exec);
    h.respond({ text: 'unchanged' });
    assert.equal(await result, 'unchanged');
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

test('one cancelled or timed-out waiter cannot settle other outstanding calls', async () => {
  const channel = new EventEmitter(), messages = [], failures = [];
  channel.connected = true;
  channel.send = (message, done) => { messages.push(message); done?.(); };
  const bridge = createToolBridge(channel, 'case', (error) => failures.push(error), 1000);
  const controller = new AbortController();
  const exec = (signal) => ({ agent: { session: { id: 'session' } }, signal });
  const healthy = new AbortController();
  try {
    const cancelled = bridge.request('delete', { path: 'keep' }, exec(controller.signal));
    const timed = bridge.request('write', { path: 'old', content: 'new' }, exec(healthy.signal));
    const edit = bridge.request('edit', { path: 'file', oldText: 'a', newText: 'b' }, exec(healthy.signal));
    const [first, second, third] = messages;
    const rejectedCancel = assert.rejects(cancelled, /cancelled/);
    const rejectedTimeout = assert.rejects(timed, /TOOL_TIMEOUT/);
    controller.abort();
    assert.equal(messages[3].type, 'tool-cancel');
    assert.equal(messages[3].requestId, first.requestId);
    const respond = (request, patch = {}) => channel.emit('message', { ...request, type: 'tool-response',
      isError: false, text: 'ok', ...patch });
    respond(second, { isError: true, text: 'TOOL_TIMEOUT: old' });
    await Promise.all([rejectedCancel, rejectedTimeout]);
    let editSettled = false;
    edit.then(() => { editSettled = true; });
    respond(first, { text: 'late deletion' });
    respond(second, { sessionId: 'wrong-late-session', text: 'late write' });
    await Promise.resolve();
    assert.equal(editSettled, false);
    respond(third, { text: 'EDITED: file' });
    respond(third, { isError: true, text: 'duplicate failure' });
    assert.equal(await edit, 'EDITED: file');
    assert.deepEqual(failures, []);
  } finally { bridge.close(); }
});

test('late response from a timed-out attempt cannot complete its retry', async () => {
  const h = harness();
  try {
    const first = h.bridge.request('write', { path: 'file', content: 'new' }, h.exec);
    const old = { ...h.channel.request };
    h.respond({ isError: true, text: 'TOOL_TIMEOUT: file' });
    await assert.rejects(first, /TOOL_TIMEOUT/);
    const retry = h.bridge.request('write', { path: 'file', content: 'new' }, h.exec);
    const current = { ...h.channel.request };
    assert.notEqual(old.requestId, current.requestId);
    let settled = false;
    retry.then(() => { settled = true; });
    h.channel.emit('message', { ...old, type: 'tool-response', isError: false, text: 'stale success' });
    await Promise.resolve();
    assert.equal(settled, false);
    h.respond({ text: 'WROTE: file' });
    assert.equal(await retry, 'WROTE: file');
    assert.deepEqual(h.failures, []);
  } finally { h.bridge.close(); }
});
