import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, isAbsolute, join, relative, resolve } from "node:path";
import * as config from "../src/config.js";
import { createRecorder, traceFilename } from "../src/recorder.js";
import { statusFilename } from "../src/session-status.js";
import { inspectRun } from "../src/inspect.js";
import { apply } from "../src/index.js";

async function setup(t, options = {}) {
  const outputDir = await mkdtemp(join(tmpdir(), "dsh-eval-lab-event-"));
  const target = resolve(outputDir);
  const withinTemp = relative(resolve(tmpdir()), target);
  assert.ok(withinTemp && !withinTemp.startsWith("..") && !isAbsolute(withinTemp));
  assert.ok(basename(target).startsWith("dsh-eval-lab-"));
  const recorder = createRecorder({ outputDir, ...options });
  t.after(async () => {
    await recorder.close().catch(() => {});
    await rm(target, { recursive: true, force: true });
  });
  return recorder;
}

const encoded = (event, sessionId = "s", runId = "x".repeat(36)) =>
  JSON.stringify({ formatVersion: 1, runId, sessionId, event }) + "\n";
const tracePath = (recorder, id = "s") => join(recorder.runDir, traceFilename(id));
const readStatus = async (recorder, id = "s") => JSON.parse(await readFile(
  join(recorder.runDir, statusFilename(traceFilename(id))), "utf8"));

test("event byte limit defaults to 1 MiB and validates both configuration entry points before creating files", async (t) => {
  assert.equal(config.DEFAULT_MAX_EVENT_BYTES, 1024 * 1024);
  assert.equal(config.resolveConfig({}, { env: {} }).maxEventBytes, 1024 * 1024);
  assert.equal(config.resolveConfig({ maxEventBytes: 512 }, { env: {} }).maxEventBytes, 512);
  const recorder = await setup(t);
  for (const maxEventBytes of [0, -1, 1.5, null, "1024", false, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => config.resolveConfig({ maxEventBytes }, { env: {} }), /maxEventBytes/);
    assert.throws(() => createRecorder({ outputDir: recorder.runDir, maxEventBytes }), /maxEventBytes/);
  }
  assert.deepEqual(await readdir(recorder.runDir), ["run.json"]);
});

test("run metadata preserves the effective event and pending limits through close", async (t) => {
  for (const maxEventBytes of [undefined, 4096]) {
    const recorder = await setup(t, { maxEventBytes, maxPendingBytes: 8192 });
    for (const phase of ["recording", "sealed"]) {
      const metadata = JSON.parse(await readFile(join(recorder.runDir, "run.json"), "utf8"));
      assert.equal(metadata.maxEventBytes, maxEventBytes ?? 1024 * 1024);
      assert.equal(metadata.maxPendingBytes, 8192);
      assert.equal(metadata.state, phase);
      assert.equal(metadata.formatVersion, 2);
      if (phase === "recording") {
        assert.equal(recorder.record("s", { seq: 0 }), true);
        await recorder.close();
      }
    }
  }
});

test("event boundary counts full UTF-8 envelope, escaped content and trailing newline exactly", async (t) => {
  const event = { seq: 0, data: '中文😀\n"\\\u0000' };
  const id = "中文😀";
  const bytes = Buffer.byteLength(encoded(event, id));
  assert.ok(bytes > encoded(event, id).length);
  const exact = await setup(t, { maxEventBytes: bytes });
  assert.equal(exact.record(id, event), true);
  await exact.close();
  assert.equal(await readFile(tracePath(exact, id), "utf8"), encoded(event, id, exact.runId));
  assert.equal((await inspectRun(exact.runDir)).exitCode, 0);

  const smaller = await setup(t, { maxEventBytes: bytes - 1 });
  assert.equal(smaller.record(id, event), false);
  await assert.rejects(smaller.close(), AggregateError);
  assert.equal((await readStatus(smaller, id)).error.code, "EVENT_BYTES_LIMIT");
  await assert.rejects(readFile(tracePath(smaller, id)), { code: "ENOENT" });
  assert.equal((await inspectRun(smaller.runDir)).exitCode, 1);
});

test("oversize rejection preserves written evidence, reports once and seals healthy sessions", async (t) => {
  const errors = [];
  const recorder = await setup(t, { maxEventBytes: 256, onError: (error, id) => {
    errors.push({ error, id });
    throw new Error("reporter failure");
  } });
  assert.equal(recorder.record("s", { seq: 0, data: "prefix" }), true);
  await recorder.flush("s");
  const before = await readFile(tracePath(recorder));
  assert.equal(recorder.record("s", { seq: 1, data: "x".repeat(256) }), false);
  assert.equal(recorder.record("s", { seq: 2 }), false);
  assert.equal(recorder.record("good", { seq: 0, data: "healthy" }), true);
  await assert.rejects(recorder.flush("s"), AggregateError);
  await recorder.flush("good");
  await assert.rejects(recorder.close(), AggregateError);
  assert.deepEqual(await readFile(tracePath(recorder)), before);
  assert.equal(errors.length, 1);
  assert.equal(errors[0].id, "s");
  assert.equal(errors[0].error.code, "EVENT_BYTES_LIMIT");
  assert.match(errors[0].error.message, /maxEventBytes=256/);
  const failed = await readStatus(recorder);
  assert.deepEqual([failed.receivedCount, failed.acceptedCount, failed.writtenCount], [2, 1, 1]);
  assert.equal(failed.state, "failed");
  assert.equal((await readStatus(recorder, "good")).state, "sealed");
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 1);
});

test("skipped queued events release pending capacity after an event limit failure", async (t) => {
  const event = { seq: 0 };
  const bytes = Buffer.byteLength(encoded(event));
  const recorder = await setup(t, { maxEventBytes: bytes, maxPendingBytes: bytes });
  assert.equal(recorder.record("s", event), true);
  assert.equal(recorder.record("s", { seq: 1, data: "too large" }), false);
  await assert.rejects(recorder.flush("s"), AggregateError);
  assert.equal((await readStatus(recorder)).writtenCount, 0);
  assert.equal(recorder.record("t", event), true);
  await recorder.flush("t");
  await assert.rejects(recorder.close(), AggregateError);
  assert.equal((await readStatus(recorder, "t")).writtenCount, 1);
});

test("event and recorder-wide pending limits are independent with event rejection taking precedence", async (t) => {
  for (const [maxEventBytes, maxPendingBytes, code] of [
    [128, 4096, "EVENT_BYTES_LIMIT"], [4096, 128, "PENDING_BYTES_LIMIT"], [128, 128, "EVENT_BYTES_LIMIT"],
  ]) {
    const recorder = await setup(t, { maxEventBytes, maxPendingBytes });
    assert.equal(recorder.record("s", { seq: 0, data: "x".repeat(256) }), false);
    await assert.rejects(recorder.close(), AggregateError);
    assert.equal((await readStatus(recorder)).error.code, code);
  }
});

test("limit applies to the frozen toJSON result and a larger explicit limit permits full evidence", async (t) => {
  const recorder = await setup(t, { maxEventBytes: 256 });
  let calls = 0;
  const observed = { seq: 0, data: "original" };
  assert.equal(recorder.record("small", { data: "x".repeat(2048), toJSON() { calls++; return observed; } }), true);
  observed.data = "changed";
  assert.equal(recorder.record("large", { seq: 0, toJSON() { calls++; return { seq: 0, data: "x".repeat(256) }; } }), false);
  assert.equal(calls, 2);
  await assert.rejects(recorder.close(), AggregateError);
  assert.equal(JSON.parse(await readFile(tracePath(recorder, "small"), "utf8")).event.data, "original");
  assert.equal((await readStatus(recorder, "large")).error.code, "EVENT_BYTES_LIMIT");

  const event = { seq: 0, data: "x".repeat(1024 * 1024) };
  const defaultLimit = await setup(t);
  assert.equal(defaultLimit.record("s", event), false);
  const raised = await setup(t, { maxEventBytes: 2 * 1024 * 1024 });
  assert.equal(raised.record("s", event), true);
  await raised.close();
  assert.equal(await readFile(tracePath(raised), "utf8"), encoded(event, "s", raised.runId));
  assert.equal((await inspectRun(raised.runDir)).exitCode, 0);
});

test("event limit is per line, not cumulative over a session", async (t) => {
  const recorder = await setup(t, { maxEventBytes: 256, maxPendingBytes: 256 });
  for (let seq = 0; seq < 20; seq++) {
    assert.equal(recorder.record("s", { seq, data: "中文😀" }), true);
    await recorder.flush("s");
  }
  await recorder.close();
  const status = await readStatus(recorder);
  assert.equal(status.writtenCount, 20);
  assert.ok(status.writtenBytes > 256);
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 0);
});

test("event error callback can close reentrantly without losing failed membership", async (t) => {
  let closing;
  const recorder = await setup(t, { maxEventBytes: 1, onError() { closing = recorder.close(); } });
  assert.equal(recorder.record("s", { seq: 0 }), false);
  assert.strictEqual(recorder.close(), closing);
  await assert.rejects(closing, AggregateError);
  assert.equal((await readStatus(recorder)).error.code, "EVENT_BYTES_LIMIT");
  assert.equal((await inspectRun(recorder.runDir)).runManifest.state, "failed");
});

test("plugin passes explicit event limits through its event, flush and disposal hooks", async (t) => {
  const container = await setup(t);
  const outputDir = join(container.runDir, "plugin");
  const hooks = new Map();
  let dispose;
  t.mock.method(console, "error", () => {});
  apply({ on: (type, listener) => hooks.set(type, listener), effect: (setup) => { dispose = setup(); } },
    { outputDir, maxEventBytes: 1 });
  assert.equal(hooks.get("session/event")({ id: "s" }, { seq: 0 }), false);
  await assert.rejects(hooks.get("session/flush")({ id: "s" }), AggregateError);
  await assert.rejects(dispose(), AggregateError);
  const [runId] = await readdir(outputDir);
  assert.equal((await readStatus({ runDir: join(outputDir, runId) })).error.code, "EVENT_BYTES_LIMIT");
});
