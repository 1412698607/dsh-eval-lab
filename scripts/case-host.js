import { execFileSync, fork } from "node:child_process";
import { createWriteStream } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { basename, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { finished } from "node:stream/promises";
import { fileURLToPath } from "node:url";
import { locateHost, validateHost } from "./lib/host.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const emit = (event) => process.stdout.write(JSON.stringify(event) + "\n");

export async function prepareCase(directory, modulesDirectory) {
  const caseData = JSON.parse(await readFile(join(directory, "case.json"), "utf8"));
  if (caseData.configRef.profile !== "headless") throw new Error("M3.2 only supports the headless profile");
  const modulesDir = await locateHost(modulesDirectory);
  const versions = await validateHost(modulesDir);
  const cli = join(modulesDir, "@deepseek-ai", "dsh", "lib", "bin.js");
  const cliVersion = JSON.parse(await readFile(join(modulesDir, "@deepseek-ai", "dsh", "package.json"), "utf8")).version;
  if (cliVersion !== versions["@deepseek-ai/dsh-session"]) throw new Error("CLI/session version mismatch");
  const home = join(directory, "home");
  const workspace = join(directory, "workspace");
  const credentialPath = join(resolve(process.env.DSH_HOME || join(homedir(), ".dsh")), ".credentials.yaml");
  execFileSync(process.execPath, [cli, "plugin", "--profile", "headless", "add",
    `link:${root.replaceAll("\\", "/")}`, "--offline", "--ignore-scripts", "--store-dir", join(directory, "pnpm-store")], {
    cwd: workspace, env: { ...process.env, DSH_HOME: home, DSH_TELEMETRY_DISABLED: "1" },
    // Python owns the preparation deadline and can terminate this entire installer tree.
    stdio: "inherit", windowsHide: true,
  });
  await writeFile(join(home, "profiles", "headless", "cordis.patch.yml"), JSON.stringify([
    { id: "credentials", config: { path: credentialPath, watch: false } },
    { id: "sandbox-policy", config: { mode: "read-only", workspaceRoot: workspace } },
    { id: "session-title-llm", disabled: true },
    { id: "agent-default-model", config: { provider: caseData.configRef.provider, model: caseData.configRef.model } },
  ], null, 2) + "\n", { flag: "w" });
  const controlPatch = join(directory, "control.patch.yml");
  await writeFile(controlPatch, JSON.stringify([{ insert: [{
    id: "eval-case-control", name: fileURLToPath(new URL("./fixtures/case-control.js", import.meta.url)),
  }] }], null, 2) + "\n", { flag: "wx" });
  const setup = { setupFormatVersion: 1, cli, cliVersion, modulesDir, versions, home, workspace, controlPatch };
  await writeFile(join(directory, "setup.json"), JSON.stringify(setup, null, 2) + "\n", { flag: "wx" });
  return setup;
}

export function summarizeProtocol(text, sessionId) {
  try {
    const frames = text.trim().split("\n").map(JSON.parse);
    const end = frames.findLast((frame) => frame.type === "status" && frame.phase === "turn_end");
    return { valid: frames[0]?.type === "session" && frames[0]?.sessionId === sessionId
        && frames.at(-1)?.type === "final" && typeof frames.at(-1)?.text === "string",
      sessionId: frames[0]?.sessionId ?? null, turnEndReason: end?.reason ?? null };
  } catch {
    return { valid: false, sessionId: null, turnEndReason: null };
  }
}

export async function runCase(directory) {
  const setup = JSON.parse(await readFile(join(directory, "setup.json"), "utf8"));
  const caseData = JSON.parse(await readFile(join(directory, "case.json"), "utf8"));
  await validateHost(setup.modulesDir);
  const traces = join(directory, "traces");
  await mkdir(traces, { recursive: true });
  const stdout = createWriteStream(join(directory, "stdout.jsonl"), { flags: "wx" });
  const stderr = createWriteStream(join(directory, "stderr.log"), { flags: "wx" });
  const report = { adapterFormatVersion: 1, cliVersion: setup.cliVersion, childPid: null, childClosed: false,
    selection: null, sessionId: null, requests: [], streamed: false, intervention: null,
    forceStopped: false, exitCode: null, signal: null, protocol: null, error: null };
  let child;
  let stopTimer;
  const commands = createInterface({ input: process.stdin });
  const stop = (kind) => {
    if (!child || report.childClosed || report.intervention !== null) return;
    report.intervention = kind;
    if (child.connected) child.send(kind === "cancel" && report.sessionId
      ? { type: "cancel", sessionId: report.sessionId } : { type: "shutdown" });
    stopTimer = setTimeout(() => {
      report.forceStopped = true;
      child.kill("SIGKILL");
    }, 10000);
  };
  const disconnected = () => stop("parent-disconnected");
  const terminate = () => stop("shutdown");
  commands.on("line", (line) => {
    try {
      const command = JSON.parse(line);
      if (command.type === "tool-response" && child?.connected && report.intervention === null) {
        child.send(command);
        return;
      }
      if (["cancel", "timeout", "shutdown"].includes(command.type)) stop(command.type);
    } catch { stop("invalid-control"); }
  });
  commands.on("close", disconnected);
  process.on("SIGINT", terminate);
  process.on("SIGTERM", terminate);
  try {
    child = fork(setup.cli, ["--profile", "headless", "--patch", setup.controlPatch, "--json", "--", caseData.input], {
      cwd: setup.workspace, windowsHide: true, stdio: ["ignore", "pipe", "pipe", "ipc"],
      env: { ...process.env, DSH_HOME: setup.home, DSH_EVAL_OUTPUT_DIR: traces, DSH_TELEMETRY_DISABLED: "1",
        DSH_EVAL_STATEFUL: caseData.environment.stateful ? "1" : "0", DSH_EVAL_CASE_RUN_ID: basename(directory),
        DSH_EVAL_HOST_MODULES: setup.modulesDir },
    });
    report.childPid = child.pid ?? null;
    child.stdout.pipe(stdout);
    child.stderr.pipe(stderr);
    child.on("message", (message) => {
      if (message?.type === "selection") {
        report.selection = message.selection;
        report.sessionId = message.sessionId;
      } else if (message?.type === "request-route") {
        report.requests.push({ sessionId: message.sessionId, provider: message.provider, model: message.model });
      } else if (message?.type === "streaming") {
        report.streamed = true;
      } else if (message?.type === "tool-request") {
        if (message.sessionId !== report.sessionId || message.caseRunId !== basename(directory)) {
          report.error = "Tool request identity mismatch";
          stop("invalid-bridge");
          return;
        }
      } else if (message?.type === "bridge-error") {
        report.error = message.message;
        stop("bridge-error");
      } else return;
      emit(message);
    });
    emit({ type: "launched", pid: report.childPid });
    const exit = await new Promise((res, rej) => {
      child.once("error", rej);
      child.once("close", (exitCode, signal) => res({ exitCode, signal }));
    });
    Object.assign(report, exit, { childClosed: true });
  } catch (error) {
    report.error = `${error.code ?? "HOST_ERROR"}: ${error.message}`;
  } finally {
    clearTimeout(stopTimer);
    commands.off("close", disconnected);
    commands.close();
    process.stdin.pause();
    process.off("SIGINT", terminate);
    process.off("SIGTERM", terminate);
    if (child && !report.childClosed && child.exitCode === null && child.signalCode === null) {
      report.forceStopped = true;
      child.kill("SIGKILL");
      await new Promise((res) => child.once("close", res));
      report.childClosed = true;
    }
    stdout.end();
    stderr.end();
    await Promise.all([finished(stdout), finished(stderr)]);
  }
  report.protocol = summarizeProtocol(await readFile(join(directory, "stdout.jsonl"), "utf8"), report.sessionId);
  await writeFile(join(directory, "host-result.json"), JSON.stringify(report, null, 2) + "\n", { flag: "wx" });
  emit({ type: "closed", childClosed: report.childClosed });
  return report;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [mode, directory, modulesDir] = process.argv.slice(2);
  try {
    if (!["prepare", "run"].includes(mode) || !directory) throw new Error("Usage: case-host.js prepare|run <case-run-dir> [modules-dir]");
    if (mode === "prepare") await prepareCase(resolve(directory), modulesDir);
    else await runCase(resolve(directory));
  } catch (error) {
    console.error(`${error.code ?? "HOST_ERROR"}: ${error.message}`);
    process.exitCode = 1;
  }
}
