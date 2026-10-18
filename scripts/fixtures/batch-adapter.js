// Synthetic adapter for Python batch integration tests. No Harness or model call.
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { basename, join } from "node:path";
import { createInterface } from "node:readline";
import { createRecorder } from "../../src/recorder.js";
import { summarizeProtocol } from "../case-host.js";

const directory = process.argv[3];
const caseData = JSON.parse(await readFile(join(directory, "case.json"), "utf8"));
const sessionId = `synthetic-${basename(directory)}`;
const recorder = createRecorder({ outputDir: join(directory, "traces") });
let seq = 0;
const record = (type, data) => recorder.record(sessionId, { seq: seq++, type, data });
const emit = (value) => process.stdout.write(JSON.stringify(value) + "\n");
const input = createInterface({ input: process.stdin });
const iterator = input[Symbol.asyncIterator]();
emit({ type: "selection", sessionId, selection: caseData.configRef });
const route = { sessionId, provider: caseData.configRef.provider, model: caseData.configRef.model };
emit({ type: "request-route", ...route });
record("turn/start", {});
record("user/message", { source: { kind: "user" }, content: [{ type: "text", text: caseData.input }] });
record("request/header", { header: { config: caseData.configRef } });
let reason = { kind: "completed" };
let answer = "no-file";
if (["WAIT_FOR_CANCEL", "WAIT_FOR_TIMEOUT"].includes(caseData.input)) {
  if (caseData.input === "WAIT_FOR_CANCEL") emit({ type: "streaming", sessionId });
  const command = JSON.parse((await iterator.next()).value);
  if (!["cancel", "timeout", "shutdown"].includes(command.type)) throw new Error("Expected stop command");
  reason = { kind: "aborted", reason: { kind: "user" } };
} else {
  // Both reads actually cross the Python bridge, so every fresh environment must fail once.
  for (let index = 0; index < 2; index++) {
    const requestId = `synthetic-read-${index}`;
    const args = { path: "project.md" };
    record("tool/call", { callId: requestId, name: "eval_read", arguments: JSON.stringify(args) });
    emit({ type: "tool-request", bridgeVersion: 1, requestId, caseRunId: basename(directory), sessionId,
      operation: "read", arguments: args });
    const response = JSON.parse((await iterator.next()).value);
    if (response.type !== "tool-response" || response.requestId !== requestId) throw new Error("Unexpected response");
    record("tool/result", { message: { toolCallId: requestId, isError: response.isError,
      content: [{ type: "text", text: response.text }] } });
    if (!response.isError) answer = response.text.match(/projectName:\s*(\S+)/)?.[1] ?? "no-field";
  }
}
record("assistant/message", { message: { content: [{ type: "text", text: answer }] } });
record("turn/end", { reason });
await recorder.close();
// Distinct owned directories are also used by the real adapter; make isolation observable in tests.
await mkdir(join(directory, "home"));
await writeFile(join(directory, "home", "synthetic-session.txt"), sessionId, { flag: "wx" });
const frames = [{ type: "session", sessionId }, { type: "status", phase: "turn_end", reason }, { type: "final", text: answer }];
await writeFile(join(directory, "host-result.json"), JSON.stringify({ childPid: null, childClosed: true,
  sessionId, requests: [route], forceStopped: false, exitCode: 0, signal: null, error: null,
  protocol: summarizeProtocol(frames.map(JSON.stringify).join("\n"), sessionId) }));
input.close();
process.stdin.pause();
