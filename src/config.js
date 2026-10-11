import { homedir } from "node:os";
import { isAbsolute, join } from "node:path";

export function resolveConfig(config = {}, { env = process.env, homeDir = homedir() } = {}) {
  if (config === null || typeof config !== "object" || Array.isArray(config)) {
    throw new TypeError("eval-lab: config 必须是对象");
  }
  let outputDir;
  let source;
  if (config.outputDir !== undefined) {
    outputDir = config.outputDir;
    source = "config.outputDir";
  } else if (env.DSH_EVAL_OUTPUT_DIR !== undefined) {
    outputDir = env.DSH_EVAL_OUTPUT_DIR;
    source = "DSH_EVAL_OUTPUT_DIR";
  } else {
    outputDir = join(homeDir, ".dsh-eval-lab", "runs");
    source = "默认日志目录";
  }
  // Validate the selected value; an invalid override must never silently fall back.
  if (typeof outputDir !== "string" || !isAbsolute(outputDir)) {
    throw new TypeError(`eval-lab: ${source} 必须是非空的绝对路径`);
  }
  return { outputDir };
}
