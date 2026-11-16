import test from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, writeFile, rm, mkdir, copyFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { monitorEventLoopDelay, performance } from "node:perf_hooks";
import { setTimeout as delay } from "node:timers/promises";
import { promisify } from "node:util";
import { armDelayMonitor, artifactEvidence, delaySummary, latencySummary, parseOptions, sourceProvenance } from "../scripts/recorder-measurement.js";
import { createRecorder } from "../src/recorder.js";
import { inspectRun } from "../src/inspect.js";

async function temporary(t) {
  const directory = await mkdtemp(join(tmpdir(), "dsh-eval-lab-measure-"));
  const child = relative(resolve(tmpdir()), resolve(directory));
  assert.ok(child && !child.startsWith("..") && !isAbsolute(child));
  assert.ok(basename(directory).startsWith("dsh-eval-lab-measure-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

test("measurement options keep default workloads and reject ambiguous selection", () => {
  const names = ["long-text", "slow-overflow", "sustained"];
  const parse = (args) => parseOptions(args, names, "/recorder", "/inspect");
  assert.deepEqual(parse([]).scenarios, ["long-text", "slow-overflow"]);
  assert.deepEqual(parse(["--scenarios", "sustained,long-text", "--repeats", "2"]).scenarios, ["sustained", "long-text"]);
  for (const args of [["--scenarios", "long-text,long-text"], ["--scenarios", "unknown"], ["--repeats", "0"],
    ["--repeats", "11"], ["--output-dir"], ["--repeats", "1", "--repeats", "2"], ["--unknown", "value"]]) {
    assert.throws(() => parse(args));
  }
});

test("empty event-loop histogram and latency have null estimates", () => {
  const histogram = monitorEventLoopDelay({ resolution: 10 });
  const result = delaySummary(histogram);
  assert.equal(result.count, 0);
  for (const key of ["minMs", "maxMs", "meanMs", "stddevMs", "p50Ms", "p95Ms", "p99Ms"]) assert.equal(result[key], null);
  assert.deepEqual(latencySummary([]), { count: 0, totalMs: 0, minMs: null, maxMs: null, p50Ms: null, p95Ms: null, p99Ms: null });
});

test("armed event-loop histogram observes a synchronous stall before tail shutdown", async () => {
  const { histogram, arm } = await armDelayMonitor();
  try {
    assert.ok(arm.samples > 0);
    const start = performance.now();
    while (performance.now() - start < 60) { /* Deliberately block the real event loop. */ }
    await delay(20);
    const result = delaySummary(histogram);
    assert.ok(result.count > arm.samples);
    assert.ok(result.maxMs >= 50, `synchronous 60 ms stall was not observed: ${result.maxMs}`);
  } finally { histogram.disable(); }
});

test("source provenance includes recorder dependencies and package metadata", async (t) => {
  const directory = await temporary(t);
  const source = join(directory, "src");
  await mkdir(source);
  for (const file of ["recorder.js", "config.js", "metadata.js", "session-status.js", "inspect.js"]) {
    await copyFile(fileURLToPath(new URL(`../src/${file}`, import.meta.url)), join(source, file));
  }
  const packagePath = join(directory, "package.json");
  await copyFile(fileURLToPath(new URL("../package.json", import.meta.url)), packagePath);
  const capture = () => sourceProvenance(join(source, "recorder.js"), join(source, "inspect.js"),
    fileURLToPath(new URL("../scripts/measure-recorder.js", import.meta.url)));
  const before = await capture();
  await writeFile(packagePath, (await readFile(packagePath, "utf8")) + "\n");
  const after = await capture();
  assert.notEqual(after.recorder.sha256, before.recorder.sha256);
  assert.notEqual(after.inspector.sha256, before.inspector.sha256);
  assert.equal(after.measurement.sha256, before.measurement.sha256);
});

async function evidence(directory, event) {
  const recorder = createRecorder({ outputDir: directory });
  recorder.record("sample", event);
  await recorder.close();
  const metadata = JSON.parse(await readFile(join(recorder.runDir, "run.json"), "utf8"));
  const inspection = await inspectRun(recorder.runDir);
  return { recorder, metadata, inspection,
    artifacts: await artifactEvidence(recorder.runDir, metadata, inspection, () => {}) };
}

test("normalized evidence ignores run identity but preserves event body and raw hashes", async (t) => {
  const directory = await temporary(t);
  const first = await evidence(directory, { seq: 0, data: { runId: "payload-value", updatedAt: "payload-time" } });
  const second = await evidence(directory, { seq: 0, data: { runId: "payload-value", updatedAt: "payload-time" } });
  const changed = await evidence(directory, { seq: 0, data: { runId: "changed-value", updatedAt: "payload-time" } });
  assert.equal(first.artifacts.normalizedFilesSha256, second.artifacts.normalizedFilesSha256);
  assert.equal(first.artifacts.normalizedInspectionSha256, second.artifacts.normalizedInspectionSha256);
  assert.notEqual(first.artifacts.files.find((file) => file.file.endsWith(".jsonl")).sha256,
    second.artifacts.files.find((file) => file.file.endsWith(".jsonl")).sha256);
  assert.notEqual(first.artifacts.normalizedFilesSha256, changed.artifacts.normalizedFilesSha256);
});

test("normalization rejects a false status digest instead of hiding it", async (t) => {
  const result = await evidence(await temporary(t), { seq: 0, data: "payload" });
  const statusPath = join(result.recorder.runDir, result.metadata.sessions[0].statusFile);
  const status = JSON.parse(await readFile(statusPath, "utf8"));
  status.sha256 = "0".repeat(64);
  await writeFile(statusPath, JSON.stringify(status));
  await assert.rejects(artifactEvidence(result.recorder.runDir, result.metadata, result.inspection, () => {}),
    /status must match actual trace digest/);
});

test("normalization rejects noncanonical JSONL instead of hiding changed bytes", async (t) => {
  const result = await evidence(await temporary(t), { seq: 0, data: "payload" });
  const tracePath = join(result.recorder.runDir, result.metadata.sessions[0].traceFile);
  const original = await readFile(tracePath, "utf8");
  await writeFile(tracePath, original.replace('"formatVersion":1', '"formatVersion":1 '));
  await assert.rejects(artifactEvidence(result.recorder.runDir, result.metadata, result.inspection, () => {}),
    /canonical UTF-8 JSONL/);
});

test("normalization rejects invalid generated timestamps instead of hiding changed fields", async (t) => {
  for (const field of ["startedAt", "updatedAt"]) {
    const result = await evidence(await temporary(t), { seq: 0, data: "payload" });
    const file = field === "startedAt" ? "run.json" : result.metadata.sessions[0].statusFile;
    const path = join(result.recorder.runDir, file);
    const data = JSON.parse(await readFile(path, "utf8"));
    data[field] = "x".repeat(data[field].length);
    await writeFile(path, JSON.stringify(data, null, 2) + "\n");
    await assert.rejects(artifactEvidence(result.recorder.runDir, result.metadata, result.inspection, () => {}),
      /valid generated ISO timestamp/);
  }
});

test("failed producer closes its recorder and preserves the original worker error", async (t) => {
  for (const cleanupFails of [false, true]) await t.test(`cleanup failure: ${cleanupFails}`, async (t) => {
  const directory = await temporary(t);
  const source = join(directory, "src");
  await mkdir(source);
  for (const file of ["recorder.js", "config.js", "metadata.js", "session-status.js", "inspect.js"]) {
    await copyFile(fileURLToPath(new URL(`../src/${file}`, import.meta.url)), join(source, file));
  }
  await copyFile(fileURLToPath(new URL("../package.json", import.meta.url)), join(directory, "package.json"));
  const recorderPath = join(source, "recorder.js");
  const original = await readFile(recorderPath, "utf8");
  const fixture = `import promises from "node:fs/promises";
import sync from "node:fs";
const beforeMeasurement = [promises.appendFile, promises.writeFile, promises.rename, sync.writeFileSync];
` + original.replace("function record(sessionId, event) {", `function record(sessionId, event) {
    if (event.seq === 1) throw new Error("injected producer failure");`)
    .replace("function close() {", `function close() {
    writeFileSync(join(outputDir, "cleanup-close.txt"), "close called");
    ${cleanupFails ? 'throw new Error("injected cleanup failure");' : ""}`)
    .replace("const runId = randomUUID();", `const runId = randomUUID();
    process.on("uncaughtExceptionMonitor", () => {
      const afterMeasurement = [promises.appendFile, promises.writeFile, promises.rename, sync.writeFileSync];
      sync.writeFileSync(join(outputDir, "restored.json"), JSON.stringify(
        afterMeasurement.map((operation, index) => operation === beforeMeasurement[index])));
    });`);
  assert.notEqual(fixture, original);
  await writeFile(recorderPath, fixture);
  const output = join(directory, "failed-worker");
  await assert.rejects(promisify(execFile)(process.execPath, ["--expose-gc",
    fileURLToPath(new URL("../scripts/measure-recorder.js", import.meta.url)), "--worker", "long-text", output,
    JSON.stringify({ recorderModule: recorderPath, inspectModule: join(source, "inspect.js") })],
  { windowsHide: true, encoding: "utf8", timeout: 10000 }), (error) => {
    assert.equal(error.code, 1);
    assert.match(error.stderr, /injected producer failure/);
    return true;
  });
  const failure = JSON.parse(await readFile(join(output, "failure.json"), "utf8"));
  assert.equal(failure.message, "injected producer failure");
  assert.equal(await readFile(join(output, "cleanup-close.txt"), "utf8"), "close called");
  assert.deepEqual(JSON.parse(await readFile(join(output, "restored.json"), "utf8")), [true, true, true, true]);
  });
});
