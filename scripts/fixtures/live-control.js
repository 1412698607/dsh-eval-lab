// Test-only lifecycle adapter for a dedicated CLI child, never a distributed bundle.
export const name = "eval-live-control";
export const inject = ["agents", "sessions"];

export function apply(ctx) {
  if (!process.send) throw new Error("live-control 只允许在专用 IPC 子进程加载");
  let streamed = false;
  ctx.on("agent/assistant-stream", ({ agent, frame }) => {
    if (streamed || frame.type !== "chunk") return;
    streamed = true;
    process.send({ type: "streaming", sessionId: agent.session.id });
  });
  const receive = async (message) => {
    if (message?.type === "cancel") {
      ctx.agents.get(message.sessionId)?.cancel({ kind: "user" });
    } else if (message?.type === "shutdown") {
      // Windows child.kill('SIGINT') terminates forcibly; request launcher disposal via IPC.
      const agents = ctx.agents.list();
      for (const agent of agents) agent.cancel({ kind: "user" });
      await Promise.all(agents.map((agent) => agent.whenIdle()));
      for (const agent of agents) await ctx.sessions.flush(agent.session);
      ctx.get("appExit")(0);
    }
  };
  const listener = (message) => receive(message).catch((error) => {
    console.error("[live-control]", error);
    ctx.get("appExit")(1);
  });
  const disconnected = () => listener({ type: "shutdown" });
  process.on("message", listener);
  process.on("disconnect", disconnected);
  ctx.effect(() => () => {
    process.off("message", listener);
    process.off("disconnect", disconnected);
    if (process.connected) process.disconnect();
  });
}
