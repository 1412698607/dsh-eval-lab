// Synthetic write/retry adapter. Real pipes and recorder; no Harness or model calls.
import { readFile, writeFile } from "node:fs/promises";
import { basename, join } from "node:path";
import { createInterface } from "node:readline";
import { createRecorder } from "../../src/recorder.js";
import { summarizeProtocol } from "../case-host.js";

const directory = process.argv[3];
const task = JSON.parse(await readFile(join(directory, "case.json"), "utf8"));
const sessionId = `synthetic-${basename(directory)}`;
const recorder = createRecorder({ outputDir: join(directory, "traces") });
const input = createInterface({ input: process.stdin });
const iterator = input[Symbol.asyncIterator]();
let seq = 0;
const record = (type, data) => recorder.record(sessionId, { seq: seq++, type, data });
const emit = (message) => process.stdout.write(JSON.stringify(message) + "\n");
const route = { sessionId, provider: task.configRef.provider, model: task.configRef.model };
emit({ type: "selection", sessionId });
emit({ type: "request-route", ...route });
record("user/message", { source: { kind: "user" }, content: [{ type: "text", text: task.input }] });
record("request/header", { header: { config: task.configRef } });
for (let index = 0; index < 3; index++) {
  const operation = index < 2 ? "write" : "read";
  const args = { path: "result.txt", ...(operation === "write" ? { content: "done\n" } : {}) };
  const requestId = `call-${index}`;
  record("tool/call", { callId: requestId, name: `eval_${operation}`, arguments: JSON.stringify(args) });
  emit({ type: "tool-request", bridgeVersion: 1, requestId, caseRunId: basename(directory), sessionId, operation, arguments: args });
  const response = JSON.parse((await iterator.next()).value);
  if (response.type !== "tool-response" || response.requestId !== requestId) throw new Error("Unexpected response");
  record("tool/result", { message: { toolCallId: requestId, isError: response.isError,
    content: [{ type: "text", text: response.text }] } });
}
const reason = { kind: "completed" };
record("assistant/message", { message: { content: [{ type: "text", text: "done" }] } });
record("turn/end", { reason });
await recorder.close();
const frames = [{ type: "session", sessionId }, { type: "status", phase: "turn_end", reason }, { type: "final", text: "done" }];
await writeFile(join(directory, "host-result.json"), JSON.stringify({ childClosed: true, sessionId, requests: [route],
  forceStopped: false, exitCode: 0, signal: null, error: null,
  protocol: summarizeProtocol(frames.map(JSON.stringify).join("\n"), sessionId) }));
input.close();
process.stdin.pause();
