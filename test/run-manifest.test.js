import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile, readdir, mkdir, rm, unlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, isAbsolute, join, relative, resolve } from "node:path";
import { createRecorder, traceFilename } from "../src/recorder.js";
import { statusFilename } from "../src/session-status.js";
import { inspectRun } from "../src/inspect.js";

async function setup(t, options = {}) {
  const outputDir = await mkdtemp(join(tmpdir(), "dsh-eval-lab-manifest-"));
  const target = resolve(outputDir);
  const withinTemp = relative(resolve(tmpdir()), target);
  assert.ok(withinTemp && !withinTemp.startsWith("..") && !isAbsolute(withinTemp));
  assert.ok(basename(target).startsWith("dsh-eval-lab-manifest-"));
  t.after(() => rm(target, { recursive: true, force: true }));
  return createRecorder({ outputDir, ...options });
}

const metadataPath = (recorder) => join(recorder.runDir, "run.json");
const metadata = async (recorder) => JSON.parse(await readFile(metadataPath(recorder), "utf8"));
const pair = (id) => ({ sessionId: id, traceFile: traceFilename(id), statusFile: statusFilename(traceFilename(id)) });
const save = (recorder, value) => writeFile(metadataPath(recorder), JSON.stringify(value));
async function removePair(recorder, id) {
  const entry = pair(id);
  await unlink(join(recorder.runDir, entry.traceFile));
  await unlink(join(recorder.runDir, entry.statusFile));
}
async function sealed(t) {
  const recorder = await setup(t);
  recorder.record("first", { seq: 0 });
  recorder.record("second", { seq: 5 });
  await recorder.close();
  return recorder;
}

test("run metadata inventories observed sessions and seals after all session queues", async (t) => {
  const recorder = await setup(t);
  const initial = await metadata(recorder);
  assert.equal(initial.formatVersion, 2);
  assert.equal(initial.runManifestFormatVersion, 1);
  assert.equal(initial.state, "recording");
  assert.deepEqual(initial.sessions, []);
  recorder.record("../../中文", { seq: 0 });
  recorder.record("other", { seq: 7 });
  await recorder.flush("../../中文");
  assert.equal((await metadata(recorder)).state, "recording");
  const closing = recorder.close();
  assert.strictEqual(recorder.close(), closing);
  await Promise.all([closing, recorder.flush()]);
  const final = await metadata(recorder);
  assert.equal(final.state, "sealed");
  assert.deepEqual(final.sessions, [pair("../../中文"), pair("other")]);
  const report = await inspectRun(recorder.runDir);
  assert.equal(report.exitCode, 0);
  assert.equal(report.runManifest.outcome, "complete");
  assert.equal(report.runManifest.expectedSessionCount, 2);
});

test("deleting an entire session pair cannot leave the remaining session complete at run level", async (t) => {
  const recorder = await sealed(t);
  await removePair(recorder, "second");
  const report = await inspectRun(recorder.runDir);
  assert.equal(report.exitCode, 1);
  assert.equal(report.runManifest.outcome, "invalid");
  assert.equal(report.sessions.length, 2);
  assert.equal(report.sessions.find((item) => item.sessionId === "first").outcome, "complete");
  assert.equal(report.sessions.find((item) => item.sessionId === "second").outcome, "invalid");
});

test("deleting every listed pair is invalid rather than an apparently empty run", async (t) => {
  const recorder = await sealed(t);
  await removePair(recorder, "first");
  await removePair(recorder, "second");
  const report = await inspectRun(recorder.runDir);
  assert.equal(report.exitCode, 1);
  assert.equal(report.sessions.length, 2);
  assert.ok(report.sessions.every((item) => item.outcome === "invalid"));
});

test("a sealed inventory requires both files for every listed session", async (t) => {
  for (const key of ["traceFile", "statusFile"]) {
    const recorder = await sealed(t);
    await unlink(join(recorder.runDir, pair("first")[key]));
    const report = await inspectRun(recorder.runDir);
    assert.equal(report.exitCode, 1, key);
    assert.equal(report.runManifest.outcome, "invalid", key);
  }
});

test("sealed session statuses do not seal an open or failed run inventory", async (t) => {
  const recorder = await sealed(t);
  const manifest = await metadata(recorder);
  await save(recorder, { ...manifest, state: "recording" });
  const open = await inspectRun(recorder.runDir);
  assert.equal(open.exitCode, 2);
  assert.equal(open.runManifest.outcome, "unverified");
  assert.ok(open.sessions.every((item) => item.outcome === "complete"));
  await save(recorder, { ...manifest, state: "failed" });
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 1);
});

test("open registration can precede session files without claiming definite corruption", async (t) => {
  const recorder = await setup(t);
  recorder.record("first", { seq: 0 });
  await recorder.flush();
  await removePair(recorder, "first");
  const report = await inspectRun(recorder.runDir);
  assert.equal(report.exitCode, 2);
  assert.equal(report.runManifest.outcome, "unverified");
  assert.equal(report.sessions.length, 1);
  assert.equal(report.sessions[0].sessionId, "first");
  await recorder.close();
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 1);
});

test("failed inventory registration writes no session files and rejects subsequent checkpoints", async (t) => {
  const errors = [];
  const recorder = await setup(t, { onError: (error, id) => { errors.push({ error, id }); throw new Error("reporter"); } });
  await unlink(metadataPath(recorder));
  await mkdir(metadataPath(recorder));
  assert.equal(recorder.record("first", { seq: 0 }), true); // queued, not persisted
  await assert.rejects(recorder.flush(), AggregateError);
  assert.equal(recorder.record("second", { seq: 0 }), false);
  await assert.rejects(recorder.close(), AggregateError);
  assert.deepEqual(await readdir(recorder.runDir), ["run.json"]);
  assert.equal(errors.length, 1);
  assert.equal(errors[0].id, null);
});

test("failure to finalize the run rejects close even when individual sessions sealed", async (t) => {
  const recorder = await setup(t);
  recorder.record("first", { seq: 0 });
  await recorder.flush();
  await unlink(metadataPath(recorder));
  await mkdir(metadataPath(recorder));
  const closing = recorder.close();
  assert.strictEqual(recorder.close(), closing);
  await assert.rejects(closing, AggregateError);
  const status = JSON.parse(await readFile(join(recorder.runDir, pair("first").statusFile), "utf8"));
  assert.equal(status.state, "sealed");
  assert.notEqual((await inspectRun(recorder.runDir)).exitCode, 0);
});

test("a session write failure finalizes the run as failed and still seals healthy sessions", async (t) => {
  const recorder = await setup(t);
  await mkdir(join(recorder.runDir, pair("bad").traceFile));
  recorder.record("bad", { seq: 0 });
  recorder.record("good", { seq: 0 });
  await assert.rejects(recorder.close(), AggregateError);
  assert.equal((await metadata(recorder)).state, "failed");
  assert.deepEqual((await metadata(recorder)).sessions, [pair("bad"), pair("good")]);
  const status = JSON.parse(await readFile(join(recorder.runDir, pair("good").statusFile), "utf8"));
  assert.equal(status.state, "sealed");
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 1);
});

test("reentrant serialization cannot omit another newly observed session", async (t) => {
  const recorder = await setup(t);
  recorder.record("first", { toJSON() { recorder.record("second", { seq: 0 }); return { seq: 0 }; } });
  await recorder.close();
  assert.deepEqual((await metadata(recorder)).sessions, [pair("first"), pair("second")]);
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 0);
});

test("unexpected session files are rejected even when their original statuses are valid", async (t) => {
  const recorder = await sealed(t);
  const manifest = await metadata(recorder);
  manifest.sessions = [pair("first")];
  await save(recorder, manifest);
  const report = await inspectRun(recorder.runDir);
  assert.equal(report.exitCode, 1);
  assert.equal(report.runManifest.outcome, "invalid");
});

test("invalid inventory identities versions and states cannot silently fall back to legacy", async (t) => {
  const changes = [
    { sessions: null }, { sessions: [pair("first"), pair("first")] },
    { sessions: [{ ...pair("first"), sessionId: "other" }] },
    { sessions: [{ ...pair("first"), traceFile: "../outside.jsonl" }] },
    { sessions: [{ ...pair("first"), statusFile: "../outside.json" }] },
    { state: "unknown" }, { runManifestFormatVersion: true }, { state: undefined },
    { runManifestFormatVersion: undefined }, { formatVersion: 1 },
    { runManifestFormatVersion: undefined, state: undefined, sessions: undefined },
  ];
  for (const change of changes) {
    const recorder = await sealed(t);
    await save(recorder, { ...await metadata(recorder), ...change });
    assert.equal((await inspectRun(recorder.runDir)).exitCode, 1, JSON.stringify(change));
  }
  const future = await sealed(t);
  await save(future, { ...await metadata(future), runManifestFormatVersion: 2 });
  const report = await inspectRun(future.runDir);
  assert.equal(report.exitCode, 2);
  assert.equal(report.runManifest.outcome, "unverified");
});

test("legacy sealed fragments keep their result but explicitly lack run coverage and remain unchanged", async (t) => {
  const recorder = await sealed(t);
  const manifest = await metadata(recorder);
  delete manifest.runManifestFormatVersion;
  delete manifest.state;
  delete manifest.sessions;
  manifest.formatVersion = 1;
  await save(recorder, manifest);
  const before = await Promise.all((await readdir(recorder.runDir)).map(async (file) => [file, await readFile(join(recorder.runDir, file))]));
  const report = await inspectRun(recorder.runDir);
  assert.equal(report.exitCode, 0);
  assert.equal(report.runManifest.outcome, "unverified");
  assert.equal(report.runManifest.expectedSessionCount, null);
  assert.ok(report.runManifest.reasons.length);
  for (const [file, bytes] of before) assert.deepEqual(await readFile(join(recorder.runDir, file)), bytes);
  await removePair(recorder, "second");
  const limited = await inspectRun(recorder.runDir);
  assert.equal(limited.exitCode, 0);
  assert.equal(limited.sessions.length, 1);
  assert.equal(limited.runManifest.outcome, "unverified");
});

test("initial and sealed empty inventories retain the no-fragments classification", async (t) => {
  const recorder = await setup(t);
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 2);
  await recorder.close();
  const report = await inspectRun(recorder.runDir);
  assert.equal(report.exitCode, 2);
  assert.equal(report.runManifest.outcome, "complete");
  assert.equal(report.runManifest.expectedSessionCount, 0);
});
