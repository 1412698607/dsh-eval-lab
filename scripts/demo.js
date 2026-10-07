import { resolve } from "node:path";
import { createRecorder } from "../src/recorder.js";

const recorder = createRecorder({ outputDir: resolve("runs") });
const sessionId = "demo-session";
const start = Date.now();
const events = [
  ["turn/start", { turn: 1 }],
  ["user/message", {
    id: "demo-user", role: "user", source: { kind: "user" },
    content: [{ type: "text", text: "读取 README.md 并告诉我项目名称" }],
  }],
  ["step/start", { turn: 1, step: 1 }],
  ["tool/call", { turn: 1, step: 1, callId: "call-1", name: "read_file", arguments: '{"path":"README.md"}' }],
  ["tool/result", { turn: 1, step: 1, message: {
    id: "demo-result", role: "tool", toolCallId: "call-1",
    source: { kind: "tool", callId: "call-1" },
    content: [{ type: "text", text: "# dsh-eval-lab" }],
  } }],
  ["assistant/message", { turn: 1, step: 1, stream: [], message: {
    id: "demo-assistant", role: "assistant", source: { kind: "model", provider: "demo", model: "simulated" },
    content: [{ type: "text", text: "项目名称是 dsh-eval-lab。" }],
  } }],
  ["step/end", { turn: 1, step: 1 }],
  ["turn/end", { turn: 1, reason: { kind: "completed" } }],
];
for (const [seq, [type, data]] of events.entries()) {
  const event = { seq, time: start + seq, type, data };
  if (["user/message", "tool/result", "assistant/message"].includes(type)) event.surfaceOp = "append";
  recorder.record(sessionId, event);
}
await recorder.close();
console.info("模拟数据演示完成（未调用模型，也未验证 Harness 事件 schema）。");
console.info(`输出：${recorder.runDir}`);
