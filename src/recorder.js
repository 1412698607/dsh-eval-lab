import { mkdirSync, writeFileSync } from "node:fs";
import { appendFile } from "node:fs/promises";
import { createHash, randomUUID } from "node:crypto";
import { isAbsolute, join } from "node:path";
import { pluginVersion } from "./metadata.js";

export function traceFilename(sessionId) {
  return `${createHash("sha256").update(sessionId).digest("hex")}.jsonl`;
}

// Each session owns an ordered write queue. The append observer never awaits I/O.
export function createRecorder({ outputDir, onError = () => {} } = {}) {
  if (typeof outputDir !== "string" || !isAbsolute(outputDir)) {
    throw new TypeError("eval-lab: outputDir 必须是绝对路径");
  }
  const runId = randomUUID();
  const runDir = join(outputDir, runId);
  mkdirSync(runDir, { recursive: true });
  writeFileSync(join(runDir, "run.json"), JSON.stringify({
    formatVersion: 1,
    plugin: "dsh-eval-lab",
    pluginVersion,
    runId,
    startedAt: new Date().toISOString(),
    captureScope: "live-events-only",
    sessionFileNaming: "sha256(sessionId).jsonl",
  }, null, 2) + "\n", { flag: "wx" });

  const states = new Map();
  let closed = false;

  function fail(state, error, sessionId) {
    if (state.error) return;
    state.error = error;
    // A failed reporter must not turn the write queue into an unhandled rejection.
    try { onError(error, sessionId); } catch { /* flush still reports the original failure */ }
  }

  function record(sessionId, event) {
    if (closed) throw new Error("eval-lab: recorder 已关闭");
    if (typeof sessionId !== "string" || !sessionId) {
      throw new TypeError("eval-lab: sessionId 必须是非空字符串");
    }
    let state = states.get(sessionId);
    if (!state) {
      state = { pending: Promise.resolve(), error: null };
      states.set(sessionId, state);
    }
    if (state.error) return false;
    let line;
    try {
      // Serialize at observation time, before another caller can mutate the input.
      line = JSON.stringify({ formatVersion: 1, runId, sessionId, event }) + "\n";
    } catch (error) {
      fail(state, error, sessionId);
      return false;
    }
    state.pending = state.pending.then(async () => {
      if (state.error) return;
      await appendFile(join(runDir, traceFilename(sessionId)), line, "utf8");
    }).catch((error) => fail(state, error, sessionId));
    return true;
  }

  async function flush(sessionId) {
    const selected = sessionId === undefined
      ? [...states.values()]
      : [states.get(sessionId)].filter(Boolean);
    // Capture a checkpoint: concurrent later appends belong to the next flush.
    await Promise.all(selected.map((state) => state.pending));
    const failures = selected.filter((state) => state.error).map((state) => state.error);
    if (failures.length) {
      throw new AggregateError(failures, "eval-lab: 日志不完整，不能作为有效评测输入");
    }
  }

  async function close() {
    closed = true;
    await flush();
  }

  return { runId, runDir, record, flush, close };
}
