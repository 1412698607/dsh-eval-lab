import { runHostSmoke } from "../lib/host-smoke.js";

const [, , modulesDir, outputDir, mode] = process.argv;
if (!["normal", "write-error"].includes(mode)) throw new Error("未知输出检查模式");
// No success text here: the parent asserts the entire child's stdout is empty.
await runHostSmoke({ modulesDir, outputDir, failWrite: mode === "write-error" });
