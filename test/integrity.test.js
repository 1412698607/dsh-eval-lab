import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile, appendFile, mkdir, readdir, rm, unlink } from "node:fs/promises";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { basename, isAbsolute, join, relative, resolve } from "node:path";
import { createRecorder, traceFilename } from "../src/recorder.js";
import { statusFilename } from "../src/session-status.js";
import { inspectRun } from "../src/inspect.js";
import { main } from "../scripts/inspect.js";

async function setup(t, options = {}) {
  const outputDir = await mkdtemp(join(tmpdir(), "dsh-eval-lab-integrity-"));
  const target = resolve(outputDir);
  const withinTemp = relative(resolve(tmpdir()), target);
  assert.ok(withinTemp && !withinTemp.startsWith("..") && !isAbsolute(withinTemp));
  assert.ok(basename(target).startsWith("dsh-eval-lab-"));
  t.after(() => rm(target, { recursive: true, force: true }));
  return createRecorder({ outputDir, ...options });
}

const tracePath = (recorder, id = "s") => join(recorder.runDir, traceFilename(id));
const statusPath = (recorder, id = "s") => join(recorder.runDir, statusFilename(traceFilename(id)));
const readStatus = async (recorder, id) => JSON.parse(await readFile(statusPath(recorder, id), "utf8"));

async function sealed(t) {
  const recorder = await setup(t);
  recorder.record("s", { seq: 3, type: "future/event", data: "中文😀" });
  recorder.record("s", { seq: 5, type: "turn/end" });
  await recorder.close();
  return recorder;
}

test("sealed content has exact byte digest, identities, counts and sequence gaps", async (t) => {
  const recorder = await sealed(t);
  const bytes = await readFile(tracePath(recorder));
  const status = await readStatus(recorder);
  assert.equal(status.state, "sealed");
  assert.equal(status.receivedCount, 2);
  assert.equal(status.acceptedCount, 2);
  assert.equal(status.writtenCount, 2);
  assert.equal(status.writtenBytes, bytes.length);
  assert.equal(status.sha256, createHash("sha256").update(bytes).digest("hex"));
  const report = await inspectRun(recorder.runDir);
  assert.equal(report.exitCode, 0);
  assert.equal(report.outcome, "complete");
  assert.equal(report.sessions[0].firstSeq, 3);
  assert.equal(report.sessions[0].lastSeq, 5);
  assert.deepEqual(report.sessions[0].gaps, [{ after: 3, before: 5 }]);
  assert.equal((await readdir(recorder.runDir)).some((file) => file.endsWith(".tmp")), false);
});

test("flush saves only its checkpoint; later appends remain open until close", async (t) => {
  const recorder = await setup(t);
  recorder.record("s", { seq: 0 });
  const checkpoint = recorder.flush("s");
  recorder.record("s", { seq: 1 });
  await checkpoint;
  const status = await readStatus(recorder);
  assert.equal(status.state, "recording");
  assert.equal(status.writtenCount, 1);
  assert.equal(status.acceptedCount, 1);
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 2);
  await recorder.flush("s");
  assert.equal((await readStatus(recorder)).writtenCount, 2);
  const closing = recorder.close();
  assert.strictEqual(recorder.close(), closing);
  const flushing = recorder.flush("s");
  assert.throws(() => recorder.record("s", { seq: 2 }), /已关闭/);
  await Promise.all([closing, flushing]);
  assert.equal((await readStatus(recorder)).state, "sealed");
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 0);
});

test("close drains queued checkpoints and events for every session", async (t) => {
  const recorder = await setup(t);
  recorder.record("s", { seq: 0 });
  const first = recorder.flush();
  recorder.record("s", { seq: 1 });
  recorder.record("other", { seq: 9 });
  const second = recorder.flush();
  await Promise.all([first, second, recorder.close()]);
  const report = await inspectRun(recorder.runDir);
  assert.equal(report.exitCode, 0);
  assert.equal(report.sessions.length, 2);
  assert.equal((await readStatus(recorder)).writtenCount, 2);
});

test("UTF-8 capacity applies across sessions and is released after successful writes", async (t) => {
  const recorder = await setup(t, { maxPendingBytes: 1 });
  assert.equal(recorder.record("s", { seq: 0 }), false);
  await assert.rejects(recorder.close(), AggregateError);
  assert.equal((await readStatus(recorder)).error.code, "PENDING_BYTES_LIMIT");
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 1);

  // UUIDs always have the same length, so a reference envelope gives the exact limit.
  const event = { seq: 0, data: "中文😀" };
  const bytes = Buffer.byteLength(JSON.stringify({ formatVersion: 1, runId: recorder.runId, sessionId: "a", event }) + "\n");
  const errors = [];
  const bounded = await setup(t, { maxPendingBytes: bytes, onError: (error, id) => errors.push(id) });
  assert.equal(bounded.record("a", event), true);
  assert.equal(bounded.record("b", event), false);
  await bounded.flush("a");
  assert.equal(bounded.record("c", event), true);
  await bounded.flush("c");
  await assert.rejects(bounded.close(), AggregateError);
  assert.deepEqual(errors, ["b"]);
  assert.equal((await readStatus(bounded, "a")).state, "sealed");
  assert.equal((await readStatus(bounded, "c")).state, "sealed");

  const tooSmall = await setup(t, { maxPendingBytes: bytes - 1 });
  assert.equal(tooSmall.record("a", event), false);
  await assert.rejects(tooSmall.close(), AggregateError);
  assert.throws(() => createRecorder({ outputDir: recorder.runDir, maxPendingBytes: 0 }), /maxPendingBytes/);
});

test("skipped queued buffers release capacity after the affected session fails", async (t) => {
  const event = { seq: 0 };
  const size = Buffer.byteLength(JSON.stringify({ formatVersion: 1, runId: "x".repeat(36), sessionId: "s", event }) + "\n");
  const recorder = await setup(t, { maxPendingBytes: size });
  assert.equal(recorder.record("s", event), true);
  assert.equal(recorder.record("s", { seq: 1 }), false);
  await assert.rejects(recorder.flush("s"), AggregateError);
  assert.equal(recorder.record("t", event), true);
  await recorder.flush("t");
  await assert.rejects(recorder.close(), AggregateError);
  assert.equal((await readStatus(recorder, "s")).writtenCount, 0);
  assert.equal((await readStatus(recorder, "t")).state, "sealed");
});

test("real append failure persists failed status and still seals healthy sessions", async (t) => {
  const recorder = await setup(t);
  await mkdir(tracePath(recorder));
  recorder.record("s", { seq: 0 });
  recorder.record("good", { seq: 0 });
  await assert.rejects(recorder.close(), AggregateError);
  assert.equal((await readStatus(recorder)).state, "failed");
  assert.equal((await readStatus(recorder, "good")).state, "sealed");
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 1);
});

test("initial status replacement failure prevents writing any trace", async (t) => {
  const recorder = await setup(t);
  await mkdir(statusPath(recorder));
  recorder.record("s", { seq: 0 });
  await assert.rejects(recorder.close(), AggregateError);
  await assert.rejects(readFile(tracePath(recorder)), { code: "ENOENT" });
  assert.notEqual((await inspectRun(recorder.runDir)).exitCode, 0);
});

test("checkpoint and seal status failures cannot leave an acceptable sealed trace", async (t) => {
  for (const phase of ["flush", "close"]) {
    const recorder = await setup(t);
    recorder.record("s", { seq: 0 });
    await recorder.flush();
    await unlink(statusPath(recorder));
    await mkdir(statusPath(recorder));
    await assert.rejects(recorder[phase](), AggregateError);
    if (phase === "flush") await assert.rejects(recorder.close(), AggregateError);
    assert.notEqual((await inspectRun(recorder.runDir)).exitCode, 0);
  }
});

test("serialization and invalid sequence failures are persistent and report once", async (t) => {
  for (const event of [{ seq: 0, value: 1n }, {}, { seq: -1 }, { seq: 1.5 }, { seq: Number.MAX_SAFE_INTEGER + 1 }]) {
    const errors = [];
    const recorder = await setup(t, { onError: (error) => { errors.push(error); throw new Error("reporter"); } });
    assert.equal(recorder.record("s", event), false);
    assert.equal(recorder.record("s", { seq: 1 }), false);
    await assert.rejects(recorder.close(), AggregateError);
    assert.equal(errors.length, 1);
    assert.equal((await readStatus(recorder)).state, "failed");
    assert.equal((await inspectRun(recorder.runDir)).exitCode, 1);
  }
  const recorder = await setup(t);
  recorder.record("s", { seq: 1 });
  await recorder.flush();
  assert.equal(recorder.record("s", { seq: 1 }), false);
  await assert.rejects(recorder.close(), AggregateError);
});

test("corrupt, truncated, empty, altered and extra sealed content is invalid", async (t) => {
  const changes = [
    (bytes) => bytes.subarray(0, bytes.length - 1),
    () => Buffer.from("{\"broken\":\n"),
    () => Buffer.alloc(0),
    (bytes) => Buffer.from(bytes.toString("utf8").replace("future/event", "changed/event")),
    (bytes) => Buffer.concat([bytes, bytes.subarray(0, bytes.indexOf(10) + 1)]),
    (bytes) => Buffer.concat([Buffer.from([0xff]), bytes]),
  ];
  for (const change of changes) {
    const recorder = await sealed(t);
    await writeFile(tracePath(recorder), change(await readFile(tracePath(recorder))));
    assert.equal((await inspectRun(recorder.runDir)).exitCode, 1);
  }
});

test("status counts, sequence bounds, digest, identity and format are checked", async (t) => {
  for (const patch of [
    { writtenCount: 99 }, { receivedCount: 3 }, { writtenBytes: 1 }, { sha256: "0".repeat(64) },
    { firstSeq: 0 }, { lastSeq: 6 }, { runId: "wrong" }, { sessionId: "wrong" },
    { traceFile: "../outside.jsonl" }, { state: "unknown" }, { error: { message: "failed" } },
  ]) {
    const recorder = await sealed(t);
    await writeFile(statusPath(recorder), JSON.stringify({ ...await readStatus(recorder), ...patch }));
    assert.equal((await inspectRun(recorder.runDir)).exitCode, 1, JSON.stringify(patch));
  }
  const recorder = await sealed(t);
  await writeFile(statusPath(recorder), "{invalid");
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 1);
});

test("legacy, missing, open, empty runs and unsupported status versions stay unverified", async (t) => {
  const recorder = await sealed(t);
  const manifestPath = join(recorder.runDir, "run.json");
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  // Old runs have no expected membership; missing status retains its old classification.
  delete manifest.runManifestFormatVersion;
  delete manifest.state;
  delete manifest.sessions;
  manifest.formatVersion = 1;
  await writeFile(manifestPath, JSON.stringify(manifest));
  await unlink(statusPath(recorder));
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 2);
  delete manifest.statusFormatVersion;
  await writeFile(manifestPath, JSON.stringify(manifest));
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 2);
  await unlink(manifestPath);
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 2);
  const empty = await setup(t);
  await empty.close();
  assert.equal((await inspectRun(empty.runDir)).exitCode, 2);
  const future = await sealed(t);
  await writeFile(statusPath(future), JSON.stringify({ ...await readStatus(future), statusFormatVersion: 999 }));
  assert.equal((await inspectRun(future.runDir)).exitCode, 2);
  assert.equal((await inspectRun(join(empty.runDir, "missing"))).exitCode, 2);
});

test("missing sealed trace, invalid manifest and structurally invalid rows are rejected", async (t) => {
  const missing = await sealed(t);
  await unlink(tracePath(missing));
  assert.equal((await inspectRun(missing.runDir)).exitCode, 1);
  const manifest = await sealed(t);
  await writeFile(join(manifest.runDir, "run.json"), "null");
  assert.equal((await inspectRun(manifest.runDir)).exitCode, 1);
  for (const patch of [{ formatVersion: 2 }, { runId: "other" }, { sessionId: "other" }, { event: { seq: 2 } }]) {
    const recorder = await sealed(t);
    const rows = (await readFile(tracePath(recorder), "utf8")).trim().split("\n").map(JSON.parse);
    Object.assign(rows[1], patch);
    await writeFile(tracePath(recorder), rows.map((row) => JSON.stringify(row) + "\n").join(""));
    // Remove status to ensure detection comes from row validation, not the final digest.
    await unlink(statusPath(recorder));
    assert.equal((await inspectRun(recorder.runDir)).exitCode, 1);
  }
});

test("an open checkpoint validates its prefix without rejecting later complete appends", async (t) => {
  const recorder = await setup(t);
  recorder.record("s", { seq: 0 });
  await recorder.flush();
  recorder.record("s", { seq: 1 });
  // Another flush provides an I/O barrier; restore the earlier checkpoint for inspection.
  const checkpoint = await readFile(statusPath(recorder));
  await recorder.flush();
  await writeFile(statusPath(recorder), checkpoint);
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 2);
  const bytes = await readFile(tracePath(recorder));
  await writeFile(tracePath(recorder), bytes.toString("utf8").replace('"seq":0', '"seq":9'));
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 1);
  await recorder.close();
});

test("inspect command requires an explicit run and returns the report exit code", async (t) => {
  const recorder = await sealed(t);
  const output = { log() {}, error() {} };
  for (const args of [[], ["--run"], ["--run", recorder.runDir, "extra"], ["--latest"]]) {
    assert.equal(await main(args, output), 2);
  }
  assert.equal(await main(["--run", recorder.runDir], output), 0);
  await appendFile(tracePath(recorder), "oops\n");
  assert.equal(await main(["--run", recorder.runDir], output), 1);
});

test("stream inspection handles multi-chunk UTF-8 lines and bounds gap detail", async (t) => {
  const recorder = await setup(t);
  recorder.record("s", { seq: 0, data: "中文😀".repeat(20000) });
  for (let seq = 2; seq <= 204; seq += 2) recorder.record("s", { seq });
  await recorder.close();
  const report = await inspectRun(recorder.runDir);
  assert.equal(report.exitCode, 0);
  assert.equal(report.sessions[0].writtenCount, 103);
  assert.equal(report.sessions[0].gapCount, 102);
  assert.equal(report.sessions[0].gaps.length, 100);
});

test("malformed status UTF-8 and interrupted replacement files never pass", async (t) => {
  const recorder = await sealed(t);
  await writeFile(statusPath(recorder), Buffer.from([0xff]));
  assert.equal((await inspectRun(recorder.runDir)).exitCode, 1);
  const temporary = await sealed(t);
  await writeFile(join(temporary.runDir, "unfinished.tmp"), "{}");
  assert.equal((await inspectRun(temporary.runDir)).exitCode, 2);
});
