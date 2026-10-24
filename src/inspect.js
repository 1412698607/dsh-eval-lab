import { createReadStream } from "node:fs";
import { readFile, readdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { join, resolve } from "node:path";
import { traceFilename } from "./recorder.js";
import { statusFilename } from "./session-status.js";

const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const count = (value) => Number.isSafeInteger(value) && value >= 0;
const digest = (value) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const emptyDigest = createHash("sha256").digest("hex");

async function readJson(path) {
  // Reject malformed UTF-8 instead of silently substituting replacement characters.
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(await readFile(path)));
}

// Hash original bytes and decode one complete line at a time. Never rebuild bytes from JSON.
async function scanTrace(path, file, runId, sessionId, checkpointBytes) {
  const hash = createHash("sha256");
  let remainder = Buffer.alloc(0);
  let writtenCount = 0;
  let writtenBytes = 0;
  let firstSeq = null;
  let lastSeq = null;
  let checkpoint = checkpointBytes === 0
    ? { writtenCount: 0, writtenBytes: 0, firstSeq: null, lastSeq: null, sha256: emptyDigest }
    : null;
  const gaps = [];
  let gapCount = 0;
  for await (const chunk of createReadStream(path)) {
    const bytes = remainder.length ? Buffer.concat([remainder, chunk]) : chunk;
    let start = 0;
    let end;
    while ((end = bytes.indexOf(10, start)) !== -1) {
      const line = bytes.subarray(start, end + 1);
      const row = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(line));
      if (!object(row) || row.formatVersion !== 1 || typeof row.runId !== "string" || !row.runId
        || typeof row.sessionId !== "string" || !row.sessionId || !object(row.event)) {
        throw new Error(`第 ${writtenCount + 1} 行包装格式无效`);
      }
      runId ??= row.runId;
      sessionId ??= row.sessionId;
      if (row.runId !== runId || row.sessionId !== sessionId || traceFilename(row.sessionId) !== file) {
        throw new Error(`第 ${writtenCount + 1} 行运行或会话身份不匹配`);
      }
      const seq = row.event.seq;
      if (!count(seq) || (lastSeq !== null && seq <= lastSeq)) {
        throw new Error(`第 ${writtenCount + 1} 行序号非法或未严格递增`);
      }
      if (lastSeq !== null && seq > lastSeq + 1) {
        gapCount++;
        if (gaps.length < 100) gaps.push({ after: lastSeq, before: seq });
      }
      firstSeq ??= seq;
      lastSeq = seq;
      writtenCount++;
      writtenBytes += line.length;
      hash.update(line);
      if (writtenBytes === checkpointBytes) {
        checkpoint = { writtenCount, writtenBytes, firstSeq, lastSeq, sha256: hash.copy().digest("hex") };
      }
      start = end + 1;
    }
    remainder = bytes.subarray(start);
  }
  if (remainder.length) throw new Error("末行缺少换行，可能被截断");
  if (!writtenCount) throw new Error("日志为空");
  return { sessionId, writtenCount, writtenBytes, firstSeq, lastSeq, sha256: hash.digest("hex"), gaps, gapCount, checkpoint };
}

function validateStatus(status, file, manifest) {
  if (!object(status) || typeof status.sessionId !== "string" || !status.sessionId
    || typeof status.runId !== "string" || !status.runId || status.traceFile !== file
    || traceFilename(status.sessionId) !== file || (manifest && status.runId !== manifest.runId)
    || status.captureScope !== "live-events-only" || !["recording", "sealed", "failed"].includes(status.state)) {
    throw new Error("状态身份、捕获范围或状态值无效");
  }
  if (![status.receivedCount, status.acceptedCount, status.writtenCount, status.writtenBytes].every(count)
    || status.writtenCount > status.acceptedCount || status.acceptedCount > status.receivedCount
    || !digest(status.sha256)) throw new Error("状态计数或摘要格式无效");
  if (status.writtenCount === 0) {
    if (status.firstSeq !== null || status.lastSeq !== null || status.writtenBytes !== 0 || status.sha256 !== emptyDigest) {
      throw new Error("空检查点的序号、字节数或摘要不一致");
    }
  } else if (!count(status.firstSeq) || !count(status.lastSeq) || status.firstSeq > status.lastSeq || !status.writtenBytes) {
    throw new Error("状态序号边界无效");
  }
  if (status.state === "sealed" && (status.writtenCount === 0
    || status.receivedCount !== status.acceptedCount || status.acceptedCount !== status.writtenCount)) {
    throw new Error("封存状态的接收、排队、写入计数不一致或为空");
  }
  if (status.state !== "failed" && status.error !== null) throw new Error("非失败状态含错误或缺少 error 字段");
  if (status.state === "failed" && (!object(status.error) || typeof status.error.message !== "string")) {
    throw new Error("失败状态缺少错误信息");
  }
}

async function inspectSession(runDir, file, manifest, files, expected) {
  const result = { traceFile: file, outcome: "unverified", reasons: [] };
  if (expected) result.sessionId = expected.sessionId;
  let status;
  if (files.has(statusFilename(file))) {
    try {
      status = await readJson(join(runDir, statusFilename(file)));
      if (object(status) && status.statusFormatVersion !== 1) {
        result.reasons.push("不支持的状态格式版本");
        status = undefined;
      } else {
        validateStatus(status, file, manifest);
        if (expected && status.sessionId !== expected.sessionId) throw new Error("状态与运行清单的会话身份不匹配");
      }
    } catch (error) {
      result.outcome = error.code && !["EISDIR", "ERR_ENCODING_INVALID_ENCODED_DATA"].includes(error.code) ? "unverified" : "invalid";
      result.reasons.push(`状态无法校验：${error.message}`);
      return result;
    }
  } else result.reasons.push("缺少状态文件，不能确认封存");
  if (status) {
    result.state = status.state;
    result.sessionId = status.sessionId;
    if (status.state === "failed") {
      result.outcome = "invalid";
      result.reasons.push(`录制失败：${status.error.message}`);
    } else if (status.state === "recording") result.reasons.push("录制尚未封存，可能仍开放或异常退出");
  }
  if (!files.has(file)) {
    if (status?.state === "sealed" || status?.writtenCount > 0) result.outcome = "invalid";
    result.reasons.push("缺少日志文件");
    return result;
  }
  try {
    const scanned = await scanTrace(join(runDir, file), file, manifest?.runId ?? status?.runId,
      expected?.sessionId ?? status?.sessionId, status?.writtenBytes);
    const { checkpoint, ...summary } = scanned;
    Object.assign(result, summary);
    if (status) {
      const measured = status.state === "sealed" ? scanned : checkpoint;
      if (!measured || ["writtenCount", "writtenBytes", "firstSeq", "lastSeq", "sha256"].some((key) => measured[key] !== status[key])) {
        result.outcome = "invalid";
        result.reasons.push("日志与状态的条数、字节数、序号边界或 SHA-256 不匹配");
      } else if (status.state === "sealed") result.outcome = "complete";
    }
  } catch (error) {
    // Access errors cannot prove corruption; malformed content and missing sealed data can.
    if (!error.code || ["ENOENT", "EISDIR", "ERR_ENCODING_INVALID_ENCODED_DATA"].includes(error.code)) result.outcome = "invalid";
    result.reasons.push(`日志无法校验：${error.message}`);
  }
  return result;
}

function inspectRunManifest(manifest, files, traces) {
  const summary = { formatVersion: null, outcome: "unverified", state: null, expectedSessionCount: null, reasons: [] };
  const expected = new Map();
  if (manifest.formatVersion === 1 && !Object.hasOwn(manifest, "runManifestFormatVersion")
    && !Object.hasOwn(manifest, "state") && !Object.hasOwn(manifest, "sessions")) {
    summary.reasons.push("旧版运行没有会话清单，仅检查发现的片段，运行级会话覆盖未知");
    return { summary, expected, legacy: true };
  }
  if (manifest.formatVersion !== 2) {
    summary.outcome = "invalid";
    summary.reasons.push("运行元信息版本与会话清单格式不一致");
    return { summary, expected, legacy: false };
  }
  summary.formatVersion = manifest.runManifestFormatVersion ?? null;
  if (Number.isSafeInteger(manifest.runManifestFormatVersion) && manifest.runManifestFormatVersion > 1) {
    summary.reasons.push("不支持的运行会话清单版本，运行级会话覆盖未知");
    return { summary, expected, legacy: false };
  }
  try {
    if (manifest.runManifestFormatVersion !== 1 || !["recording", "sealed", "failed"].includes(manifest.state)
      || !Array.isArray(manifest.sessions)) throw new Error("运行会话清单格式或状态无效");
    const identities = new Set();
    for (const entry of manifest.sessions) {
      if (!object(entry) || typeof entry.sessionId !== "string" || !entry.sessionId
        || entry.traceFile !== traceFilename(entry.sessionId) || entry.statusFile !== statusFilename(entry.traceFile)
        || identities.has(entry.sessionId) || expected.has(entry.traceFile)) {
        throw new Error("运行会话清单身份、文件名无效或重复");
      }
      identities.add(entry.sessionId);
      expected.set(entry.traceFile, entry);
    }
    summary.state = manifest.state;
    summary.expectedSessionCount = expected.size;
    summary.outcome = manifest.state === "sealed" ? "complete" : manifest.state === "failed" ? "invalid" : "unverified";
    if (manifest.state === "recording") summary.reasons.push("运行会话清单尚未封存，成员集合可能继续增长");
    if (manifest.state === "failed") summary.reasons.push("运行关闭时存在录制失败，清单未成功封存");
    for (const file of traces) {
      if (!expected.has(file)) {
        summary.outcome = "invalid";
        summary.reasons.push(`发现未登记的会话文件：${file}`);
      }
    }
    if (manifest.state === "sealed") {
      for (const entry of expected.values()) {
        for (const file of [entry.traceFile, entry.statusFile]) {
          if (!files.has(file)) {
            summary.outcome = "invalid";
            summary.reasons.push(`已封存的运行清单缺少文件：${file}`);
          }
        }
      }
    }
  } catch (error) {
    summary.outcome = "invalid";
    summary.reasons.push(error.message);
    expected.clear(); // Never use a partially validated membership list to choose files.
  }
  return { summary, expected, legacy: false };
}

export async function inspectRun(directory) {
  const runDir = resolve(directory);
  const report = { runDir, outcome: "unverified", exitCode: 2, reasons: [], sessions: [],
    runManifest: { formatVersion: null, outcome: "unverified", state: null, expectedSessionCount: null,
      reasons: ["无法确认运行级会话清单"] } };
  let entries;
  try { entries = await readdir(runDir); } catch (error) {
    report.reasons.push(`运行目录无法读取：${error.message}`);
    return report;
  }
  let manifest;
  let manifestVerified = false;
  let invalid = false;
  try {
    manifest = await readJson(join(runDir, "run.json"));
    if (!object(manifest) || ![1, 2].includes(manifest.formatVersion) || manifest.plugin !== "dsh-eval-lab"
      || typeof manifest.runId !== "string" || !manifest.runId || manifest.captureScope !== "live-events-only"
      || manifest.sessionFileNaming !== "sha256(sessionId).jsonl") throw new Error("运行元信息格式或身份无效");
    manifestVerified = manifest.statusFormatVersion === 1;
    if (!manifestVerified) report.reasons.push("旧版或不支持的运行状态格式，无法确认");
  } catch (error) {
    invalid = !error.code || error.code === "ERR_ENCODING_INVALID_ENCODED_DATA";
    report.reasons.push(`运行元信息无法校验：${error.message}`);
    manifest = undefined;
  }
  const files = new Set(entries);
  const traces = new Set();
  for (const entry of entries) {
    if (entry.endsWith(".jsonl") || entry.endsWith(".status.json")) {
      const file = entry.replace(/\.status\.json$/, ".jsonl");
      if (!/^[a-f0-9]{64}\.jsonl$/.test(file)) {
        invalid = true;
        report.reasons.push(`不符合会话哈希命名规则：${entry}`);
      } else traces.add(file);
    }
  }
  let inventory;
  if (manifest) {
    inventory = inspectRunManifest(manifest, files, traces);
    report.runManifest = inventory.summary;
    if (!inventory.legacy) report.reasons.push(...inventory.summary.reasons);
    if (inventory.summary.outcome === "invalid") invalid = true;
    for (const file of inventory.expected.keys()) traces.add(file);
  }
  if (entries.some((entry) => entry.endsWith(".tmp"))) report.reasons.push("存在未完成状态替换的临时文件");
  for (const file of [...traces].sort()) {
    const session = await inspectSession(runDir, file, manifest, files, inventory?.expected.get(file));
    if (inventory?.summary.state === "sealed" && inventory.expected.has(file)
      && (!files.has(file) || !files.has(statusFilename(file)))) {
      session.outcome = "invalid";
      session.reasons.push("已封存运行的登记会话缺少日志或状态文件");
    }
    report.sessions.push(session);
  }
  if (!report.sessions.length) report.reasons.push("没有可检查的录制片段");
  if (invalid || report.sessions.some((session) => session.outcome === "invalid")) {
    report.outcome = "invalid";
    report.exitCode = 1;
  } else if (manifestVerified && !report.reasons.length && report.sessions.every((session) => session.outcome === "complete")) {
    report.outcome = "complete";
    report.exitCode = 0;
  }
  return report;
}
