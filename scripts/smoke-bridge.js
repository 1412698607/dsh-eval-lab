// Actual Cordis/tools registry + fork IPC + Python state, without a model request.
import assert from "node:assert/strict";
import { fork } from "node:child_process";
import { createRequire } from "node:module";
import { join } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { locateHost, loadHost, HOST_FIBER_ACTIVE } from "./lib/host.js";
import { createToolBridge, registerStatefulTools } from "./lib/tool-bridge.js";

const [mode, caseRunId] = process.argv.slice(2);
if (mode === "child") {
  const modulesDir = await locateHost();
  const { Context } = await loadHost(modulesDir);
  const requireHost = createRequire(join(modulesDir, "__bridge_smoke__.cjs"));
  const { default: SystemPrompt } = requireHost("@deepseek-ai/dsh-system-prompt");
  const { default: Tools, defineTool } = requireHost("@deepseek-ai/dsh-tools");
  const ctx = new Context();
  const prompt = await ctx.plugin(SystemPrompt, {});
  const tools = await ctx.plugin(Tools);
  assert.equal(tools.state, HOST_FIBER_ACTIVE);
  const bridge = createToolBridge(process, caseRunId, (message) => { throw new Error(message); });
  try {
    registerStatefulTools(ctx, defineTool, bridge);
    const exec = { agent: { session: { id: "bridge-smoke-session" } }, signal: new AbortController().signal };
    const read = (path) => ctx.tools.get("eval_read").execute({ path }, exec);
    await assert.rejects(read("missing.md"), /NOT_FOUND/);
    assert.equal(await ctx.tools.get("eval_list").execute({ path: "." }, exec), "project.md");
    await assert.rejects(read("project.md"), /TEMPORARY_READ_FAILURE/);
    assert.equal(await read("project.md"), "projectName: dsh-stateful-retry\n");
  } finally {
    bridge.close();
    await tools.dispose();
    await prompt.dispose();
    process.disconnect();
  }
} else {
  const child = fork(fileURLToPath(import.meta.url), ["child", caseRunId], {
    stdio: ["ignore", "inherit", "inherit", "ipc"], windowsHide: true,
  });
  const input = createInterface({ input: process.stdin });
  child.on("message", (message) => {
    if (message.type === "tool-request") process.stdout.write(JSON.stringify(message) + "\n");
  });
  input.on("line", (line) => { if (child.connected) child.send(JSON.parse(line)); });
  const code = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("close", resolve);
  });
  input.close();
  process.stdin.pause();
  process.exitCode = code;
}
