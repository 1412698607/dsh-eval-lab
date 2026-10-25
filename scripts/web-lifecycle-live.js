// Explicit real Web driver. Browser submission/cancellation happens outside this process.
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { stripVTControlCharacters } from "node:util";
import { fileURLToPath } from "node:url";
import { locateHost, validateHost } from "./lib/host.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const scenarios = ["normal-exit", "page-cancel", "process-interrupt"];
const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));
const saveNew = (path, value) => writeFileSync(path, JSON.stringify(value, null, 2) + "\n", { flag: "wx" });
const output = (value) => console.info(JSON.stringify(value));
const ptyModule = (modulesDir) => createRequire(join(modulesDir, "__web_eval__.cjs"))("node-pty");

export const isUserSubmission = (event) => event.kind === "session/event"
  && event.type === "user/message" && event.sourceKind === "user";

export async function prepareWeb(directory, scenario, modulesDirectory) {
  if (!scenarios.includes(scenario)) throw new Error("Unknown Web lifecycle scenario");
  const modulesDir = await locateHost(modulesDirectory);
  const versions = await validateHost(modulesDir);
  const cli = join(modulesDir, "@deepseek-ai", "dsh", "lib", "bin.js");
  const cliVersion = readJson(join(modulesDir, "@deepseek-ai", "dsh", "package.json")).version;
  if (cliVersion !== versions["@deepseek-ai/dsh-session"]) throw new Error("CLI/session version mismatch");
  mkdirSync(directory); // Each owned server gets a new case, home and workspace.
  const caseData = readJson(join(root, "fixtures", "evaluation", "web-lifecycle.case.json"));
  if (scenario !== "normal-exit") {
    caseData.caseId += `-${scenario}`;
    caseData.input = "Use the actual read tool with file_path README.md (a relative path) to read projectName. "
      + "Then write a detailed numbered list of 10000 software testing examples, continuing until interrupted. "
      + "Do not modify files, run shell commands, or delegate.";
  }
  saveNew(join(directory, "case.json"), caseData);
  const home = join(directory, "home");
  const documentsDirectory = join(directory, "documents");
  // Web creates its first Workspace from this supported deployment override, not CLI cwd.
  const workspace = join(documentsDirectory, "deepseek-harness", "default-workspace");
  mkdirSync(workspace, { recursive: true });
  for (const [name, text] of Object.entries(caseData.environment.files)) {
    mkdirSync(resolve(workspace, name, ".."), { recursive: true });
    writeFileSync(join(workspace, name), text, { flag: "wx" });
  }
  const credentialPath = join(resolve(process.env.DSH_HOME || join(homedir(), ".dsh")), ".credentials.yaml");
  execFileSync(process.execPath, [cli, "plugin", "--profile", "web", "add", `link:${root.replaceAll("\\", "/")}`,
    "--offline", "--ignore-scripts", "--store-dir", join(directory, "pnpm-store")], {
    cwd: workspace, env: { ...process.env, DSH_HOME: home, DSH_TELEMETRY_DISABLED: "1" },
    stdio: ["ignore", "pipe", "pipe"], windowsHide: true, timeout: 120000,
  });
  saveNew(join(directory, "observations-meta.json"), { observationVersion: 1, source: "live", scenario });
  writeFileSync(join(directory, "observations.jsonl"), "", { flag: "wx" });
  writeFileSync(join(home, "profiles", "web", "cordis.patch.yml"), JSON.stringify([
    { id: "credentials", config: { path: credentialPath, watch: false } },
    { id: "sandbox-policy", config: { mode: "read-only", workspaceRoot: workspace } },
    { id: "session-title-llm", disabled: true },
    { id: "agent-default-model", config: { provider: caseData.configRef.provider, model: caseData.configRef.model } },
    { id: "workspace-controller", config: { documentsDirectory } },
  ], null, 2) + "\n");
  const patch = join(directory, "observer.patch.yml");
  saveNew(patch, [{ insert: [{ id: "eval-web-observer", name:
    fileURLToPath(new URL("./fixtures/web-lifecycle-observer.js", import.meta.url)) }] }]);
  saveNew(join(directory, "setup.json"), { webLiveSetupVersion: 1, scenario, cliVersion, modulesDir, versions,
    cli, home, workspace, documentsDirectory, patch, nodePtyVersion: readJson(join(modulesDir, "node-pty", "package.json")).version });
  return { directory, scenario, cliVersion, model: caseData.configRef.model };
}

export function checkpoint(directory, sessionId) {
  const traces = join(directory, "traces");
  const runs = readdirSync(traces);
  if (runs.length !== 1) throw new Error("Expected one owned recorder run");
  const runId = runs[0];
  const run = readJson(join(traces, runId, "run.json"));
  const member = run.sessions.find((item) => item.sessionId === sessionId);
  if (!member) throw new Error("Session not registered in recorder");
  const status = readJson(join(traces, runId, member.statusFile));
  if (!Number.isSafeInteger(status.lastSeq)) throw new Error("No written operation checkpoint");
  return { runId, sessionId, runDir: `traces/${runId}`, afterSeq: status.lastSeq };
}

export async function runWeb(directory, spawnTerminal) {
  const setup = readJson(join(directory, "setup.json"));
  if (setup.webLiveSetupVersion !== 1 || !scenarios.includes(setup.scenario)) throw new Error("Invalid live setup");
  await validateHost(setup.modulesDir);
  for (const name of ["state.json", "state.json.new", "lifecycle-live.json", "browser-url.txt"]) {
    if (existsSync(join(directory, name))) throw new Error(`Refusing existing capture: ${name}`);
  }
  // Reserve output before starting a child. Later I/O failures still require cleanup.
  writeFileSync(join(directory, "terminal.log"), "", { flag: "wx" });
  const report = { liveWebLifecycleFormatVersion: 1, source: "live", scenario: setup.scenario,
    runId: null, sessionId: null, runDir: null, operation: null,
    platform: process.platform, cliVersion: setup.cliVersion, nodePtyVersion: setup.nodePtyVersion,
    process: { pid: null, closed: false, exitCode: null, signal: null, forceStopped: false,
      intervention: null, error: null }, startedAt: new Date().toISOString(), finishedAt: null };
  let terminal;
  let interval;
  let timeout;
  let shutdownTimer;
  let exited;
  let failCapture;
  const failed = new Promise(resolve => { failCapture = resolve; });
  let seen = 0;
  let text = "";
  let firstStream = false;
  let end = null;
  let endSeq = null;
  let observedWorkspace = null;
  const commands = createInterface({ input: process.stdin });
  const state = () => {
    const path = join(directory, "state.json");
    writeFileSync(`${path}.new`, JSON.stringify({ ...report, firstStream, turnEnd: end, observedWorkspace }) + "\n");
    renameSync(`${path}.new`, path);
  };
  const abort = (error) => {
    report.process.error ??= String(error.message);
    failCapture();
  };
  const killOwned = () => {
    const pid = terminal.pid;
    if (!Number.isSafeInteger(pid) || pid <= 0) throw new Error("Owned terminal PID is not ready");
    report.process.pid = pid;
    process.kill(pid, "SIGKILL");
  };
  const stop = (intervention) => {
    if (!terminal || report.process.closed || report.process.intervention) return;
    report.process.intervention = intervention;
    try {
      if (report.sessionId) {
        const point = checkpoint(directory, report.sessionId);
        Object.assign(report, { runId: point.runId, runDir: point.runDir });
        const forced = intervention === "expected-interrupt" || intervention === "timeout";
        if (!report.operation) report.operation = { kind: forced ? "process-kill" : "console-ctrl-c",
          afterSeq: intervention === "console-shutdown" ? Math.max(point.afterSeq, endSeq ?? point.afterSeq) : point.afterSeq,
          at: new Date().toISOString(),
          requestedSignal: forced ? "SIGKILL" : "SIGINT" };
      }
      if (intervention === "expected-interrupt" || intervention === "timeout") {
        report.process.forceStopped = true;
        killOwned();
      } else {
        // Actual ConPTY input. Never child.kill('SIGINT') or process.emit('SIGINT').
        terminal.write("\x03");
        shutdownTimer = setTimeout(() => {
          if (report.process.closed) return;
          report.process.forceStopped = true;
          report.process.intervention = "shutdown-timeout";
          try { killOwned(); } catch (error) { abort(error); }
        }, 10000);
      }
    } catch (error) {
      abort(error);
    }
    try { state(); } catch (error) { abort(error); }
  };
  commands.on("line", (line) => {
    try {
      const command = JSON.parse(line);
      if (command.type === "mark-page-cancel") {
        if (setup.scenario !== "page-cancel" || !firstStream || end || report.operation) {
          throw new Error("Page cancellation requires one currently streaming task");
        }
        const point = checkpoint(directory, report.sessionId);
        Object.assign(report, { runId: point.runId, runDir: point.runDir });
        report.operation = { kind: "page-cancel", afterSeq: point.afterSeq,
          at: new Date().toISOString(), requestedSignal: null };
        state();
        output({ pageCancelCheckpoint: point.afterSeq });
        return; // Observation marker only; the actual button must still be clicked.
      }
      if (command.type !== "shutdown") throw new Error("Only console shutdown is supported; cancel on the actual page");
      if (!end) throw new Error("Wait for the actual task's turn/end before shutdown");
      stop("console-shutdown");
    } catch (error) {
      if (error.code) abort(error);
      output({ error: error.message });
    }
  });
  const parentLost = () => stop("parent-disconnected");
  commands.on("close", parentLost);
  try {
    const spawn = spawnTerminal ?? ((...args) => ptyModule(setup.modulesDir).spawn(...args));
    terminal = spawn(process.execPath, [setup.cli, "--profile", "web", "--patch", setup.patch,
      "--no-open", "--host", "127.0.0.1", "--port", "0"], {
      name: "xterm-color", cols: 180, rows: 40, cwd: setup.workspace,
      env: { ...process.env, DSH_HOME: setup.home, DSH_TELEMETRY_DISABLED: "1",
        DSH_EVAL_OUTPUT_DIR: join(directory, "traces"), DSH_EVAL_WEB_OBSERVATIONS: join(directory, "observations.jsonl") },
    });
    // Register exit observation before subscribing to output or writing any more evidence.
    exited = new Promise((done) => terminal.onExit(({ exitCode, signal }) => {
      Object.assign(report.process, { pid: terminal.pid, closed: true, exitCode, signal: signal ?? null });
      done();
    }));
    report.process.pid = terminal.pid;
    terminal.onData((chunk) => {
      if (report.process.error) return;
      try {
        appendFileSync(join(directory, "terminal.log"), chunk);
        text = (text + chunk).slice(-100000);
        const match = stripVTControlCharacters(text).match(/dsh web: (http:\/\/127\.0\.0\.1:\d+\S*)/);
        if (match && !report.url) {
          // Bootstrap URL carries a local process token; keep it in ignored evidence only.
          writeFileSync(join(directory, "browser-url.txt"), match[1] + "\n", { flag: "wx" });
          report.url = new URL(match[1]).origin;
          report.process.pid = terminal.pid; // ConPTY assigns the real PID after initial pipe readiness.
          state();
          output({ ready: true, directory, url: report.url, pid: terminal.pid });
        }
      } catch (error) { abort(error); }
    });
    interval = setInterval(() => {
      try {
        const lines = readFileSync(join(directory, "observations.jsonl"), "utf8").split("\n");
        const previousSeen = seen;
        for (; seen < lines.length - 1; seen++) {
          const event = JSON.parse(lines[seen]);
          if (event.kind === "session/event" && event.cwd) {
            observedWorkspace = event.cwd;
            if (resolve(event.cwd) !== resolve(setup.workspace)) throw new Error("Actual Web Workspace differs from the frozen fixture");
          }
          if (isUserSubmission(event)) {
            if (report.sessionId) throw new Error("Only one submitted task is authorized per server");
            report.sessionId = event.sessionId;
            timeout = setTimeout(() => stop("timeout"), 120000);
          }
          if (event.kind === "model/first-chunk") {
            firstStream = true;
            if (setup.scenario === "process-interrupt") stop("expected-interrupt");
          }
          if (event.kind === "session/event" && event.type === "turn/end") {
            end = event.reason;
            endSeq = event.seq;
            clearTimeout(timeout);
          }
        }
        if (seen !== previousSeen) state();
      } catch (error) { abort(error); }
    }, 30);
    await Promise.race([exited, failed]);
  } catch (error) { abort(error); }
  finally {
    clearInterval(interval);
    clearTimeout(timeout);
    clearTimeout(shutdownTimer);
    commands.off("close", parentLost);
    commands.close();
    if (terminal && !report.process.closed) {
      report.process.forceStopped = true;
      report.process.intervention ??= "capture-error";
      // ConPTY may initially expose PID 0. Never pass that value to process.kill.
      const deadline = Date.now() + 10000;
      while (!report.process.closed && !(Number.isSafeInteger(terminal.pid) && terminal.pid > 0) && Date.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, 10));
      }
      let cleanupError;
      if (!report.process.closed) {
        try { killOwned(); } catch (error) { cleanupError = error.message; }
        let cleanupTimer;
        try {
          await Promise.race([exited, new Promise(resolve => {
            cleanupTimer = setTimeout(resolve, Math.max(0, deadline - Date.now()));
          })]);
        } finally { clearTimeout(cleanupTimer); }
      }
      if (!report.process.closed) {
        const reason = cleanupError ?? "Owned process exit was not observed during cleanup";
        report.process.error = `${report.process.error ?? "Capture failed"}; cleanup: ${reason}`;
      }
    }
    report.finishedAt = new Date().toISOString();
    state();
    saveNew(join(directory, "lifecycle-live.json"), report);
    output({ finished: true, directory, process: report.process });
  }
  return report.process.error ? 1 : 0;
}

export async function checkConsole(directory) {
  mkdirSync(directory);
  const modulesDir = await locateHost();
  let terminal;
  let text = "";
  const watchdog = setTimeout(() => { if (terminal) process.kill(terminal.pid, "SIGKILL"); }, 10000);
  try {
    terminal = ptyModule(modulesDir).spawn(process.execPath, ["-e",
      "process.on('SIGINT',()=>{console.log('ACTUAL_SIGINT_RECEIVED');process.exit(130)});console.log('CONSOLE_READY');setInterval(()=>{},1000)"],
    { name: "xterm-color", cols: 100, rows: 20, cwd: root, env: process.env });
    let sent = false;
    terminal.onData((chunk) => {
      text += chunk;
      if (!sent && text.includes("CONSOLE_READY")) { sent = true; terminal.write("\x03"); }
    });
    const exit = await new Promise((done) => terminal.onExit(done));
    const report = { modelCalled: false, pid: terminal.pid, exit, receivedSIGINT: text.includes("ACTUAL_SIGINT_RECEIVED") };
    writeFileSync(join(directory, "terminal.log"), text, { flag: "wx" });
    saveNew(join(directory, "result.json"), report);
    output(report);
    return report.receivedSIGINT && exit.exitCode === 130 ? 0 : 1;
  } finally { clearTimeout(watchdog); }
}

export async function main(args = process.argv.slice(2)) {
  const [mode, name, scenario] = args;
  if (!name || !["prepare", "run", "check-console"].includes(mode)) throw new Error(
    "Usage: node scripts/web-lifecycle-live.js prepare <new-directory> <scenario> | run <directory> | check-console <new-directory>");
  const directory = resolve(name);
  if (mode === "prepare") { output(await prepareWeb(directory, scenario)); return 0; }
  return mode === "run" ? runWeb(directory) : checkConsole(directory);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const code = await main();
  // node-pty's native worker can retain the supervisor after the observed child exit.
  // All evidence writes are synchronous; drain stdout before releasing this CLI process.
  process.stdout.write("", () => process.exit(code));
}
