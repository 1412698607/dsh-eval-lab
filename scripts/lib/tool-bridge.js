import { randomUUID } from "node:crypto";

export function registerStatefulTools(ctx, defineTool, bridge) {
  for (const operation of ["read", "list"]) {
    ctx.tools.register(defineTool({
      name: `eval_${operation}`,
      description: operation === "read" ? "Read a virtual fixture file. Retry temporary read failures."
        : "List virtual fixture file paths under a directory; use . for the root.",
      parameters: { path: { type: "string", required: true, description: "Relative POSIX path in the virtual fixture." } },
      output: { schema: { type: "string" }, render: (_args, text) => [{ type: "text", text }] },
      execute: (args, exec) => bridge.request(operation, args, exec),
    }));
  }
}

// One dedicated Harness child. All operations are immediate in Python; abort closes
// the local waiter. A response arriving after abort cannot resume a tool call.
export function createToolBridge(channel, caseRunId, onFailure, timeoutMs = 5000) {
  const pending = new Map();
  let closed = false;
  const fail = (message) => {
    if (closed) return;
    closed = true;
    for (const entry of [...pending.values()]) entry.finish(new Error(message));
    onFailure(message);
  };
  const receive = (message) => {
    if (message?.type !== "tool-response") return;
    const entry = pending.get(message.requestId);
    if (!entry) return; // Late or duplicate response; never execute again.
    if (message.bridgeVersion !== 1 || message.caseRunId !== caseRunId || message.sessionId !== entry.sessionId
        || typeof message.isError !== "boolean" || typeof message.text !== "string") {
      fail("Invalid bridge response identity or payload");
      return;
    }
    entry.finish(null, message);
  };
  const disconnected = () => fail("Bridge disconnected");
  channel.on("message", receive);
  channel.on("disconnect", disconnected);
  return {
    request(operation, args, exec) {
      return new Promise((resolve, reject) => {
        const sessionId = exec.agent?.session.id;
        if (!sessionId || closed || exec.signal.aborted || !channel.connected) {
          if (!exec.signal.aborted && !closed) fail("Bridge unavailable");
          reject(new Error("Bridge unavailable or call cancelled"));
          return;
        }
        const requestId = randomUUID();
        let timer;
        const abort = () => finish(new Error("Tool call cancelled"));
        const finish = (error, response) => {
          if (!pending.delete(requestId)) return;
          clearTimeout(timer);
          exec.signal.removeEventListener("abort", abort);
          if (error) reject(error);
          else if (response.isError) reject(new Error(response.text));
          else resolve(response.text);
        };
        pending.set(requestId, { sessionId, finish });
        exec.signal.addEventListener("abort", abort, { once: true });
        timer = setTimeout(() => fail("Bridge response deadline reached"), timeoutMs);
        try {
          channel.send({ type: "tool-request", bridgeVersion: 1, requestId, caseRunId, sessionId, operation, arguments: args },
            (error) => { if (error) fail("Bridge send failed"); });
        } catch { fail("Bridge send failed"); }
      });
    },
    close() {
      closed = true;
      channel.off("message", receive);
      channel.off("disconnect", disconnected);
      for (const entry of [...pending.values()]) entry.finish(new Error("Bridge closed"));
    },
  };
}
