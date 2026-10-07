import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readdir, readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import * as plugin from "../src/index.js";
import { traceFilename } from "../src/recorder.js";

// Reuse installed packages without installing or changing a user's DSH profile.
async function locateHost() {
  if (process.argv[2]) return resolve(process.argv[2]);
  const cache = process.env.LOCALAPPDATA
    ? join(process.env.LOCALAPPDATA, "npm-cache", "_npx") : null;
  if (cache && existsSync(cache)) {
    const entries = await readdir(cache, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const modules = join(cache, entry.name, "node_modules");
      const manifestPath = join(modules, "@deepseek-ai", "dsh-session", "package.json");
      if (!existsSync(manifestPath)) continue;
      const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
      if (manifest.version === "0.2.0-rc.2") return modules;
    }
  }
  throw new Error("未找到 DSH 0.2.0-rc.2 缓存。传入已安装 DSH 的 node_modules 绝对路径。");
}

const modules = await locateHost();
const requireHost = createRequire(join(dirname(modules), "package.json"));
const { Context } = await import(pathToFileURL(requireHost.resolve("@deepseek-ai/cordis")).href);
const { default: SessionStore, SessionId } = await import(pathToFileURL(requireHost.resolve("@deepseek-ai/dsh-session")).href);
const ctx = new Context();
const outputDir = resolve("runs", "host-smoke");
const sessionFiber = await ctx.plugin(SessionStore);
const fiber = await ctx.plugin(plugin, { outputDir });
assert.equal(fiber.state, 2, "插件必须完成启动后才能接收会话事件");
try {
  const session = ctx.sessions.create(SessionId(`eval-lab-smoke-${Date.now()}`));
  const expected = [];
  expected.push(session.append("turn/start", { turn: 1 }));
  expected.push(session.append("step/start", { turn: 1, step: 1 }));
  expected.push(session.append("tool/call", {
    turn: 1, step: 1, callId: "smoke-call", name: "read_file", arguments: '{"path":"README.md"}',
  }));
  expected.push(session.append("tool/result", {
    turn: 1, step: 1,
    message: {
      id: "smoke-result", role: "tool", toolCallId: "smoke-call",
      source: { kind: "tool", callId: "smoke-call" },
      content: [{ type: "text", text: "# dsh-eval-lab" }],
    },
  }, { surfaceOp: "append" }));
  expected.push(session.append("step/end", { turn: 1, step: 1 }));
  expected.push(session.append("turn/end", { turn: 1, reason: { kind: "completed" } }));
  assert.equal(await ctx.sessions.flush(session), true);
  const runs = await readdir(outputDir);
  let tracePath;
  for (const run of runs) {
    const candidate = join(outputDir, run, traceFilename(session.id));
    if (existsSync(candidate)) { tracePath = candidate; break; }
  }
  assert.ok(tracePath, "真实会话事件应该生成 JSONL 文件");
  const rows = (await readFile(tracePath, "utf8")).trim().split("\n").map(JSON.parse);
  assert.deepEqual(rows.map((row) => row.event), expected);
  console.info("DSH 真实 SessionStore + Cordis 插件接入验证通过。");
  console.info(`日志：${tracePath}`);
} finally {
  await fiber.dispose();
  await sessionFiber.dispose();
}
