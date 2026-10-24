import { readdir } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

let count = 0;
for (const directory of ["src", "scripts", "test", "dsh_eval/web"]) {
  const root = new URL(`../${directory}/`, import.meta.url);
  for (const entry of await readdir(root, { recursive: true })) {
    if (!entry.endsWith(".js")) continue;
    const result = spawnSync(process.execPath, ["--check", join(fileURLToPath(root), entry)], {
      stdio: "inherit", windowsHide: true,
    });
    if (result.error) throw result.error;
    if (result.status !== 0) process.exit(result.status ?? 1);
    count++;
  }
}
console.info(`语法检查通过：${count} 个 JavaScript 文件。`);
