import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import { syncBuiltinESMExports } from "node:module";
import { arch, platform, release } from "node:os";
import { basename, join, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { createRecorder } from "../src/recorder.js";
import { inspectRun } from "../src/inspect.js";

const MiB = 1024 * 1024;
const scenarios = {
  "long-text": { sessions: 1, eventsPerSession: 40, payloadBytes: 256 * 1024, flushEvery: 8 },
  "oversize": { sessions: 16, eventsPerSession: 1, payloadBytes: 2 * MiB, errorCode: "EVENT_BYTES_LIMIT" },
  "sessions-100": { sessions: 100, eventsPerSession: 1, payloadBytes: 128 },
  "sessions-300": { sessions: 300, eventsPerSession: 1, payloadBytes: 128 },
  "sessions-600": { sessions: 600, eventsPerSession: 1, payloadBytes: 128 },
  "sessions-600-batched": { sessions: 600, eventsPerSession: 1, payloadBytes: 128, sessionBatchSize: 100 },
  "slow-writes": { sessions: 4, eventsPerSession: 12, payloadBytes: 256 * 1024, appendDelayMs: 15 },
  "slow-overflow": { sessions: 1, eventsPerSession: 8, payloadBytes: 256 * 1024,
    appendDelayMs: 15, maxPendingBytes: MiB, errorCode: "PENDING_BYTES_LIMIT" },
};

async function measure(name, outputDir) {
  assert.equal(typeof global.gc, "function", "worker requires --expose-gc");
  const workload = scenarios[name];
  assert.ok(workload, "unknown measurement scenario");
  const started = performance.now();
  const samples = [];
  const sample = (phase) => samples.push({ phase, elapsedMs: performance.now() - started, ...process.memoryUsage() });
  global.gc();
  sample("baseline-gc");
  const errors = [];
  const recorder = createRecorder({ outputDir, maxPendingBytes: workload.maxPendingBytes ?? 16 * MiB,
    onError: (error, sessionId) => errors.push({ code: error.code ?? null, message: error.message, sessionId }) });
  const initialManifestBytes = (await fs.stat(join(recorder.runDir, "run.json"))).size;
  const io = { appendCalls: 0, appendedBytes: 0, manifestWrites: 1, manifestBytes: initialManifestBytes };
  const originalAppend = fs.appendFile;
  const originalWrite = fs.writeFile;
  let firstAppendStarted;
  const firstAppend = new Promise((done) => { firstAppendStarted = done; });
  // Only these worker-local wrappers add delay/counters; every write still uses real files.
  fs.appendFile = async (path, data, ...args) => {
    io.appendCalls++;
    firstAppendStarted();
    if (workload.appendDelayMs) await delay(workload.appendDelayMs);
    const result = await originalAppend(path, data, ...args);
    io.appendedBytes += data.length;
    return result;
  };
  fs.writeFile = async (path, data, ...args) => {
    const result = await originalWrite(path, data, ...args);
    if (basename(String(path)).startsWith("run.json.")) {
      io.manifestWrites++;
      io.manifestBytes += Buffer.byteLength(data);
    }
    return result;
  };
  syncBuiltinESMExports();
  const timer = setInterval(() => sample("interval"), 10);
  let accepted = 0;
  let rejected = 0;
  let closeRejected = false;
  let closeMs;
  const attempt = (id, event) => {
    if (recorder.record(id, event)) accepted++;
    else rejected++;
  };
  try {
    // One shared ASCII payload is retained by the producer throughout this sample.
    const payload = "x".repeat(workload.payloadBytes);
    sample("input-created");
    if (name === "slow-overflow") {
      attempt("s0", { seq: 0, data: payload });
      await firstAppend; // Overflow while the first real append is in flight.
      for (let seq = 1; seq < workload.eventsPerSession; seq++) attempt("s0", { seq, data: payload });
      sample("after-burst");
      await assert.rejects(recorder.flush("s0"), AggregateError);
    } else {
      for (let seq = 0; seq < workload.eventsPerSession; seq++) {
        for (let id = 0; id < workload.sessions; id++) {
          attempt(`s${id}`, { seq, data: payload });
          if (workload.sessionBatchSize && (id + 1) % workload.sessionBatchSize === 0) {
            sample("before-session-flush");
            await recorder.flush();
          }
        }
        sample("after-burst");
        if (workload.flushEvery && (seq + 1) % workload.flushEvery === 0) await recorder.flush();
      }
    }
    if (workload.errorCode) {
      // A failed session must not prevent a later small healthy session from sealing.
      attempt("healthy", { seq: 0, data: "healthy" });
      await recorder.flush("healthy");
    }
    const closeStarted = performance.now();
    try { await recorder.close(); } catch (error) {
      assert.ok(error instanceof AggregateError);
      closeRejected = true;
    }
    closeMs = performance.now() - closeStarted;
    sample("after-close");
    global.gc();
    sample("after-close-gc");
  } finally {
    clearInterval(timer);
    fs.appendFile = originalAppend;
    fs.writeFile = originalWrite;
    syncBuiltinESMExports();
  }
  const measurementMs = performance.now() - started;
  // Inspect only after memory sampling, so its buffers do not count as recorder load.
  const inspection = await inspectRun(recorder.runDir);
  const metadata = JSON.parse(await fs.readFile(join(recorder.runDir, "run.json"), "utf8"));
  const totals = { received: 0, accepted: 0, written: 0, writtenBytes: 0, sealed: 0, failed: 0 };
  for (const member of metadata.sessions) {
    const status = JSON.parse(await fs.readFile(join(recorder.runDir, member.statusFile), "utf8"));
    totals.received += status.receivedCount;
    totals.accepted += status.acceptedCount;
    totals.written += status.writtenCount;
    totals.writtenBytes += status.writtenBytes;
    totals[status.state]++;
    if (member.sessionId === "healthy") assert.equal(status.state, "sealed");
  }
  assert.equal(totals.accepted, accepted);
  assert.equal(totals.writtenBytes, io.appendedBytes);
  assert.equal(inspection.exitCode, workload.errorCode ? 1 : 0);
  assert.equal(closeRejected, Boolean(workload.errorCode));
  if (workload.errorCode) {
    assert.equal(errors.length, workload.sessions);
    assert.ok(errors.every((error) => error.code === workload.errorCode && error.sessionId !== null));
    assert.equal(totals.sealed, 1);
    assert.equal(totals.failed, workload.sessions);
    assert.equal(accepted, name === "oversize" ? 1 : 4);
    assert.equal(totals.written, name === "oversize" ? 1 : 2);
  } else {
    assert.deepEqual(errors, []);
    assert.equal(rejected, 0);
    assert.equal(totals.written, workload.sessions * workload.eventsPerSession);
    assert.equal(totals.sealed, workload.sessions);
  }
  const memoryFields = ["rss", "heapTotal", "heapUsed", "external", "arrayBuffers"];
  const sampledMax = Object.fromEntries(memoryFields.map((key) => [key, Math.max(...samples.map((row) => row[key]))]));
  return { scenario: name, workload, runId: recorder.runId, limits: {
    maxEventBytes: metadata.maxEventBytes, maxPendingBytes: metadata.maxPendingBytes,
  }, accepted, rejected, totals, errors, closeRejected, closeMs, measurementMs, io,
  inspection: { exitCode: inspection.exitCode, outcome: inspection.outcome, runManifest: inspection.runManifest },
  memory: { baseline: samples[0], afterCloseGC: samples.at(-1), sampledMax, samples } };
}

async function main() {
  const args = process.argv.slice(2);
  if (args[0] === "--worker") {
    assert.equal(args.length, 3);
    console.log(JSON.stringify(await measure(args[1], resolve(args[2]))));
    return;
  }
  if (args.length !== 0 && (args.length !== 2 || args[0] !== "--repeats" || !/^[1-9]\d*$/.test(args[1]) || Number(args[1]) > 10)) {
    throw new Error("Usage: npm.cmd run measure:recorder -- [--repeats 1..10]");
  }
  const repeats = args.length ? Number(args[1]) : 3;
  const outputDir = resolve("runs", "recorder-resources", randomUUID());
  await fs.mkdir(outputDir, { recursive: true });
  const summary = { measurementFormatVersion: 1, source: "synthetic", modelCalled: false,
    startedAt: new Date().toISOString(), environment: { node: process.version, platform: platform(), arch: arch(), release: release() },
    repeats, method: "One fresh --expose-gc Node process per scenario/repeat; real files; shared ASCII input; memory at boundaries and 10 ms intervals; sampled maxima are not true peaks. Timings include instrumentation and I/O. No model calls or performance comparison.",
    samples: [] };
  const summaryPath = join(outputDir, "summary.json");
  console.info(`资源测量目录：${outputDir}`);
  for (let repeat = 1; repeat <= repeats; repeat++) {
    for (const scenario of Object.keys(scenarios)) {
      const directory = join(outputDir, `${scenario}-${repeat}`);
      try {
        const { stdout, stderr } = await promisify(execFile)(process.execPath, ["--expose-gc",
          fileURLToPath(import.meta.url), "--worker", scenario, directory],
        { windowsHide: true, encoding: "utf8", timeout: 60000, maxBuffer: 4 * MiB });
        assert.equal(stderr, "");
        const measurement = { repeat, ...JSON.parse(stdout) };
        await fs.writeFile(join(directory, "measurement.json"), JSON.stringify(measurement, null, 2) + "\n", { flag: "wx" });
        summary.samples.push(measurement);
        console.info(`${scenario} #${repeat}: accepted=${measurement.accepted}, written=${measurement.totals.written}, inspect=${measurement.inspection.exitCode}`);
      } catch (error) {
        summary.failure = { scenario, repeat, message: error.message, code: error.code ?? null, stderr: error.stderr ?? null };
        throw error;
      } finally {
        await fs.writeFile(summaryPath, JSON.stringify(summary, null, 2) + "\n");
      }
    }
  }
  console.info(`完成 ${summary.samples.length} 个独立进程样本：${summaryPath}`);
}

await main();
