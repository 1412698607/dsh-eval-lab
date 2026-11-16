// Real case-host and fork IPC with scripted tools; no Harness or model dependency.
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createRecorder } from "../../src/recorder.js";
import { supportedSessionVersion } from "../../src/metadata.js";
import { runCase } from "../case-host.js";
import { supportedCordisVersion } from "../lib/host.js";
import { createToolBridge, registerStatefulTools } from "../lib/tool-bridge.js";

const fixture = fileURLToPath(import.meta.url);
const emit = (message) => process.stdout.write(JSON.stringify(message) + "\n");

async function runFixture(directory) {
  // validateHost reads version manifests only. These do not supply a Harness runtime.
  const modulesDir = join(directory, "fixture-modules");
  for (const [name, version] of [["dsh-session", supportedSessionVersion], ["cordis", supportedCordisVersion]]) {
    const packageDir = join(modulesDir, "@deepseek-ai", name);
    await mkdir(packageDir, { recursive: true });
    await writeFile(join(packageDir, "package.json"), JSON.stringify({ version }), { flag: "wx" });
  }
  await writeFile(join(directory, "setup.json"), JSON.stringify({
    cli: fixture, cliVersion: "synthetic-ipc", modulesDir, home: directory,
    workspace: directory, controlPatch: "unused-synthetic-patch",
  }), { flag: "wx" });
  await runCase(directory);
}

async function runChild() {
  const directory = dirname(process.env.DSH_EVAL_OUTPUT_DIR);
  const task = JSON.parse(await readFile(join(directory, "case.json"), "utf8"));
  const caseRunId = basename(directory), sessionId = `synthetic-${caseRunId}`;
  const route = { sessionId, provider: task.configRef.provider, model: task.configRef.model };
  const recorder = createRecorder({ ...task.recorder, outputDir: join(directory, "traces") });
  let seq = 0;
  const record = (type, data) => recorder.record(sessionId, { seq: seq++, type, data });
  const failures = [], controls = [];
  const initialMessageListeners = process.listenerCount("message");
  const initialDisconnectListeners = process.listenerCount("disconnect");
  const bridge = createToolBridge(process, caseRunId, (message) => {
    failures.push(message);
    if (process.connected) process.send({ type: "bridge-error", message });
  });
  const registered = new Map();
  registerStatefulTools({ tools: { register: (tool) => registered.set(tool.name, tool) } },
    (tool) => tool, bridge, ["eval_edit", "eval_delete"]);
  const controller = new AbortController();
  const exec = { agent: { session: { id: sessionId } }, signal: controller.signal };
  let finishStop;
  const stopped = new Promise((res) => { finishStop = res; });
  const control = (message) => {
    if (!["cancel", "shutdown"].includes(message?.type)) return;
    controls.push(message);
    if (message.type === "cancel" && message.sessionId !== sessionId) throw new Error("Wrong cancel session");
    if (process.env.DSH_TEST_BRIDGE_STOP !== "close") controller.abort();
    bridge.close();
    finishStop();
  };
  process.on("message", control);
  process.send({ type: "selection", sessionId, selection: task.configRef });
  process.send({ type: "request-route", ...route });
  emit({ type: "session", sessionId });
  record("user/message", { source: { kind: "user" }, content: [{ type: "text", text: task.input }] });
  record("request/header", { header: { config: task.configRef } });
  const call = async (name, args, callId) => {
    record("tool/call", { callId, name, arguments: JSON.stringify(args) });
    try {
      const value = await registered.get(name).execute(args, exec);
      record("tool/result", { message: { toolCallId: callId, isError: false,
        content: [{ type: "text", text: value }] } });
      return value;
    } catch (error) {
      record("tool/result", { message: { toolCallId: callId, isError: true,
        content: [{ type: "text", text: `Error: ${error.message}` }] } });
      throw error;
    }
  };
  const pending = Promise.allSettled([
    call("eval_edit", { path: "settings.txt", oldText: "mode=draft", newText: "mode=ready" }, "ipc-edit"),
    call("eval_delete", { path: "obsolete.txt" }, "ipc-delete"),
  ]);
  await stopped;
  const results = (await pending).map((result) => result.status === "rejected"
    ? { status: result.status, reason: result.reason.message } : result);
  process.off("message", control);
  const reason = { kind: "aborted", reason: { kind: "user" } };
  record("turn/end", { reason });
  await recorder.close();
  await writeFile(join(directory, "tool-budget-proof.json"), JSON.stringify({
    childPid: process.pid, modelCalled: false, HarnessRuntimeUsed: false, results, controls, failures,
    listeners: { before: { message: initialMessageListeners, disconnect: initialDisconnectListeners },
      after: { message: process.listenerCount("message"), disconnect: process.listenerCount("disconnect") } },
    messageListenersRestored: process.listenerCount("message") === initialMessageListeners,
    disconnectListenersRestored: process.listenerCount("disconnect") === initialDisconnectListeners,
  }, null, 2) + "\n", { flag: "wx" });
  emit({ type: "status", phase: "turn_end", reason });
  emit({ type: "final", text: "" });
  process.disconnect();
}

if (process.argv[2] === "run") await runFixture(resolve(process.argv[3]));
else if (process.connected) await runChild();
else throw new Error("Usage: tool-budget-ipc.js run <case-run-dir>");
