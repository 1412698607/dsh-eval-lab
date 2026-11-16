import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import fsSync from "node:fs";
import fs from "node:fs/promises";
import { syncBuiltinESMExports } from "node:module";
import { arch, cpus, platform, release } from "node:os";
import { basename, dirname, join, relative, resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";
import { armDelayMonitor, artifactEvidence, delaySummary, latencySummary, parseOptions, sha256, sourceProvenance } from "./recorder-measurement.js";

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
  "sustained": { sessions: 4, eventsPerSession: 2000, payloadBytes: 4096,
    rounds: 500, eventsPerRound: 4, periodMs: 40 },
};

const measurementModule = fileURLToPath(import.meta.url);
const samplingProtocol = {
  version: 2, memoryIntervalMs: 10, delayResolutionMs: 10, delayWarmupMs: 20,
  delayArmPollMs: 20, delayArmTimeoutMs: 1000, delayTailMs: 20,
  cpuPhases: ["baseline-gc", "setup", "input", "producer", "close", "final-gc"],
  cpuUnits: "microseconds", latencyUnits: "milliseconds",
  producerIncludes: "record calls, producer instrumentation, flush calls, I/O during awaits, and cadence waits",
  eventLoopWindow: "delay histogram includes post-reset arming until first sample (20 ms polling, 1 s timeout) and 20 ms tail observation, plus baseline GC through final GC; includes nominal timer interval, not only excess delay; ELU excludes arm and tail",
  workloadWindow: "first producer action through close completion; excludes setup, input allocation, final GC and inspect",
  normalization: "verified raw digests; top-level runId to same-length zero UUID, generated startedAt/updatedAt to fixed ISO time; derived status/inspect digests mapped to normalized trace digests; event objects unchanged",
};

async function measure(name, outputDir, options) {
  assert.equal(typeof global.gc, "function", "worker requires --expose-gc");
  const workload = scenarios[name];
  assert.ok(workload, "unknown measurement scenario");
  const provenance = await sourceProvenance(options.recorderModule, options.inspectModule, measurementModule);
  const { createRecorder } = await import(pathToFileURL(options.recorderModule));
  const { inspectRun } = await import(pathToFileURL(options.inspectModule));
  // Hash the exact ordered producer inputs outside the measurement window.
  const inputHash = createHash("sha256");
  for (let seq = 0; seq < workload.eventsPerSession; seq++) {
    for (let id = 0; id < workload.sessions; id++) inputHash.update(JSON.stringify({ sessionId: `s${id}`,
      event: { seq, data: "x".repeat(workload.payloadBytes) } }) + "\n");
  }
  if (workload.errorCode) inputHash.update(JSON.stringify({ sessionId: "healthy", event: { seq: 0, data: "healthy" } }) + "\n");
  const inputSha256 = inputHash.digest("hex");
  const workloadFingerprint = sha256(JSON.stringify({ scenario: name, workload, inputSha256, samplingProtocol }));
  const { histogram, arm } = await armDelayMonitor();
  try {
  const started = performance.now();
  const cpuStarted = process.cpuUsage();
  const eluStarted = performance.eventLoopUtilization();
  const samples = [];
  const phases = [];
  const cpuSnapshot = (before, wallStarted) => {
    const cpu = process.cpuUsage(before);
    return { userUs: cpu.user, systemUs: cpu.system, wallMs: performance.now() - wallStarted };
  };
  const phase = async (name, work) => {
    const wallStarted = performance.now();
    const before = process.cpuUsage();
    try { return await work(); } finally { phases.push({ phase: name, ...cpuSnapshot(before, wallStarted) }); }
  };
  const sample = (phase) => samples.push({ phase, elapsedMs: performance.now() - started, ...process.memoryUsage() });
  await phase("baseline-gc", () => global.gc());
  sample("baseline-gc");
  const errors = [];
  const io = Object.fromEntries(["append", "manifestWrite", "statusWrite", "manifestRename", "statusRename"]
    .map((key) => [key, { calls: 0, completed: 0, bytes: 0, elapsedMs: 0 }]));
  const originalAppend = fs.appendFile;
  const originalWrite = fs.writeFile;
  const originalRename = fs.rename;
  const originalSyncWrite = fsSync.writeFileSync;
  let firstAppendStarted;
  const firstAppend = new Promise((done) => { firstAppendStarted = done; });
  const track = async (counter, bytes, operation) => {
    const start = performance.now();
    counter.calls++;
    try { const value = await operation(); counter.completed++; counter.bytes += bytes; return value; }
    finally { counter.elapsedMs += performance.now() - start; }
  };
  const kind = (path) => basename(String(path)).startsWith("run.json") ? "manifest" : "status";
  // Only these worker-local wrappers add delay/counters; every write still uses real files.
  fs.appendFile = (path, data, ...args) => track(io.append, Buffer.byteLength(data), async () => {
    firstAppendStarted();
    if (workload.appendDelayMs) await delay(workload.appendDelayMs);
    return originalAppend(path, data, ...args);
  });
  fs.writeFile = (path, data, ...args) => track(io[`${kind(path)}Write`], Buffer.byteLength(data), () => originalWrite(path, data, ...args));
  fs.rename = (from, to, ...args) => track(io[`${kind(to)}Rename`], 0, () => originalRename(from, to, ...args));
  fsSync.writeFileSync = (path, data, ...args) => {
    const counter = io[`${kind(path)}Write`];
    const start = performance.now();
    counter.calls++;
    try { const value = originalSyncWrite(path, data, ...args); counter.completed++; counter.bytes += Buffer.byteLength(data); return value; }
    finally { counter.elapsedMs += performance.now() - start; }
  };
  syncBuiltinESMExports();
  let recorder;
  const timer = setInterval(() => sample("interval"), 10);
  const enqueueTimes = [];
  const flushCalls = [];
  const rounds = [];
  let accepted = 0;
  let rejected = 0;
  let closeRejected = false;
  let closeMs;
  let workloadStarted;
  let workloadMs;
  const attempt = (id, event) => {
    const start = performance.now();
    if (recorder.record(id, event)) accepted++;
    else rejected++;
    enqueueTimes.push(performance.now() - start);
  };
  const flush = async (sessionId) => {
    const start = performance.now();
    const before = process.cpuUsage();
    let rejected = false;
    try { return await recorder.flush(sessionId); } catch (error) { rejected = true; throw error; }
    finally { flushCalls.push({ sessionId: sessionId ?? null, rejected, ...cpuSnapshot(before, start) }); }
  };
  try {
    recorder = await phase("setup", () => createRecorder({ outputDir, maxPendingBytes: workload.maxPendingBytes ?? 16 * MiB,
      onError: (error, sessionId) => errors.push({ code: error.code ?? null, message: error.message, sessionId }) }));
    // One shared ASCII payload is retained by the producer throughout this sample.
    const payload = await phase("input", () => "x".repeat(workload.payloadBytes));
    sample("input-created");
    workloadStarted = performance.now();
    await phase("producer", async () => {
    if (name === "slow-overflow") {
      attempt("s0", { seq: 0, data: payload });
      await firstAppend; // Overflow while the first real append is in flight.
      for (let seq = 1; seq < workload.eventsPerSession; seq++) attempt("s0", { seq, data: payload });
      sample("after-burst");
      await assert.rejects(flush("s0"), AggregateError);
    } else if (workload.rounds) {
      const cadenceStarted = performance.now();
      for (let round = 0; round < workload.rounds; round++) {
        const scheduledMs = round * workload.periodMs;
        const waitMs = scheduledMs - (performance.now() - cadenceStarted);
        if (waitMs > 0) await delay(waitMs);
        const roundStarted = performance.now();
        const roundCpu = process.cpuUsage();
        const startedMs = roundStarted - cadenceStarted;
        for (let step = 0; step < workload.eventsPerRound; step++) {
          for (let id = 0; id < workload.sessions; id++) attempt(`s${id}`, {
            seq: round * workload.eventsPerRound + step, data: payload });
        }
        await flush();
        rounds.push({ round, scheduledMs, startedMs, latenessMs: Math.max(0, startedMs - scheduledMs),
          ...cpuSnapshot(roundCpu, roundStarted) });
        sample("after-round-flush");
      }
    } else {
      for (let seq = 0; seq < workload.eventsPerSession; seq++) {
        for (let id = 0; id < workload.sessions; id++) {
          attempt(`s${id}`, { seq, data: payload });
          if (workload.sessionBatchSize && (id + 1) % workload.sessionBatchSize === 0) {
            sample("before-session-flush");
            await flush();
          }
        }
        sample("after-burst");
        if (workload.flushEvery && (seq + 1) % workload.flushEvery === 0) await flush();
      }
    }
    if (workload.errorCode) {
      // A failed session must not prevent a later small healthy session from sealing.
      attempt("healthy", { seq: 0, data: "healthy" });
      await flush("healthy");
    }
    });
    const closeStarted = performance.now();
    try { await phase("close", () => recorder.close()); } catch (error) {
      assert.ok(error instanceof AggregateError);
      closeRejected = true;
    }
    closeMs = performance.now() - closeStarted;
    workloadMs = performance.now() - workloadStarted;
    sample("after-close");
    await phase("final-gc", () => global.gc());
    sample("after-close-gc");
  } catch (error) {
    // Drain any accepted writes before removing the worker-local I/O wrappers.
    // Cleanup failure must not replace the error that invalidated this sample.
    try { await recorder?.close(); } catch { /* Preserve the original measurement failure. */ }
    throw error;
  } finally {
    clearInterval(timer);
    fs.appendFile = originalAppend;
    fs.writeFile = originalWrite;
    fs.rename = originalRename;
    fsSync.writeFileSync = originalSyncWrite;
    syncBuiltinESMExports();
  }
  const measurementMs = performance.now() - started;
  const totalCpu = cpuSnapshot(cpuStarted, started);
  const elu = performance.eventLoopUtilization(eluStarted);
  const tailStarted = performance.now();
  await delay(20);
  histogram.disable();
  const eventLoop = { delay: { ...delaySummary(histogram), arm, tailElapsedMs: performance.now() - tailStarted },
    utilization: { activeMs: elu.active, idleMs: elu.idle,
    totalMs: elu.active + elu.idle, utilization: elu.active + elu.idle > 0 ? elu.utilization : null } };
  Object.assign(io, { appendCalls: io.append.calls, appendedBytes: io.append.bytes,
    manifestWrites: io.manifestWrite.completed, manifestBytes: io.manifestWrite.bytes });
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
  const artifacts = await artifactEvidence(recorder.runDir, metadata, inspection, (id, event) => {
    assert.deepEqual(Object.keys(event), ["seq", "data"]);
    assert.equal(event.data, id === "healthy" ? "healthy" : "x".repeat(workload.payloadBytes));
    assert.ok(Number.isInteger(event.seq) && event.seq >= 0 && event.seq < (id === "healthy" ? 1 : workload.eventsPerSession));
  });
  assert.deepEqual(await sourceProvenance(options.recorderModule, options.inspectModule, measurementModule), provenance,
    "source changed during measurement");
  return { status: "completed", scenario: name, workload, workloadFingerprint, inputSha256, provenance,
    samplingProtocol, runId: recorder.runId, limits: {
    maxEventBytes: metadata.maxEventBytes, maxPendingBytes: metadata.maxPendingBytes,
  }, accepted, rejected, totals, errors, closeRejected, closeMs, measurementMs, io,
  inspection, artifacts, cpu: { phases, total: totalCpu }, enqueue: latencySummary(enqueueTimes),
  flush: { calls: flushCalls, summary: latencySummary(flushCalls.map((call) => call.wallMs)) }, rounds,
  timing: { workloadMs, attemptedPerSecond: (accepted + rejected) * 1000 / workloadMs,
    acceptedPerSecond: accepted * 1000 / workloadMs, writtenPerSecond: totals.written * 1000 / workloadMs,
    writtenBytesPerSecond: totals.writtenBytes * 1000 / workloadMs }, eventLoop,
  memory: { baseline: samples[0], afterCloseGC: samples.at(-1), sampledMax, samples } };
  } finally { histogram.disable(); }
}

async function main() {
  const args = process.argv.slice(2);
  if (args[0] === "--worker") {
    assert.equal(args.length, 4);
    const outputDir = resolve(args[2]);
    await fs.mkdir(outputDir);
    try { console.log(JSON.stringify(await measure(args[1], outputDir, JSON.parse(args[3])))); }
    catch (error) {
      await fs.writeFile(join(outputDir, "failure.json"), JSON.stringify({ status: "failed", scenario: args[1],
        message: error.message, code: error.code ?? null, stack: error.stack }, null, 2) + "\n", { flag: "wx" });
      throw error;
    }
    return;
  }
  const options = parseOptions(args, Object.keys(scenarios), fileURLToPath(new URL("../src/recorder.js", import.meta.url)),
    fileURLToPath(new URL("../src/inspect.js", import.meta.url)));
  const { repeats } = options;
  const outputDir = options.outputDir ?? resolve("runs", "recorder-resources", randomUUID());
  const provenance = await sourceProvenance(options.recorderModule, options.inspectModule, measurementModule);
  await fs.mkdir(dirname(outputDir), { recursive: true });
  await fs.mkdir(outputDir); // Never reuse or overwrite a previous batch.
  const processors = cpus();
  const summary = { measurementFormatVersion: 2, status: "running", source: "synthetic", modelCalled: false,
    startedAt: new Date().toISOString(), environment: { node: process.version, platform: platform(), arch: arch(), release: release(),
      cpuModel: processors[0]?.model ?? null, logicalCpus: processors.length },
    repeats, scenarios: options.scenarios, provenance, samplingProtocol,
    method: "One fresh --expose-gc Node process per scenario/repeat; real files; shared ASCII input. Sampled memory maxima are not peaks. CPU includes instrumentation. Flush CPU is a producer subset; cumulative I/O elapsed times overlap. No model calls.",
    samples: [] };
  const summaryPath = join(outputDir, "summary.json");
  console.info(`资源测量目录：${outputDir}`);
  for (let repeat = 1; repeat <= repeats; repeat++) {
    for (const scenario of options.scenarios) {
      const directory = join(outputDir, `${scenario}-${repeat}`);
      try {
        const { stdout, stderr } = await promisify(execFile)(process.execPath, ["--expose-gc",
          measurementModule, "--worker", scenario, directory, JSON.stringify(options)],
        { windowsHide: true, encoding: "utf8", timeout: 120000, maxBuffer: 8 * MiB });
        assert.equal(stderr, "");
        const measurement = { repeat, ...JSON.parse(stdout) };
        assert.deepEqual(measurement.provenance, provenance, "worker source differs from batch source");
        measurement.runDirectory = relative(outputDir, join(directory, measurement.runId)).replaceAll("\\", "/");
        await fs.writeFile(join(directory, "measurement.json"), JSON.stringify(measurement, null, 2) + "\n", { flag: "wx" });
        summary.samples.push(measurement);
        console.info(`${scenario} #${repeat}: accepted=${measurement.accepted}, written=${measurement.totals.written}, inspect=${measurement.inspection.exitCode}`);
      } catch (error) {
        summary.status = "failed";
        summary.failure = { scenario, repeat, message: error.message, code: error.code ?? null, stderr: error.stderr ?? null };
        throw error;
      } finally {
        await fs.writeFile(summaryPath, JSON.stringify(summary, null, 2) + "\n");
      }
    }
  }
  summary.status = "completed";
  summary.completedAt = new Date().toISOString();
  await fs.writeFile(summaryPath, JSON.stringify(summary, null, 2) + "\n");
  console.info(`完成 ${summary.samples.length} 个独立进程样本：${summaryPath}`);
}

await main();
