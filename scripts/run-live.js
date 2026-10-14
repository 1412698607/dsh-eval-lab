import { fork } from "node:child_process";
import { randomUUID } from "node:crypto";
import { createWriteStream } from "node:fs";
import { finished } from "node:stream/promises";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { inspectRun } from "../src/inspect.js";
import { validateHost } from "./lib/host.js";

const [directory, mode] = process.argv.slice(2);
const prompts = {
  read: "Read README.md using the actual filesystem tool. Return only the value of projectName. Do not modify any files or delegate.",
  missing: "Read missing-m2-3.txt using the actual filesystem tool. If it does not exist, report that fact in one sentence. Do not create it, modify any files or delegate.",
  cancel: "Read README.md with the filesystem tool, then explain its contents in detail. Do not modify files or delegate.",
  kill: "Read README.md with the filesystem tool, then explain its contents in detail. Do not modify files or delegate.",
};
if (process.argv.length !== 4 || !directory || !(Object.hasOwn(prompts, mode) || mode === "web")) {
  console.error("用法：node scripts/run-live.js <联调目录> read|missing|cancel|kill|web");
  process.exit(2);
}
const setup = JSON.parse(await readFile(join(resolve(directory), "setup.json"), "utf8"));
if (setup.setupFormatVersion !== 1) throw new Error("不支持的联调配置版本");
await validateHost(setup.modulesDir);
const launchDir = join(resolve(directory), mode, randomUUID());
const traces = join(launchDir, "traces");
await mkdir(traces, { recursive: true });
const stdoutPath = join(launchDir, mode === "web" ? "stdout.log" : "stdout.jsonl");
const stdout = createWriteStream(stdoutPath);
const stderr = createWriteStream(join(launchDir, "stderr.log"));
const profile = mode === "web" ? "web" : "headless";
const args = ["--profile", profile, "--patch", setup.controlPatch,
  ...(mode === "web" ? ["--no-open", "--host", "127.0.0.1", "--port", "0"] : ["--json", prompts[mode]])];
let intervention = null;
let timeout;
let child;
try {
  child = fork(setup.cli, args, {
    cwd: setup.workspace, windowsHide: true, stdio: ["ignore", "pipe", "pipe", "ipc"],
    env: { ...process.env, DSH_HOME: setup.home, DSH_EVAL_OUTPUT_DIR: traces, DSH_TELEMETRY_DISABLED: "1" },
  });
} catch (cause) {
  stdout.end();
  stderr.end();
  throw new Error(cause.code === "EPERM"
    ? "沙箱禁止创建真实子进程；请在获准环境或外部终端执行同一命令，当前不能视为通过。"
    : "Harness 子进程无法启动", { cause });
}
child.stdout.pipe(stdout);
child.stderr.pipe(stderr);
child.stderr.on("data", (chunk) => process.stderr.write(chunk));
if (mode === "web") child.stdout.on("data", (chunk) => process.stdout.write(chunk));
const sendShutdown = () => {
  if (child.connected) child.send({ type: "shutdown" });
  clearTimeout(timeout);
  timeout = setTimeout(() => {
    intervention = "shutdown-timeout-force-stop";
    child.kill("SIGKILL");
  }, 15000);
};
process.on("SIGINT", sendShutdown);
process.on("SIGTERM", sendShutdown);
if (mode === "web") {
  console.info("Web 联调启动后，在页面提交任务。完成后在此输入 stop 并回车，等待正常关闭及 inspect。");
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (text) => { if (text.trim() === "stop") sendShutdown(); });
} else {
  timeout = setTimeout(() => {
    intervention = "timeout-force-stop";
    child.kill("SIGKILL");
  }, 120000);
}
child.on("message", (message) => {
  if (message?.type !== "streaming" || intervention !== null) return;
  if (mode === "cancel") {
    intervention = "agent-cancel-after-stream-chunk";
    child.send({ type: "cancel", sessionId: message.sessionId });
  } else if (mode === "kill") {
    intervention = "force-stop-after-stream-chunk";
    child.kill("SIGKILL");
  }
});
console.info(`本次输出：${launchDir}`);
try {
  const result = await new Promise((res, rej) => {
    child.once("error", rej);
    child.once("close", (exitCode, signal) => res({ exitCode, signal }));
  });
  await Promise.all([finished(stdout), finished(stderr)]);
  const inspections = [];
  for (const runId of await readdir(traces)) {
    const runDir = join(traces, runId);
    const inspection = await inspectRun(runDir);
    inspections.push({ runDir, ...inspection });
  }
  // Validate the headless output boundary and termination facts, not task correctness.
  let protocol = null;
  if (mode !== "web" && mode !== "kill" && intervention !== "timeout-force-stop") {
    const frames = (await readFile(stdoutPath, "utf8")).trim().split("\n").map(JSON.parse);
    const turnEnd = frames.findLast((frame) => frame.type === "status" && frame.phase === "turn_end");
    protocol = { sessionId: frames[0]?.sessionId, turnEndReason: turnEnd?.reason,
      valid: frames[0]?.type === "session" && frames.at(-1)?.type === "final" && typeof frames.at(-1).text === "string" };
    protocol.valid &&= inspections.some((item) => item.sessions.some((session) => session.sessionId === protocol.sessionId));
  }
  const report = { resultFormatVersion: 1, profile, cliVersion: setup.cliVersion, mode, prompt: prompts[mode] ?? null,
    ...result, intervention, protocol, inspections };
  await writeFile(join(launchDir, "result.json"), JSON.stringify(report, null, 2) + "\n");
  console.info(JSON.stringify(report, null, 2));
  // A forcibly stopped run must have evidence and must never inspect as complete.
  const inspected = inspections.length > 0;
  const expected = mode === "kill"
    ? intervention === "force-stop-after-stream-chunk" && result.signal === "SIGKILL"
      && inspected && inspections.every((item) => item.exitCode !== 0)
    : result.exitCode === (mode === "cancel" ? 1 : 0) && inspected && inspections.every((item) => item.exitCode === 0)
      && (mode === "web" || protocol?.valid && (mode === "cancel"
        ? intervention === "agent-cancel-after-stream-chunk" && protocol.turnEndReason?.kind === "aborted"
          && protocol.turnEndReason.reason?.kind === "user"
        : protocol.turnEndReason?.kind === "completed"));
  process.exitCode = expected ? 0 : 1;
} finally {
  clearTimeout(timeout);
  process.off("SIGINT", sendShutdown);
  process.off("SIGTERM", sendShutdown);
  process.stdin.pause();
  if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
}
