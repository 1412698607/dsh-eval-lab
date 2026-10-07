import { createRecorder } from "./recorder.js";

export const name = "dsh-eval-lab";
export const inject = ["sessions"];

export function apply(ctx, config = {}) {
  const recorder = createRecorder({
    outputDir: config.outputDir,
    onError(error, sessionId) {
      console.error(`[eval-lab] 会话 ${sessionId} 的日志写入失败：`, error);
    },
  });

  ctx.on("session/event", (session, event) => recorder.record(session.id, event));
  ctx.on("session/flush", (session) => recorder.flush(session.id));
  ctx.on("dispose", () => recorder.close());
  console.info(`[eval-lab] 日志目录：${recorder.runDir}`);
}
