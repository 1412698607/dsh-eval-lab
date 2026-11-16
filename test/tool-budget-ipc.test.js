import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createInterface } from "node:readline";
import test from "node:test";
import { fileURLToPath } from "node:url";

const fixture = fileURLToPath(new URL("../scripts/fixtures/tool-budget-ipc.js", import.meta.url));

for (const stopMode of ["abort", "close"]) {
  test(`tool budget rejection crosses real fork IPC before ${stopMode} and child exits`, { timeout: 15000 }, async () => {
    const directory = await mkdtemp(join(tmpdir(), "dsh-budget-ipc-"));
    let child, childPid, timer, lines;
    try {
      await writeFile(join(directory, "case.json"), JSON.stringify({
        caseId: "edit-delete", input: "Scripted tool budget cancellation", budget: { maxToolCalls: 1 },
        configRef: { profile: "headless", provider: "synthetic", model: "none" },
        environment: { stateful: { tools: ["eval_edit", "eval_delete"] } },
      }));
      child = spawn(process.execPath, [fixture, "run", directory], {
        windowsHide: true, stdio: ["pipe", "pipe", "pipe"],
        env: { ...process.env, DSH_TEST_BRIDGE_STOP: stopMode },
      });
      let stderr = "";
      child.stderr.setEncoding("utf8");
      child.stderr.on("data", (chunk) => { stderr += chunk; });
      const messages = [], requests = [];
      lines = createInterface({ input: child.stdout });
      lines.on("line", (line) => {
        const message = JSON.parse(line);
        messages.push(message);
        if (message.type === "launched") childPid = message.pid;
        if (message.type !== "tool-request") return;
        requests.push(message);
        if (requests.length === 2) {
          child.stdin.write(JSON.stringify({ ...message, type: "tool-response", isError: true,
            errorCode: "TOOL_CALL_LIMIT_EXCEEDED", text: "TOOL_CALL_LIMIT_EXCEEDED: obsolete.txt" }) + "\n");
          child.stdin.write(JSON.stringify({ type: "tool_budget" }) + "\n");
        }
      });
      const exit = await new Promise((res, rej) => {
        child.once("error", rej);
        child.once("close", (code, signal) => res({ code, signal }));
        timer = setTimeout(() => rej(new Error(`IPC fixture did not exit: ${stderr}`)), 10000);
      });
      clearTimeout(timer);
      assert.deepEqual(exit, { code: 0, signal: null }, stderr);
      assert.deepEqual(requests.map((request) => request.operation), ["edit", "delete"]);
      assert.equal(new Set(requests.map((request) => request.requestId)).size, 2);
      const proof = JSON.parse(await readFile(join(directory, "tool-budget-proof.json"), "utf8"));
      assert.equal(proof.childPid, childPid);
      assert.equal(proof.modelCalled, false);
      assert.equal(proof.HarnessRuntimeUsed, false);
      assert.deepEqual(proof.results, [
        { status: "rejected", reason: stopMode === "abort" ? "Tool call cancelled" : "Bridge closed" },
        { status: "rejected", reason: "TOOL_CALL_LIMIT_EXCEEDED: obsolete.txt" },
      ]);
      assert.deepEqual(proof.controls, [{ type: "cancel", sessionId: requests[0].sessionId }]);
      assert.deepEqual(proof.failures, []);
      assert.equal(proof.messageListenersRestored, true);
      assert.equal(proof.disconnectListenersRestored, true);
      assert.deepEqual(proof.listeners.after, proof.listeners.before);
      const cancels = messages.filter((message) => message.type === "tool-cancel");
      assert.deepEqual(cancels.map((message) => message.requestId), stopMode === "abort" ? [requests[0].requestId] : []);
      const host = JSON.parse(await readFile(join(directory, "host-result.json"), "utf8"));
      assert.equal(host.childClosed, true);
      assert.equal(host.intervention, "tool_budget");
      assert.equal(host.forceStopped, false);
      assert.equal(host.exitCode, 0);
      assert.equal(host.signal, null);
      assert.equal(host.error, null);
      assert.equal(host.protocol.valid, true);
      assert.deepEqual(host.protocol.turnEndReason, { kind: "aborted", reason: { kind: "user" } });
      const runDirectories = await readdir(join(directory, "traces"));
      assert.equal(runDirectories.length, 1);
      const traceDirectory = join(directory, "traces", runDirectories[0]);
      const trace = (await readdir(traceDirectory)).find((name) => name.endsWith(".jsonl"));
      const events = (await readFile(join(traceDirectory, trace), "utf8")).trim().split("\n").map((line) => JSON.parse(line).event);
      assert.equal(events.some((event) => event.type === "assistant/message"), false);
      assert.equal(events.filter((event) => event.type === "tool/result").length, 2);
      assert.equal(events.some((event) => event.type === "tool/result" && event.data.message.isError
        && event.data.message.content[0].text === "Error: TOOL_CALL_LIMIT_EXCEEDED: obsolete.txt"), true);
      assert.throws(() => process.kill(childPid, 0), { code: "ESRCH" });
    } finally {
      clearTimeout(timer);
      lines?.close();
      if (child && child.exitCode === null && child.signalCode === null) {
        if (childPid) {
          try { process.kill(childPid, "SIGKILL"); } catch (error) { if (error.code !== "ESRCH") throw error; }
        }
        const closed = new Promise((res) => child.once("close", res));
        child.kill("SIGKILL");
        await closed;
      }
      await rm(directory, { recursive: true, force: true });
    }
  });
}
