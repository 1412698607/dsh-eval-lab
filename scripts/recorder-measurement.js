import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { monitorEventLoopDelay, performance } from "node:perf_hooks";
import { setTimeout as delay } from "node:timers/promises";

export const sha256 = (data) => createHash("sha256").update(data).digest("hex");

export function parseOptions(args, scenarioNames, defaultRecorder, defaultInspector) {
  const options = { repeats: 3, scenarios: scenarioNames.filter((name) => name !== "sustained"),
    recorderModule: defaultRecorder, inspectModule: defaultInspector };
  const seen = new Set();
  for (let index = 0; index < args.length; index += 2) {
    const key = args[index];
    const value = args[index + 1];
    assert.ok(["--repeats", "--scenarios", "--output-dir", "--recorder-module", "--inspect-module"].includes(key)
      && value && !value.startsWith("--") && !seen.has(key), "Invalid or duplicate measurement option");
    seen.add(key);
    if (key === "--repeats") {
      assert.ok(/^[1-9]\d*$/.test(value) && Number(value) <= 10, "repeats must be 1..10");
      options.repeats = Number(value);
    } else if (key === "--scenarios") {
      options.scenarios = value.split(",");
      assert.ok(options.scenarios.every((name) => scenarioNames.includes(name))
        && new Set(options.scenarios).size === options.scenarios.length, "Invalid or duplicate scenario");
    } else options[{ "--output-dir": "outputDir", "--recorder-module": "recorderModule",
      "--inspect-module": "inspectModule" }[key]] = resolve(value);
  }
  return options;
}

// The recorder/inspector use this fixed local dependency set, including metadata's package read.
// A new runtime dependency requires extending this manifest before measuring that implementation.
export async function sourceProvenance(recorderModule, inspectModule, measurementModule) {
  async function group(entry, inspector = false) {
    const sourceDir = dirname(entry);
    const paths = [entry, ...["config.js", "metadata.js", "session-status.js"].map((file) => join(sourceDir, file)),
      join(sourceDir, "..", "package.json")];
    if (inspector) paths.push(join(sourceDir, "recorder.js"));
    const names = [inspector ? "inspect.js" : "recorder.js", "config.js", "metadata.js", "session-status.js", "../package.json"];
    if (inspector) names.push("recorder.js");
    return hashFiles(paths.map((path, index) => ({ name: names[index], path })));
  }
  return { recorder: await group(recorderModule), inspector: await group(inspectModule, true),
    measurement: await hashFiles([{ name: "measure-recorder.js", path: measurementModule },
      { name: "recorder-measurement.js", path: join(dirname(measurementModule), "recorder-measurement.js") }]) };
}

async function hashFiles(entries) {
  const files = [];
  for (const entry of entries) files.push({ ...entry, sha256: sha256(await fs.readFile(entry.path)) });
  return { sha256: sha256(JSON.stringify(files.map(({ name, sha256: hash }) => ({ name, sha256: hash })))), files };
}

export function latencySummary(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const percentile = (fraction) => sorted.length ? sorted[Math.ceil(sorted.length * fraction) - 1] : null;
  return { count: sorted.length, totalMs: sorted.reduce((sum, value) => sum + value, 0),
    minMs: sorted[0] ?? null, maxMs: sorted.at(-1) ?? null,
    p50Ms: percentile(0.5), p95Ms: percentile(0.95), p99Ms: percentile(0.99) };
}

export function delaySummary(histogram) {
  const count = Number(histogram.count);
  const milliseconds = (value) => count ? value / 1e6 : null;
  return { count, resolutionMs: 10, minMs: milliseconds(histogram.min), maxMs: milliseconds(histogram.max),
    meanMs: milliseconds(histogram.mean), stddevMs: milliseconds(histogram.stddev),
    p50Ms: count ? histogram.percentile(50) / 1e6 : null,
    p95Ms: count ? histogram.percentile(95) / 1e6 : null,
    p99Ms: count ? histogram.percentile(99) / 1e6 : null };
}

export async function armDelayMonitor() {
  const histogram = monitorEventLoopDelay({ resolution: 10 });
  histogram.enable();
  await delay(20);
  histogram.reset();
  const start = performance.now();
  // Reset must be followed by a sampled timer turn before the first synchronous burst.
  do { await delay(20); } while (!histogram.count && performance.now() - start < 1000);
  const arm = { samples: Number(histogram.count), elapsedMs: performance.now() - start };
  if (!arm.samples) { histogram.disable(); throw new Error("event-loop monitor failed to acquire an arming sample"); }
  return { histogram, arm };
}

const identityRunId = "00000000-0000-0000-0000-000000000000";
const identityTime = "2000-01-01T00:00:00.000Z";

function validGeneratedTime(value) {
  const parsed = typeof value === "string" ? Date.parse(value) : NaN;
  assert.ok(Number.isFinite(parsed) && new Date(parsed).toISOString() === value,
    "normalization requires a valid generated ISO timestamp");
}

// Keep raw digests. Only verified trace-derived digests are mapped to their normalized equivalents.
export async function artifactEvidence(runDir, metadata, inspection, expectedEvent) {
  const files = [];
  const traceHashes = new Map();
  const traces = new Map();
  const names = (await fs.readdir(runDir)).sort();
  const expectedNames = new Set(["run.json"]);
  for (const member of metadata.sessions) {
    expectedNames.add(member.statusFile);
    let bytes;
    try { bytes = await fs.readFile(join(runDir, member.traceFile)); } catch (error) {
      if (error.code !== "ENOENT") throw error;
      bytes = Buffer.alloc(0);
    }
    const rows = bytes.length ? bytes.toString("utf8").trimEnd().split("\n").map((line) => JSON.parse(line)) : [];
    const canonicalBytes = Buffer.from(rows.map((row) => JSON.stringify(row) + "\n").join(""));
    assert.ok(bytes.equals(canonicalBytes), "trace bytes must be canonical UTF-8 JSONL before identity normalization");
    const normalized = rows.map((row) => {
      assert.equal(row.runId, metadata.runId);
      assert.equal(row.sessionId, member.sessionId);
      expectedEvent(row.sessionId, row.event);
      return JSON.stringify({ ...row, runId: identityRunId }) + "\n";
    }).join("");
    const entry = { sha256: sha256(bytes), normalizedSha256: sha256(normalized), bytes: bytes.length, count: rows.length };
    traces.set(member.traceFile, entry);
    traceHashes.set(member.traceFile, entry.normalizedSha256);
    if (bytes.length) {
      expectedNames.add(member.traceFile);
      files.push({ file: member.traceFile, ...entry });
    }
  }
  assert.deepEqual(names, [...expectedNames].sort(), "unexpected/missing recorder output files");
  for (const file of names.filter((name) => name.endsWith(".json"))) {
    const bytes = await fs.readFile(join(runDir, file));
    const data = JSON.parse(bytes);
    assert.equal(data.runId, metadata.runId);
    const normalized = { ...data, runId: identityRunId };
    if (file === "run.json") {
      validGeneratedTime(data.startedAt);
      normalized.startedAt = identityTime;
    }
    else {
      validGeneratedTime(data.updatedAt);
      normalized.updatedAt = identityTime;
      const trace = traces.get(data.traceFile);
      assert.ok(trace, "status must name an expected trace");
      assert.equal(data.sha256, trace.sha256, "status must match actual trace digest before normalization");
      assert.equal(data.writtenBytes, trace.bytes);
      assert.equal(data.writtenCount, trace.count);
      normalized.sha256 = trace.normalizedSha256;
    }
    files.push({ file, bytes: bytes.length, sha256: sha256(bytes), normalizedSha256: sha256(JSON.stringify(normalized)) });
  }
  const normalizedInspection = structuredClone(inspection);
  assert.equal(normalizedInspection.runDir, runDir);
  normalizedInspection.runDir = "<run-directory>";
  for (const session of normalizedInspection.sessions) {
    if (session.sha256 !== undefined) {
      assert.equal(session.sha256, traces.get(session.traceFile)?.sha256);
      session.sha256 = traceHashes.get(session.traceFile);
    }
  }
  files.sort((a, b) => a.file.localeCompare(b.file));
  return { files, normalizedFilesSha256: sha256(JSON.stringify(files.map(({ file, bytes, normalizedSha256 }) =>
    ({ file, bytes, normalizedSha256 })))), normalizedInspectionSha256: sha256(JSON.stringify(normalizedInspection)) };
}
