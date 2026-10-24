// Synthetic lifecycle events only. This fixture never imports Harness or a model adapter.
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { createRecorder } from "../../src/recorder.js";

const [directory, scenario] = process.argv.slice(2);
if (!process.send || !["page-cancel", "normal-exit", "process-interrupt"].includes(scenario)) {
  throw new Error("Dedicated lifecycle fixture child required");
}
const caseData = JSON.parse(await readFile(join(directory, "case.json"), "utf8"));
const recorder = createRecorder({ outputDir: join(directory, "traces") });
const sessionId = `synthetic-web-${randomUUID()}`;
let seq = 0;
const record = (type, data) => {
  if (!recorder.record(sessionId, { seq: seq++, type, data })) throw new Error("Fixture record rejected");
};
// Bound orphaned fixtures without converting a lost parent into a successful shutdown.
const watchdog = setTimeout(() => process.exit(3), 30000);
process.once("disconnect", () => process.exit(3));
record("turn/start", { turn: 1 });
record("user/message", { source: { kind: "user" }, content: [{ type: "text", text: caseData.input }] });
record("step/start", { turn: 1, step: 1 });
if (scenario === "normal-exit") {
  record("tool/call", { callId: "fixture-read", name: "read", arguments: '{"file_path":"README.md"}' });
  const text = await readFile(join(directory, "workspace", "README.md"), "utf8");
  record("tool/result", { message: { toolCallId: "fixture-read", isError: false,
    content: [{ type: "text", text }] } });
  const answer = text.match(/^projectName: (.+)$/m)?.[1] ?? "NO_FIELD";
  record("assistant/message", { message: { content: [{ type: "text", text: answer }] } });
  record("step/end", { turn: 1, step: 1 });
  record("turn/end", { turn: 1, reason: { kind: "completed" } });
  await recorder.close();
} else await recorder.flush();

process.once("message", async (message) => {
  try {
    if (message?.type !== (scenario === "page-cancel" ? "synthetic-cancel" : "fixture-exit")
        || scenario === "process-interrupt") throw new Error("Unexpected fixture command");
    if (scenario === "page-cancel") {
      record("step/end", { turn: 1, step: 1 });
      record("turn/end", { turn: 1, reason: { kind: "aborted", reason: { kind: "user" } } });
      await recorder.close();
    }
    clearTimeout(watchdog);
    process.removeAllListeners("disconnect");
    process.disconnect();
  } catch (error) {
    console.error(error);
    process.exit(2);
  }
});
process.send({ type: "checkpoint", runId: recorder.runId, sessionId, lastSeq: seq - 1 });
