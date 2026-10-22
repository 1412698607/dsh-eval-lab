import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { syncBuiltinESMExports } from "node:module";
import { tmpdir } from "node:os";
import { basename, isAbsolute, join, relative, resolve } from "node:path";
import { createRecorder, traceFilename } from "../src/recorder.js";
import { writeStatus } from "../src/session-status.js";
import { inspectRun } from "../src/inspect.js";

async function setup(t) {
  const outputDir = await fs.mkdtemp(join(tmpdir(), "dsh-eval-lab-queue-"));
  const target = resolve(outputDir);
  const withinTemp = relative(resolve(tmpdir()), target);
  assert.ok(withinTemp && !withinTemp.startsWith("..") && !isAbsolute(withinTemp));
  assert.ok(basename(target).startsWith("dsh-eval-lab-queue-"));
  t.after(() => fs.rm(target, { recursive: true, force: true }));
  return outputDir;
}

function replace(t, name, implementation) {
  const original = fs[name];
  t.mock.method(fs, name, implementation(original));
  syncBuiltinESMExports();
  t.after(() => { t.mock.restoreAll(); syncBuiltinESMExports(); });
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

test("status replacement retries transient rename errors with the same temporary file", async (t) => {
  const outputDir = await setup(t);
  const target = join(outputDir, "status.json");
  await fs.writeFile(target, "old");
  const sources = [];
  replace(t, "rename", (original) => async (source, destination) => {
    sources.push(source);
    if (sources.length <= 3) {
      assert.equal(await fs.readFile(target, "utf8"), "old");
      throw Object.assign(new Error("temporary replacement failure"), { code: ["EPERM", "EACCES", "EBUSY"][sources.length - 1] });
    }
    return original(source, destination);
  });
  await writeStatus(target, { saved: true });
  assert.equal(sources.length, 4);
  assert.equal(new Set(sources).size, 1);
  assert.deepEqual(JSON.parse(await fs.readFile(target, "utf8")), { saved: true });
  assert.deepEqual(await fs.readdir(outputDir), ["status.json"]);
});

test("persistent replacement errors exhaust a finite retry budget and preserve the original error", async (t) => {
  const outputDir = await setup(t);
  const target = join(outputDir, "status.json");
  await fs.writeFile(target, "old");
  const failure = Object.assign(new Error("permanent access failure"), { code: "EPERM" });
  let attempts = 0;
  replace(t, "rename", () => async () => { attempts++; throw failure; });
  await assert.rejects(writeStatus(target, {}), (error) => error === failure);
  assert.equal(attempts, 6);
  assert.equal(await fs.readFile(target, "utf8"), "old");
  assert.deepEqual(await fs.readdir(outputDir), ["status.json"]);
});

test("unrelated rename errors and temporary file creation errors are not retried", async (t) => {
  const outputDir = await setup(t);
  const target = join(outputDir, "status.json");
  let attempts = 0;
  const failure = Object.assign(new Error("no space"), { code: "ENOSPC" });
  replace(t, "rename", () => async () => { attempts++; throw failure; });
  await assert.rejects(writeStatus(target, {}), (error) => error === failure);
  assert.equal(attempts, 1);
  let writes = 0;
  replace(t, "writeFile", () => async () => { writes++; throw Object.assign(new Error("cannot create"), { code: "EPERM" }); });
  await assert.rejects(writeStatus(target, {}), { code: "EPERM" });
  assert.equal(writes, 1);
  assert.equal(attempts, 1);
  assert.deepEqual(await fs.readdir(outputDir), []);
});

test("synchronous rejected-session bursts share one registration snapshot and preserve failed identities", async (t) => {
  const outputDir = await setup(t);
  const snapshots = [];
  replace(t, "writeFile", (original) => async (path, text, options) => {
    if (String(path).includes("run.json.")) snapshots.push(JSON.parse(text));
    return original(path, text, options);
  });
  const recorder = createRecorder({ outputDir, maxPendingBytes: 1 });
  for (let index = 0; index < 80; index++) assert.equal(recorder.record(`failed-${index}`, { seq: 0 }), false);
  await assert.rejects(recorder.close(), AggregateError);
  assert.deepEqual(snapshots.map((snapshot) => [snapshot.state, snapshot.sessions.length]), [["recording", 80], ["failed", 80]]);
  assert.deepEqual(snapshots[1].sessions.map((entry) => entry.sessionId), Array.from({ length: 80 }, (_, index) => `failed-${index}`));
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 1);
});

test("members arriving during registration share a later barrier and flush waits only its selected prefix", { timeout: 5000 }, async (t) => {
  const outputDir = await setup(t);
  const started = [deferred(), deferred()];
  const release = [deferred(), deferred()];
  t.after(() => release.forEach((item) => item.resolve()));
  const snapshots = [];
  replace(t, "rename", (original) => async (source, target) => {
    if (String(target).endsWith("run.json")) {
      const snapshot = JSON.parse(await fs.readFile(source, "utf8"));
      snapshots.push(snapshot);
      const index = snapshots.length - 1;
      if (index < 2) { started[index].resolve(); await release[index].promise; }
    }
    return original(source, target);
  });
  const recorder = createRecorder({ outputDir });
  recorder.record("first", { seq: 0 });
  const firstFlush = recorder.flush("first");
  await started[0].promise;
  recorder.record("second", { seq: 0 });
  recorder.record("third", { toJSON() { recorder.record("nested", { seq: 0 }); return { seq: 0 }; } });
  const secondFlush = recorder.flush("second");
  let secondDone = false;
  secondFlush.then(() => { secondDone = true; });
  assert.deepEqual(await fs.readdir(recorder.runDir).then((files) => files.filter((file) => !file.includes("run.json"))), []);
  release[0].resolve();
  await started[1].promise;
  await firstFlush;
  assert.equal(secondDone, false);
  assert.equal(await fs.stat(join(recorder.runDir, traceFilename("second"))).catch(() => null), null);
  const closing = recorder.close();
  assert.strictEqual(recorder.close(), closing);
  assert.strictEqual(recorder.flush(), closing);
  release[1].resolve();
  await Promise.all([secondFlush, closing]);
  assert.deepEqual(snapshots.map((snapshot) => [snapshot.state, snapshot.sessions.map((entry) => entry.sessionId)]), [
    ["recording", ["first"]], ["recording", ["first", "second", "third", "nested"]], ["sealed", ["first", "second", "third", "nested"]],
  ]);
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 0);
});

test("transient run registration recovers without reporting a permanent run error", async (t) => {
  const outputDir = await setup(t);
  let attempts = 0;
  replace(t, "rename", (original) => async (source, target) => {
    if (String(target).endsWith("run.json") && ++attempts === 1) throw Object.assign(new Error("busy"), { code: "EPERM" });
    return original(source, target);
  });
  const errors = [];
  const recorder = createRecorder({ outputDir, onError: (...args) => errors.push(args) });
  recorder.record("first", { seq: 0 });
  await recorder.flush();
  recorder.record("second", { seq: 0 });
  await recorder.close();
  assert.deepEqual(errors, []);
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 0);
});

test("exhausted later registration keeps registered sessions draining and rejects unregistered members", async (t) => {
  const outputDir = await setup(t);
  let failReplacement = false;
  let attempts = 0;
  replace(t, "rename", (original) => async (source, target) => {
    if (failReplacement && String(target).endsWith("run.json")) {
      attempts++;
      throw Object.assign(new Error("busy forever"), { code: "EBUSY" });
    }
    return original(source, target);
  });
  const errors = [];
  let recorder;
  let reentrantResult;
  let reentrantClose;
  recorder = createRecorder({ outputDir, onError: (error, id) => {
    errors.push({ error, id });
    reentrantResult = recorder.record("from-error", { seq: 0 });
    reentrantClose = recorder.close();
    reentrantClose.catch(() => {});
    throw new Error("reporter failure");
  } });
  recorder.record("healthy", { seq: 0 });
  await recorder.flush();
  failReplacement = true;
  recorder.record("unregistered", { seq: 0 });
  recorder.record("another", { seq: 0 });
  recorder.record("healthy", { seq: 1 });
  await assert.rejects(recorder.flush(), AggregateError);
  await assert.rejects(recorder.close(), AggregateError);
  assert.equal(attempts, 6);
  assert.equal(errors.length, 1);
  assert.equal(errors[0].id, null);
  assert.equal(reentrantResult, false);
  assert.strictEqual(recorder.close(), reentrantClose);
  const names = await fs.readdir(recorder.runDir);
  assert.ok(!names.includes(traceFilename("unregistered")));
  assert.ok(!names.includes(traceFilename("another")));
  assert.ok(!names.some((name) => name.endsWith(".tmp")));
  assert.equal((await fs.readFile(join(recorder.runDir, traceFilename("healthy")), "utf8")).trim().split("\n").length, 2);
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 2);
});
