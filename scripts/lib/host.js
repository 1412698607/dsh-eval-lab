import { readFile, readdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { supportedSessionVersion } from "../../src/metadata.js";

export const supportedCordisVersion = "4.0.4";
// Cordis 4.0.4 declares a const enum, erased from its JS exports.
// Source: @deepseek-ai/cordis/lib/types/fiber.d.ts, FiberState.ACTIVE.
export const HOST_FIBER_ACTIVE = 2;

export async function validateHost(modulesDir) {
  const versions = {};
  for (const [name, expected] of [
    ["@deepseek-ai/dsh-session", supportedSessionVersion],
    ["@deepseek-ai/cordis", supportedCordisVersion],
  ]) {
    const path = join(modulesDir, ...name.split("/"), "package.json");
    let manifest;
    try {
      manifest = JSON.parse(await readFile(path, "utf8"));
    } catch (cause) {
      throw new Error(`eval-lab: 无法读取宿主组件 ${name} 的版本：${path}`, { cause });
    }
    if (manifest.version !== expected) {
      throw new Error(`eval-lab: ${name} 版本不匹配，要求 ${expected}，实际 ${manifest.version}；目录：${modulesDir}`);
    }
    versions[name] = manifest.version;
  }
  return versions;
}

// Reuse installed packages; never install or change an existing DSH profile.
export async function locateHost(modulesDir, env = process.env) {
  if (modulesDir !== undefined) {
    const absolute = resolve(modulesDir);
    await validateHost(absolute);
    return absolute;
  }
  const cache = env.LOCALAPPDATA ? join(env.LOCALAPPDATA, "npm-cache", "_npx") : null;
  const failures = [];
  if (cache) {
    let entries = [];
    try { entries = await readdir(cache, { withFileTypes: true }); }
    catch (error) { if (error.code !== "ENOENT") throw error; }
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const candidate = join(cache, entry.name, "node_modules");
      try {
        await validateHost(candidate);
        return candidate;
      } catch (error) { failures.push(error.message); }
    }
  }
  throw new Error(`eval-lab: 未找到匹配的 dsh-session ${supportedSessionVersion} / Cordis ${supportedCordisVersion}。请传入已安装宿主的 node_modules 路径。${failures.length ? `\n${failures.join("\n")}` : ""}`);
}

export async function loadHost(modulesDir) {
  const versions = await validateHost(modulesDir);
  const requireHost = createRequire(join(modulesDir, "__eval_lab__.cjs"));
  const { Context } = await import(pathToFileURL(requireHost.resolve("@deepseek-ai/cordis")).href);
  const { default: SessionStore, SessionId } = await import(pathToFileURL(requireHost.resolve("@deepseek-ai/dsh-session")).href);
  return { Context, SessionStore, SessionId, versions };
}
