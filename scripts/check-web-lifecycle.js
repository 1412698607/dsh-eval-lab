// Real owned child processes and recorder files; no Web server, Harness or model calls.
import { fork } from "node:child_process";
import { randomUUID } from "node:crypto";
import { createWriteStream } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { finished } from "node:stream/promises";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const scenarios = ["page-cancel", "normal-exit", "process-interrupt"];
const fixture = fileURLToPath(new URL("./fixtures/web-lifecycle-child.js", import.meta.url));
const casePath = fileURLToPath(new URL("../fixtures/evaluation/web-lifecycle.case.json", import.meta.url));

export async function captureScenario(directory, scenario) {
  if (!scenarios.includes(scenario)) throw new Error("Unknown lifecycle scenario");
  await mkdir(directory); // A new directory is required; never overwrite an earlier capture.
  const caseData = JSON.parse(await readFile(casePath, "utf8"));
  await writeFile(join(directory, "case.json"), JSON.stringify(caseData, null, 2) + "\n", { flag: "wx" });
  await mkdir(join(directory, "workspace"));
  await writeFile(join(directory, "workspace", "README.md"), caseData.environment.files["README.md"], { flag: "wx" });
  const report = { webLifecycleFormatVersion: 1, source: "synthetic", scenario,
    runId: null, sessionId: null, runDir: null, operation: null,
    process: { pid: null, closed: false, exitCode: null, signal: null, forceStopped: false,
      intervention: null, error: null } };
  const stdout = createWriteStream(join(directory, "stdout.log"), { flags: "wx" });
  const stderr = createWriteStream(join(directory, "stderr.log"), { flags: "wx" });
  const streams = Promise.all([finished(stdout), finished(stderr)]);
  // Attach an error handler immediately; failures are reported after the owned child closes.
  streams.catch(() => {});
  let child;
  let deadline;
  try {
    child = fork(fixture, [directory, scenario], {
      windowsHide: true, stdio: ["ignore", "pipe", "pipe", "ipc"],
    });
    report.process.pid = child.pid ?? null;
    child.stdout.pipe(stdout);
    child.stderr.pipe(stderr);
    const kill = () => {
      try {
        if (!child.kill("SIGKILL")) report.process.error ??= "Owned child rejected SIGKILL";
      } catch (error) { report.process.error ??= `${error.code ?? "KILL_ERROR"}: ${error.message}`; }
    };
    child.on("message", (message) => {
      if (message?.type !== "checkpoint" || report.operation || report.process.intervention) return;
      Object.assign(report, { runId: message.runId, sessionId: message.sessionId, runDir: `traces/${message.runId}` });
      report.operation = { kind: { "page-cancel": "synthetic-cancel", "normal-exit": "fixture-exit",
        "process-interrupt": "process-kill" }[scenario], afterSeq: message.lastSeq,
        signal: scenario === "process-interrupt" ? "SIGKILL" : null };
      if (scenario === "process-interrupt") {
        report.process.forceStopped = true;
        report.process.intervention = "expected-interrupt";
        kill();
      } else child.send({ type: report.operation.kind }, (error) => {
        if (error) report.process.error ??= `${error.code ?? "IPC_ERROR"}: ${error.message}`;
      });
    });
    deadline = setTimeout(() => {
      report.process.intervention = "timeout";
      report.process.forceStopped = true;
      kill();
      if (child.connected) child.disconnect();
    }, 10000);
    await new Promise((res) => {
      child.once("error", (error) => { report.process.error = `${error.code ?? "SPAWN_ERROR"}: ${error.message}`; });
      child.once("close", (exitCode, signal) => {
        Object.assign(report.process, { closed: true, exitCode, signal });
        res();
      });
    });
  } catch (error) {
    report.process.error ??= `${error.code ?? "CAPTURE_ERROR"}: ${error.message}`;
  } finally {
    clearTimeout(deadline);
    stdout.end();
    stderr.end();
    try { await streams; }
    catch (error) { report.process.error ??= `OUTPUT_ERROR: ${error.message}`; }
  }
  await writeFile(join(directory, "lifecycle.json"), JSON.stringify(report, null, 2) + "\n", { flag: "wx" });
  return report;
}

export async function main(args = process.argv.slice(2)) {
  if (args.length > 1) throw new Error("Usage: node scripts/check-web-lifecycle.js [new-output-directory]");
  const directory = resolve(args[0] ?? join("runs", "web-lifecycle", randomUUID()));
  await mkdir(resolve(directory, ".."), { recursive: true });
  await mkdir(directory);
  const captures = [];
  for (const scenario of scenarios) {
    const launch = join(directory, scenario);
    const report = await captureScenario(launch, scenario);
    captures.push({ scenario, directory: launch, error: report.process.error });
  }
  console.info(JSON.stringify({ source: "synthetic", modelCalled: false, directory, captures }));
  return captures.every((item) => item.error === null) ? 0 : 1;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exitCode = await main();
