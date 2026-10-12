import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdir, readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import * as plugin from "../../src/index.js";
import { pluginVersion } from "../../src/metadata.js";
import { traceFilename } from "../../src/recorder.js";
import { statusFilename } from "../../src/session-status.js";
import { inspectRun } from "../../src/inspect.js";
import { HOST_FIBER_ACTIVE, loadHost } from "./host.js";

// outputDir must be unique to this check; never select a previous run's trace.
export async function runHostSmoke({ modulesDir, outputDir, failWrite = false }) {
  const { Context, SessionStore, SessionId, versions } = await loadHost(modulesDir);
  await mkdir(outputDir, { recursive: true });
  assert.deepEqual(await readdir(outputDir), [], "检查目录必须为空");
  const ctx = new Context();
  const sessionFiber = await ctx.plugin(SessionStore);
  let fiber;
  try {
    assert.equal(sessionFiber.state, HOST_FIBER_ACTIVE, "会话服务必须完成启动");
    fiber = await ctx.plugin(plugin, { outputDir });
    assert.equal(fiber.state, HOST_FIBER_ACTIVE, "插件必须完成启动后才能接收会话事件");
    const runs = await readdir(outputDir);
    assert.equal(runs.length, 1, "本次挂载应只产生一个运行目录");
    const runDir = join(outputDir, runs[0]);
    const manifest = JSON.parse(await readFile(join(runDir, "run.json"), "utf8"));
    assert.equal(manifest.runId, runs[0]);
    assert.equal(manifest.pluginVersion, pluginVersion);
    const session = ctx.sessions.create(SessionId(`eval-lab-smoke-${randomUUID()}`));
    const tracePath = join(runDir, traceFilename(session.id));
    if (failWrite) await mkdir(tracePath); // Force a real append error, not a mocked reporter.
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
    if (failWrite) {
      await assert.rejects(ctx.sessions.flush(session), AggregateError);
    } else {
      assert.equal(await ctx.sessions.flush(session), true);
      const rows = (await readFile(tracePath, "utf8")).trim().split("\n").map(JSON.parse);
      assert.deepEqual(rows.map((row) => row.event), expected);
    }
    assert.equal(JSON.parse(await readFile(join(runDir, statusFilename(traceFilename(session.id))), "utf8")).state,
      failWrite ? "failed" : "recording");
    // Cordis may swallow disposer errors. Validate persisted evidence after unloading.
    await fiber.dispose();
    fiber = undefined;
    const inspection = await inspectRun(runDir);
    assert.equal(inspection.exitCode, failWrite ? 1 : 0);
    return { tracePath, eventCount: expected.length, versions };
  } finally {
    try {
      // Cordis 4.0.4 catches disposer errors; flush above is the failure barrier.
      if (fiber) await fiber.dispose();
    } finally { await sessionFiber.dispose(); }
  }
}
