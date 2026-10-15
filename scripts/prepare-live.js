import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { locateHost, validateHost } from "./lib/host.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const modulesDir = await locateHost(process.argv[2]);
const versions = await validateHost(modulesDir);
const cli = join(modulesDir, "@deepseek-ai", "dsh", "lib", "bin.js");
const cliVersion = JSON.parse(await readFile(join(modulesDir, "@deepseek-ai", "dsh", "package.json"), "utf8")).version;
if (cliVersion !== versions["@deepseek-ai/dsh-session"]) throw new Error("CLI 与会话组件版本不匹配");
const checkDir = join(root, "runs", "live", randomUUID());
const home = join(checkDir, "home");
const workspace = join(checkDir, "workspace");
// Reference the existing store; never copy credentials into generated artifacts.
const credentialPath = join(resolve(process.env.DSH_HOME || join(homedir(), ".dsh")), ".credentials.yaml");
await mkdir(workspace, { recursive: true });
await copyFile(join(root, "fixtures", "live-read", "README.md"), join(workspace, "README.md"));
const env = { ...process.env, DSH_HOME: home, DSH_TELEMETRY_DISABLED: "1" };
for (const profile of ["headless", "web"]) {
  execFileSync(process.execPath, [cli, "plugin", "--profile", profile, "add",
    `link:${root.replaceAll("\\", "/")}`, "--offline", "--ignore-scripts",
    "--store-dir", join(checkDir, "pnpm-store")], {
    cwd: workspace, env, stdio: "inherit", windowsHide: true, timeout: 120000,
  });
  const patch = [
    { id: "credentials", config: { path: credentialPath, watch: false } },
    { id: "sandbox-policy", config: { mode: "read-only", workspaceRoot: workspace } },
    { id: "session-title-llm", disabled: true },
  ];
  // JSON is a YAML subset, avoiding a new dependency for this local patch.
  await writeFile(join(home, "profiles", profile, "cordis.patch.yml"), JSON.stringify(patch, null, 2) + "\n");
}
const controlPatch = join(checkDir, "control.patch.yml");
await writeFile(controlPatch, JSON.stringify([{ insert: [{
  id: "eval-live-control", name: fileURLToPath(new URL("./fixtures/live-control.js", import.meta.url)),
}] }], null, 2) + "\n");
await writeFile(join(checkDir, "setup.json"), JSON.stringify({
  setupFormatVersion: 1, cli, cliVersion, modulesDir, versions, home, workspace, controlPatch,
}, null, 2) + "\n");
console.info(`联调目录：${checkDir}`);
console.info("已在独立 home 的 headless / web profile 安装本地插件；现有 profile 保持不变。");
