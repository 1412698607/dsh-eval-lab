import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { checkpoint, isUserSubmission, runWeb } from "../scripts/web-lifecycle-live.js";
import { apply as observe } from "../scripts/fixtures/web-lifecycle-observer.js";
import { createRecorder } from "../src/recorder.js";

async function startupFixture() {
  const directory = await mkdtemp(join(tmpdir(), "web-live-startup-"));
  // Version metadata only. The injected terminal launches a real bounded Node child,
  // without importing Harness, native ConPTY, credentials or model adapters.
  for (const [name, version] of [["dsh-session", "0.2.0-rc.2"], ["cordis", "4.0.4"]]) {
    const path = join(directory, "modules", "@deepseek-ai", name);
    await mkdir(path, { recursive: true });
    await writeFile(join(path, "package.json"), JSON.stringify({ version }));
  }
  await mkdir(join(directory, "home"));
  await writeFile(join(directory, "observations.jsonl"), "");
  await writeFile(join(directory, "setup.json"), JSON.stringify({ webLiveSetupVersion: 1,
    scenario: "normal-exit", modulesDir: join(directory, "modules"), cli: "test-only",
    home: join(directory, "home"), workspace: directory, patch: "test-only",
    cliVersion: "0.2.0-rc.2", nodePtyVersion: "test-process-adapter" }));
  return directory;
}

function processTerminal(directory, script, options, children, { delayedPid = false, subscriptionError = false } = {}) {
  const child = spawn(process.execPath, ["-e", script, directory], {
    env: options.env, cwd: directory, windowsHide: true, stdio: ["pipe", "pipe", "ignore"],
  });
  child.on("error", () => {}); // Missing spawn permissions must fail the real-process test.
  assert(Number.isSafeInteger(child.pid) && child.pid > 0, "Actual owned child did not start");
  const closed = new Promise(resolve => child.once("exit", resolve));
  children.push({ child, closed });
  const readyAt = Date.now() + (delayedPid ? 50 : 0);
  return {
    get pid() { return Date.now() < readyAt ? 0 : child.pid; },
    onExit: handler => child.once("exit", (exitCode, signal) => handler({ exitCode, signal })),
    onData: handler => {
      if (subscriptionError) throw new Error("startup subscription failed after spawn");
      child.stdout.on("data", chunk => handler(String(chunk)));
    },
    write: text => child.stdin.write(text),
  };
}

async function cleanupChildren(children) {
  for (const { child, closed } of children) {
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
    await closed;
  }
}

test("Web submission count excludes runtime context and skill catalogs", () => {
  for (const sourceKind of ["runtime-context", "skill-catalog", undefined, null]) {
    assert.equal(isUserSubmission({ kind: "session/event", type: "user/message", sourceKind }), false);
  }
  assert.equal(isUserSubmission({ kind: "session/event", type: "user/message", sourceKind: "user" }), true);
});

test("Web operation reads the real recorder checkpoint without a flush call", async () => {
  const directory = await mkdtemp(join(tmpdir(), "web-live-checkpoint-"));
  try {
    const recorder = createRecorder({ outputDir: join(directory, "traces") });
    recorder.record("one", { seq: 10, type: "turn/start", data: { turn: 1 } });
    await recorder.flush();
    assert.deepEqual(checkpoint(directory, "one"), {
      runId: recorder.runId, sessionId: "one", runDir: `traces/${recorder.runId}`, afterSeq: 10,
    });
    assert.throws(() => checkpoint(directory, "other"), /not registered/);
    await recorder.close();
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("Web observer records source and one real stream notification without control calls", async () => {
  const directory = await mkdtemp(join(tmpdir(), "web-live-observer-"));
  const previous = process.env.DSH_EVAL_WEB_OBSERVATIONS;
  const hooks = new Map();
  let dispose;
  try {
    process.env.DSH_EVAL_WEB_OBSERVATIONS = join(directory, "observations.jsonl");
    observe({ agentDefaultModel: { currentSelection: () => ({ provider: "test", model: "test" }) },
      on: (name, handler) => hooks.set(name, handler), effect: (effect) => { dispose = effect(); },
      sessions: { flush: () => assert.fail("Observer must not flush") } });
    hooks.get("session/event")({ id: "one" }, { seq: 3, type: "user/message", data: { source: { kind: "runtime-context" } } });
    const frame = { agent: { session: { id: "one" }, cancel: () => assert.fail("Observer must not cancel") }, frame: { type: "chunk" } };
    hooks.get("agent/assistant-stream")(frame);
    hooks.get("agent/assistant-stream")(frame);
    dispose();
    dispose = null;
    const rows = (await readFile(process.env.DSH_EVAL_WEB_OBSERVATIONS, "utf8")).trim().split("\n").map(JSON.parse);
    assert.equal(rows.find((item) => item.type === "user/message").sourceKind, "runtime-context");
    assert.equal(rows.filter((item) => item.kind === "model/first-chunk").length, 1);
    assert.equal(rows.at(-1).kind, "observer/disposed");
  } finally {
    dispose?.();
    if (previous === undefined) delete process.env.DSH_EVAL_WEB_OBSERVATIONS;
    else process.env.DSH_EVAL_WEB_OBSERVATIONS = previous;
    await rm(directory, { recursive: true, force: true });
  }
});

test("Web startup refuses existing evidence before spawning or changing saved state", async () => {
  const directory = await startupFixture();
  let spawned = false;
  try {
    for (const name of ["terminal.log", "state.json", "lifecycle-live.json"]) {
      await writeFile(join(directory, name), "original evidence\n");
    }
    await assert.rejects(runWeb(directory, () => {
      spawned = true;
      throw new Error("Existing capture must be rejected before spawning");
    }), /already exists|existing capture|EEXIST/i);
    assert.equal(spawned, false);
    for (const name of ["terminal.log", "state.json", "lifecycle-live.json"]) {
      assert.equal(await readFile(join(directory, name), "utf8"), "original evidence\n");
    }
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("Web startup error reaps the real child even while the terminal PID is initially zero", async () => {
  const directory = await startupFixture();
  const children = [];
  try {
    const code = await runWeb(directory, (_file, _args, options) => processTerminal(directory,
      "setTimeout(()=>process.exit(3),5000)", options, children, { delayedPid: true, subscriptionError: true }));
    const report = JSON.parse(await readFile(join(directory, "lifecycle-live.json"), "utf8"));
    assert.equal(code, 1);
    assert.equal(report.process.closed, true);
    assert.equal(report.process.forceStopped, true);
    assert.equal(report.process.pid, children[0].child.pid);
    assert.match(report.process.error, /startup subscription failed/);
    assert.notEqual(children[0].child.signalCode ?? children[0].child.exitCode, null);
  } finally { await cleanupChildren(children); await rm(directory, { recursive: true, force: true }); }
});

test("Web terminal output write failure reaps the real child and preserves the first error", async () => {
  const directory = await startupFixture();
  const children = [];
  try {
    const script = "require('node:fs').writeFileSync(require('node:path').join(process.argv[1],'browser-url.txt'),'original url\\n',{flag:'wx'});"
      + "console.log('dsh web: http://127.0.0.1:12345/');setTimeout(()=>process.exit(3),5000)";
    assert.equal(await runWeb(directory, (_file, _args, options) => processTerminal(directory, script, options, children)), 1);
    const report = JSON.parse(await readFile(join(directory, "lifecycle-live.json"), "utf8"));
    assert.equal(report.process.closed, true);
    assert.equal(report.process.forceStopped, true);
    assert.match(report.process.error, /EEXIST.*browser-url\.txt/);
    assert.equal(await readFile(join(directory, "browser-url.txt"), "utf8"), "original url\n");
  } finally { await cleanupChildren(children); await rm(directory, { recursive: true, force: true }); }
});
