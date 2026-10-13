import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { inspectRun } from "../src/inspect.js";

export async function main(args, output = console) {
  if (args.length !== 2 || args[0] !== "--run" || !args[1] || args[1].startsWith("--")) {
    output.error("用法：npm.cmd run inspect -- --run <运行目录>（退出码不代表 Agent 任务通过）");
    return 2;
  }
  const report = await inspectRun(args[1]);
  output.log(JSON.stringify(report, null, 2));
  return report.exitCode;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = await main(process.argv.slice(2));
}
