import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { resolve, join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { locateHost } from "./lib/host.js";

const modulesDir = await locateHost(process.argv[2]);
const outputDir = resolve("runs", "output-check", randomUUID());
for (const mode of ["normal", "write-error"]) {
  let output;
  try {
    output = await promisify(execFile)(process.execPath, [
      fileURLToPath(new URL("./fixtures/output-child.js", import.meta.url)),
      modulesDir, join(outputDir, mode), mode,
    ], { encoding: "utf8", windowsHide: true, timeout: 15000, maxBuffer: 1024 * 1024 });
  } catch (cause) {
    const hint = cause.code === "EPERM"
      ? "沙箱禁止创建子进程，请在外部终端运行 npm.cmd run check:output；当前不能视为已验证。"
      : "请查看 cause 中的子进程退出原因和 stderr。";
    throw new Error(`真实子进程输出检查未通过（${mode}，${cause.code ?? "未知错误"}）。${hint}`, { cause });
  }
  assert.equal(output.stdout, "", `${mode}: 子进程 stdout 必须保持为空`);
  assert.match(output.stderr, /\[eval-lab\] 日志目录：/);
  if (mode === "write-error") assert.match(output.stderr, /日志写入失败/);
  else assert.doesNotMatch(output.stderr, /日志写入失败/);
  console.info(`${mode}：真实组件子进程 stdout 为空，stderr 诊断检查通过。`);
}
console.info(`检查输出：${outputDir}`);
