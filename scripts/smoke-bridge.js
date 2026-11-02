// Actual Cordis/tools registry + fork IPC + Python state, without a model request.
import assert from "node:assert/strict";
import { fork } from "node:child_process";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { join } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { locateHost, loadHost, HOST_FIBER_ACTIVE } from "./lib/host.js";
import { createToolBridge, registerStatefulTools } from "./lib/tool-bridge.js";

const [mode, caseRunId, scenario = "reads"] = process.argv.slice(2);
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
  const task = JSON.parse(await readFile(new URL(`../fixtures/evaluation/${scenario === "writes" ? "write-retry" : "retry-read"}.case.json`, import.meta.url), "utf8"));
  const bridge = createToolBridge(process, caseRunId, (message) => { throw new Error(message); }, undefined, task.budget);
  try {
    registerStatefulTools(ctx, defineTool, bridge, task.environment.stateful.tools);
    const exec = { agent: { session: { id: "bridge-smoke-session" } }, signal: new AbortController().signal };
    const read = (path) => ctx.tools.get("eval_read").execute({ path }, exec);
    if (scenario === "writes") {
      const write = () => ctx.tools.get("eval_write").execute({ path: "result.txt", content: "done\n" }, exec);
      await assert.rejects(write(), /TOOL_TIMEOUT/);
      assert.equal(await read("result.txt"), "old\n");
      assert.equal(await write(), "WROTE: result.txt");
      assert.equal(await read("result.txt"), "done\n");
      const controller = new AbortController();
      const cancelled = ctx.tools.get("eval_write").execute({ path: "result.txt", content: "late" },
        { ...exec, signal: controller.signal });
      setTimeout(() => controller.abort(), 25);
      await assert.rejects(cancelled, /cancelled/);
      assert.equal(await read("result.txt"), "done\n");
    } else {
      await assert.rejects(read("missing.md"), /NOT_FOUND/);
      assert.equal(await ctx.tools.get("eval_list").execute({ path: "." }, exec), "project.md");
      await assert.rejects(read("project.md"), /TEMPORARY_READ_FAILURE/);
      assert.equal(await read("project.md"), "projectName: dsh-stateful-retry\n");
    }
  } finally {
    bridge.close();
    await tools.dispose();
    await prompt.dispose();
    process.disconnect();
  }
} else {
  const child = fork(fileURLToPath(import.meta.url), ["child", caseRunId, scenario], {
    stdio: ["ignore", "inherit", "inherit", "ipc"], windowsHide: true,
  });
  const input = createInterface({ input: process.stdin });
  child.on("message", (message) => {
    if (["tool-request", "tool-cancel"].includes(message.type)) process.stdout.write(JSON.stringify(message) + "\n");
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
