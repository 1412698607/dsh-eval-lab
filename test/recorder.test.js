import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, isAbsolute, join, relative, resolve } from "node:path";
import { createRecorder, traceFilename } from "../src/recorder.js";
import { apply } from "../src/index.js";
import { pluginVersion } from "../src/metadata.js";

function cleanup(t, outputDir) {
  const target = resolve(outputDir);
  const withinTemp = relative(resolve(tmpdir()), target);
  assert.ok(withinTemp && !withinTemp.startsWith("..") && !isAbsolute(withinTemp));
  assert.ok(basename(target).startsWith("dsh-eval-lab-"));
  t.after(() => rm(target, { recursive: true, force: true }));
}

async function setup(t, onError) {
  const outputDir = await mkdtemp(join(tmpdir(), "dsh-eval-lab-"));
  cleanup(t, outputDir);
  return createRecorder({ outputDir, onError });
}

async function readTrace(recorder, id) {
  const text = await readFile(join(recorder.runDir, traceFilename(id)), "utf8");
  return text.trim().split("\n").map((line) => JSON.parse(line));
}

test("rapid interleaved events retain per-session order, payloads, and safe paths", async (t) => {
  const recorder = await setup(t);
  const id = "../../outside";
  const event = { seq: 0, type: "tool/call", data: { name: "读取文件", arguments: "line1\nline2" } };
  recorder.record(id, event);
  event.data.name = "changed after recording";
  for (let seq = 1; seq < 40; seq++) {
    recorder.record("other", { seq, type: "tool/result", data: { seq } });
    recorder.record(id, { seq, type: "step/end", data: { seq } });
  }
  await recorder.close();
  const rows = await readTrace(recorder, id);
  assert.equal(rows.length, 40);
  assert.deepEqual(rows.map((row) => row.event.seq), Array.from({ length: 40 }, (_, i) => i));
  assert.equal(rows[0].event.data.name, "读取文件");
  assert.equal(rows[0].event.data.arguments, "line1\nline2");
  assert.equal(rows[0].sessionId, id);
  assert.equal((await readTrace(recorder, "other")).length, 39);
  assert.match(traceFilename(id), /^[a-f0-9]{64}\.jsonl$/);
});

test("each launch has a distinct manifest and output directory", async (t) => {
  const first = await setup(t);
  const second = createRecorder({ outputDir: join(first.runDir, "..") });
  assert.notEqual(first.runId, second.runId);
  const manifest = JSON.parse(await readFile(join(first.runDir, "run.json"), "utf8"));
  assert.equal(manifest.captureScope, "live-events-only");
  assert.equal(manifest.pluginVersion, pluginVersion);
  assert.equal(manifest.runId, first.runId);
  await first.close();
  await second.close();
});

test("disk write failure invalidates only the failed session and reports once", async (t) => {
  const errors = [];
  const recorder = await setup(t, (error, id) => errors.push({ error, id }));
  await mkdir(join(recorder.runDir, traceFilename("bad")));
  recorder.record("bad", { seq: 0 });
  recorder.record("good", { seq: 0 });
  await assert.rejects(recorder.flush("bad"), AggregateError);
  assert.equal(recorder.record("bad", { seq: 1 }), false);
  await recorder.flush("good");
  assert.equal((await readTrace(recorder, "good")).length, 1);
  assert.equal(errors.length, 1);
  assert.equal(errors[0].id, "bad");
  await assert.rejects(recorder.close(), AggregateError);
});

test("serialization failure is visible even if the error reporter throws", async (t) => {
  const recorder = await setup(t, () => { throw new Error("reporter failed"); });
  assert.equal(recorder.record("bad", { value: 1n }), false);
  await assert.rejects(recorder.close(), AggregateError);
});

test("rejects a relative output path and stops accepting events after close", async (t) => {
  assert.throws(() => createRecorder({ outputDir: "runs" }), /绝对路径/);
  const recorder = await setup(t);
  await recorder.close();
  assert.throws(() => recorder.record("late", { seq: 0 }), /已关闭/);
});

test("plugin event, checkpoint, and disposal hooks persist a trace", async (t) => {
  const outputDir = await mkdtemp(join(tmpdir(), "dsh-eval-lab-hooks-"));
  cleanup(t, outputDir);
  const hooks = new Map();
  apply({ on: (type, listener) => hooks.set(type, listener) }, { outputDir });
  const session = { id: "hook-session" };
  hooks.get("session/event")(session, { seq: 0, type: "turn/start", data: { turn: 1 } });
  await hooks.get("session/flush")(session);
  await hooks.get("dispose")();
  const { readdir } = await import("node:fs/promises");
  const [runId] = await readdir(outputDir);
  const rows = await readTrace({ runDir: join(outputDir, runId) }, session.id);
  assert.equal(rows[0].event.type, "turn/start");
});
