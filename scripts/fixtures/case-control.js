// Dedicated evaluation child only; keep the M2.3 lifecycle controller unchanged.
import { apply as installLifecycle } from "./live-control.js";

export const name = "eval-case-control";
export const inject = ["agents", "sessions", "agentDefaultModel"];

export function apply(ctx) {
  installLifecycle(ctx);
  ctx.on("agent/created", ({ agent }) => {
    process.send({ type: "selection", sessionId: agent.session.id,
      selection: ctx.agentDefaultModel.currentSelection() });
  });
  ctx.on("session/event", (session, event) => {
    if (event.type !== "request/header") return;
    const { provider, model } = event.data.header.config;
    process.send({ type: "request-route", sessionId: session.id, provider, model });
  });
}
