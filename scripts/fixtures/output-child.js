import { runHostSmoke } from "../lib/host-smoke.js";
import { createRecorder } from "../../src/recorder.js";

const [, , modulesDir, outputDir, mode] = process.argv;
if (!["normal", "write-error", "abrupt-exit"].includes(mode)) throw new Error("未知输出检查模式");
// No success text here: the parent asserts the entire child's stdout is empty.
if (mode === "abrupt-exit") {
  const recorder = createRecorder({ outputDir });
  recorder.record("interrupted", { seq: 0, type: "turn/start" });
  await recorder.flush();
  // Exit this dedicated fixture without close; never terminate a user's host.
  process.exit(0);
} else await runHostSmoke({ modulesDir, outputDir, failWrite: mode === "write-error" });
