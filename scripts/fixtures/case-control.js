// Dedicated evaluation child only; keep the M2.3 lifecycle controller unchanged.
import { apply as installLifecycle } from "./live-control.js";
import { createRequire } from "node:module";
import { join } from "node:path";
import { createToolBridge, registerStatefulTools } from "../lib/tool-bridge.js";

export const name = "eval-case-control";
export const inject = ["agents", "sessions", "agentDefaultModel", "tools"];

export function apply(ctx) {
  installLifecycle(ctx);
  if (process.env.DSH_EVAL_STATEFUL === "1") {
    const requireHost = createRequire(join(process.env.DSH_EVAL_HOST_MODULES, "__eval_bridge__.cjs"));
    const { defineTool } = requireHost("@deepseek-ai/dsh-tools");
    const bridge = createToolBridge(process, process.env.DSH_EVAL_CASE_RUN_ID, (message) => {
      if (process.connected) process.send({ type: "bridge-error", message });
      for (const agent of ctx.agents.list()) agent.cancel({ kind: "user" });
    });
    ctx.effect(() => () => bridge.close());
    registerStatefulTools(ctx, defineTool, bridge);
  }
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
