// Scripted virtual file mutations. Real pipes and recorder; no Harness or model calls.
import { readFile, writeFile } from "node:fs/promises";
import { basename, join } from "node:path";
import { createInterface } from "node:readline";
import { createRecorder } from "../../src/recorder.js";
import { summarizeProtocol } from "../case-host.js";

const directory = process.argv[3];
const task = JSON.parse(await readFile(join(directory, "case.json"), "utf8"));
let options = {};
try { options = JSON.parse(await readFile(join(directory, "synthetic.json"), "utf8")); }
catch (error) { if (error.code !== "ENOENT") throw error; }
const scenario = options.scenario ?? task.caseId;
const edit = ["edit", { path: "settings.txt", oldText: "mode=draft", newText: "mode=ready" }];
const remove = ["delete", { path: "obsolete.txt" }];
const read = ["read", { path: "settings.txt" }];
const rename = ["rename", { path: "draft.txt", destination: "archive/final.txt" }];
const renameConfirmation = [["rename", { path: "draft.txt", destination: "guard.txt" }],
  rename, ["read", { path: "archive/final.txt" }]];
const scenarios = {
  "rename-confirmation": renameConfirmation,
  "rename-timeout-retry": [rename, ["read", { path: "draft.txt" }],
    ["read", { path: "archive/final.txt" }], rename, ["read", { path: "archive/final.txt" }]],
  "rename-timeout-skip-readbacks": [rename, rename, ["read", { path: "archive/final.txt" }]],
  "rename-no-overwrite": [["rename", { path: "draft.txt", destination: "guard.txt" }],
    ["rename", { path: "draft.txt", destination: "archive/final.txt" }], ["read", { path: "archive/final.txt" }]],
  "edit-delete": [edit, remove, read],
  "edit-delete-timeout": [edit, edit, remove, remove, read],
  "edit-delete-errors": [["delete", { path: "missing.txt" }],
    ["edit", { path: "settings.txt", oldText: "flag=off", newText: "flag=on" }]],
};
if (!Object.hasOwn(scenarios, scenario)) throw new Error("Unsupported synthetic mutation case");
const sessionId = `synthetic-${basename(directory)}`;
const recorder = createRecorder({ ...task.recorder, outputDir: join(directory, "traces") });
const input = createInterface({ input: process.stdin });
const iterator = input[Symbol.asyncIterator]();
let seq = 0, index = 0;
const record = (type, data) => recorder.record(sessionId, { seq: seq++, type, data });
const emit = (message) => process.stdout.write(JSON.stringify(message) + "\n");
const route = { sessionId, provider: task.configRef.provider, model: task.configRef.model };
emit({ type: "selection", sessionId });
emit({ type: "request-route", ...route });
record("user/message", { source: { kind: "user" }, content: [{ type: "text", text: task.input }] });
record("request/header", { header: { config: task.configRef } });
for (const [operation, args] of scenarios[scenario]) {
  const requestId = `call-${index++}`;
  record("tool/call", { callId: requestId, name: `eval_${operation}`, arguments: JSON.stringify(args) });
  emit({ type: "tool-request", bridgeVersion: 1, requestId, caseRunId: basename(directory), sessionId, operation, arguments: args });
  const response = JSON.parse((await iterator.next()).value);
  if (response.type !== "tool-response" || response.requestId !== requestId) throw new Error("Unexpected response");
  // The real Tools pipeline presents thrown bridge errors with an Error: prefix.
  record("tool/result", { message: { toolCallId: requestId, isError: response.isError,
    content: [{ type: "text", text: response.isError ? `Error: ${response.text}` : response.text }] } });
}
const decoratedConfirmation = ["rename-confirmation", "rename-timeout-retry"].includes(scenario);
let answer = "done";
if (scenario === "edit-delete-errors") answer = "rejected";
else if (decoratedConfirmation) answer = "**Done.**";
if (Object.hasOwn(options, "finalText")) {
  if (typeof options.finalText !== "string") throw new Error("Synthetic finalText must be a string");
  answer = options.finalText;
}
const reason = { kind: "completed" };
record("assistant/message", { message: { content: [{ type: "text", text: answer }] } });
record("turn/end", { reason });
await recorder.close();
const frames = [{ type: "session", sessionId }, { type: "status", phase: "turn_end", reason }, { type: "final", text: answer }];
await writeFile(join(directory, "host-result.json"), JSON.stringify({ childClosed: true, sessionId, requests: [route],
  forceStopped: false, exitCode: 0, signal: null, error: null,
  protocol: summarizeProtocol(frames.map(JSON.stringify).join("\n"), sessionId) }));
input.close();
process.stdin.pause();
