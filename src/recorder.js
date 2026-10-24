import { mkdirSync, writeFileSync } from "node:fs";
import { appendFile } from "node:fs/promises";
import { createHash, randomUUID } from "node:crypto";
import { isAbsolute, join } from "node:path";
import { pluginVersion } from "./metadata.js";
import { DEFAULT_MAX_EVENT_BYTES, DEFAULT_MAX_PENDING_BYTES, validateMaxEventBytes, validateMaxPendingBytes } from "./config.js";
import { statusFilename, writeStatus } from "./session-status.js";

export function traceFilename(sessionId) {
  return `${createHash("sha256").update(sessionId).digest("hex")}.jsonl`;
}

// Each session owns an ordered write queue. The append observer never awaits I/O.
export function createRecorder({ outputDir, maxPendingBytes = DEFAULT_MAX_PENDING_BYTES,
  maxEventBytes = DEFAULT_MAX_EVENT_BYTES, onError = () => {} } = {}) {
  if (typeof outputDir !== "string" || !isAbsolute(outputDir)) {
    throw new TypeError("eval-lab: outputDir 必须是绝对路径");
  }
  validateMaxPendingBytes(maxPendingBytes);
  validateMaxEventBytes(maxEventBytes);
  const runId = randomUUID();
  const runDir = join(outputDir, runId);
  mkdirSync(runDir, { recursive: true });
  const runPath = join(runDir, "run.json");
  const metadata = {
    formatVersion: 2,
    statusFormatVersion: 1,
    runManifestFormatVersion: 1,
    plugin: "dsh-eval-lab",
    pluginVersion,
    runId,
    startedAt: new Date().toISOString(),
    captureScope: "live-events-only",
    sessionFileNaming: "sha256(sessionId).jsonl",
    maxPendingBytes,
    maxEventBytes,
  };
  writeFileSync(runPath, JSON.stringify({ ...metadata, state: "recording", sessions: [] }, null, 2) + "\n", { flag: "wx" });

  const states = new Map();
  let closed = false;
  let closePromise;
  let pendingBytes = 0;
  let manifestPending = Promise.resolve(true);
  let registrationBatch = null;
  let manifestError = null;

  function persistRun(phase) {
    manifestPending = manifestPending.then(async () => {
      // Members observed before this write starts share its barrier. Members
      // arriving during I/O join the next batch, which holds no snapshot yet.
      if (phase === "recording") registrationBatch = null;
      if (manifestError) return false;
      const snapshot = { ...metadata, state: phase, sessions: [...states.values()].map((state) => ({
        sessionId: state.sessionId, traceFile: state.traceFile, statusFile: statusFilename(state.traceFile),
      })) };
      try { await writeStatus(runPath, snapshot); return true; } catch (error) {
        manifestError = error;
        try { onError(error, null); } catch { /* Preserve the run-level error. */ }
        return false;
      }
    });
    return manifestPending;
  }

  function fail(state, error) {
    if (state.error) return;
    state.error = error;
    try { onError(error, state.sessionId); } catch { /* Preserve the recording error. */ }
  }

  function persist(state, phase, counts = state) {
    return writeStatus(join(runDir, statusFilename(state.traceFile)), {
      statusFormatVersion: 1, runId, sessionId: state.sessionId,
      captureScope: "live-events-only", traceFile: state.traceFile, state: phase,
      receivedCount: counts.receivedCount, acceptedCount: counts.acceptedCount,
      writtenCount: state.writtenCount, writtenBytes: state.writtenBytes,
      firstSeq: state.firstSeq, lastSeq: state.lastSeq,
      sha256: state.hash.copy().digest("hex"), updatedAt: new Date().toISOString(),
      error: state.error ? { message: String(state.error.message ?? state.error), code: state.error.code ?? null } : null,
    });
  }

  function enqueue(state, work) {
    state.pending = state.pending.then(async () => {
      try { await work(); } catch (error) { fail(state, error); }
      if (state.registered && state.error && !state.failureSaved) {
        // Failure persistence may also fail; an old recording/missing status stays unverified.
        try { await persist(state, "failed"); state.failureSaved = true; } catch { /* flush rejects below */ }
      }
    });
    return state.pending;
  }

  function record(sessionId, event) {
    if (closed) throw new Error("eval-lab: recorder 已关闭");
    if (typeof sessionId !== "string" || !sessionId) {
      throw new TypeError("eval-lab: sessionId 必须是非空字符串");
    }
    if (manifestError) return false;
    let state = states.get(sessionId);
    if (!state) {
      state = {
        sessionId, traceFile: traceFilename(sessionId), pending: Promise.resolve(), error: null, registered: false,
        receivedCount: 0, acceptedCount: 0, writtenCount: 0, writtenBytes: 0,
        firstSeq: null, lastSeq: null, acceptedLastSeq: null, hash: createHash("sha256"),
      };
      states.set(sessionId, state);
      const registration = registrationBatch ??= persistRun("recording");
      enqueue(state, async () => {
        // No trace or status file may precede successful membership persistence.
        state.registered = await registration;
        if (state.registered && !state.error) await persist(state, "recording");
      });
    }
    if (state.error) return false;
    state.receivedCount++;
    let line;
    let seq;
    try {
      // Size the frozen envelope before allocating a Buffer or parsing its seq.
      // JSON.stringify still uses synchronous CPU and temporary memory.
      const text = JSON.stringify({ formatVersion: 1, runId, sessionId, event }) + "\n";
      const bytes = Buffer.byteLength(text, "utf8");
      if (bytes > maxEventBytes) {
        const error = new Error(`eval-lab: 单条事件 ${bytes} 字节超过 maxEventBytes=${maxEventBytes}`);
        error.code = "EVENT_BYTES_LIMIT";
        throw error;
      }
      seq = JSON.parse(text).event?.seq;
      if (!Number.isSafeInteger(seq) || seq < 0 || (state.acceptedLastSeq !== null && seq <= state.acceptedLastSeq)) {
        throw new Error("eval-lab: event.seq 必须是严格递增的非负安全整数");
      }
      if (pendingBytes + bytes > maxPendingBytes) {
        const error = new Error(`eval-lab: 待写入字节超过 maxPendingBytes=${maxPendingBytes}`);
        error.code = "PENDING_BYTES_LIMIT";
        throw error;
      }
      line = Buffer.from(text, "utf8");
    } catch (error) {
      fail(state, error);
      enqueue(state, async () => {});
      return false;
    }
    // A custom toJSON can re-enter the recorder.
    if (closed) throw new Error("eval-lab: recorder 已关闭");
    if (state.error) return false;
    state.acceptedCount++;
    state.acceptedLastSeq = seq;
    pendingBytes += line.length;
    enqueue(state, async () => {
      try {
        if (!state.registered || state.error) return;
        await appendFile(join(runDir, state.traceFile), line);
        state.hash.update(line);
        state.writtenCount++;
        state.writtenBytes += line.length;
        state.firstSeq ??= seq;
        state.lastSeq = seq;
      } finally { pendingBytes -= line.length; }
    });
    return true;
  }

  async function wait(selected, checkpoints) {
    await Promise.all(checkpoints);
    const failures = selected.filter((state) => state.error).map((state) => state.error);
    if (manifestError) failures.push(manifestError);
    if (failures.length) throw new AggregateError(failures, "eval-lab: 日志不完整，不能作为有效评测输入");
  }

  function flush(sessionId) {
    if (closed) return closePromise;
    const selected = sessionId === undefined ? [...states.values()] : [states.get(sessionId)].filter(Boolean);
    const checkpoints = selected.map((state) => {
      const counts = { receivedCount: state.receivedCount, acceptedCount: state.acceptedCount };
      return enqueue(state, () => !state.registered || state.error ? undefined : persist(state, "recording", counts));
    });
    return wait(selected, checkpoints);
  }

  function close() {
    if (closePromise) return closePromise;
    closed = true;
    const selected = [...states.values()];
    const checkpoints = selected.map((state) => enqueue(state, () => !state.registered || state.error ? undefined : persist(state, "sealed")));
    closePromise = (async () => {
      await Promise.all(checkpoints);
      await persistRun(selected.some((state) => state.error) || manifestError ? "failed" : "sealed");
      await wait(selected, []);
    })();
    return closePromise;
  }

  return { runId, runDir, record, flush, close };
}
