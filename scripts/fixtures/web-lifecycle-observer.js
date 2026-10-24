// Observation only: no cancel, flush, tool, model, or appExit calls.
import { appendFileSync } from "node:fs";

export const name = "eval-web-observer";
export const inject = ["sessions", "agentDefaultModel"];

export function apply(ctx) {
  const path = process.env.DSH_EVAL_WEB_OBSERVATIONS;
  if (!path) throw new Error("Dedicated Web observation file required");
  const observe = (kind, data = {}) => appendFileSync(path,
    JSON.stringify({ observationVersion: 1, at: new Date().toISOString(), kind, pid: process.pid, ...data }) + "\n");
  const streamed = new Set();
  observe("observer/ready", { selection: ctx.agentDefaultModel.currentSelection() });
  ctx.on("session/event", (session, event) => {
    const data = { sessionId: session.id, seq: event.seq, type: event.type, cwd: session.header?.cwd ?? null };
    if (event.type === "user/message") data.sourceKind = event.data.source?.kind ?? null;
    if (event.type === "request/header") data.route = {
      provider: event.data.header.config.provider, model: event.data.header.config.model,
    };
    if (event.type === "turn/end") data.reason = event.data.reason;
    observe("session/event", data);
  });
  ctx.on("agent/assistant-stream", ({ agent, frame }) => {
    if (frame.type !== "chunk" || streamed.has(agent.session.id)) return;
    streamed.add(agent.session.id);
    observe("model/first-chunk", { sessionId: agent.session.id });
  });
  const signal = () => observe("process/SIGINT");
  process.on("SIGINT", signal);
  ctx.effect(() => () => {
    observe("observer/disposed");
    process.off("SIGINT", signal);
  });
}
