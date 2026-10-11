import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, isAbsolute, join, relative, resolve } from "node:path";
import { locateHost, loadHost, supportedCordisVersion, validateHost } from "../scripts/lib/host.js";
import { supportedSessionVersion } from "../src/metadata.js";

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), "dsh-eval-lab-host-"));
  const target = resolve(root);
  const withinTemp = relative(resolve(tmpdir()), target);
  assert.ok(withinTemp && !withinTemp.startsWith("..") && !isAbsolute(withinTemp));
  assert.ok(basename(target).startsWith("dsh-eval-lab-"));
  t.after(() => rm(target, { recursive: true, force: true }));
  return root;
}

async function writeVersions(modulesDir, sessionVersion = supportedSessionVersion, cordisVersion = supportedCordisVersion) {
  for (const [name, version] of [["dsh-session", sessionVersion], ["cordis", cordisVersion]]) {
    const dir = join(modulesDir, "@deepseek-ai", name);
    await mkdir(dir, { recursive: true });
    await writeFile(join(dir, "package.json"), JSON.stringify({ name: `@deepseek-ai/${name}`, version }));
  }
}

test("host validation reports both matching component versions", async (t) => {
  const root = await fixture(t);
  await writeVersions(root);
  assert.deepEqual(await validateHost(root), {
    "@deepseek-ai/dsh-session": supportedSessionVersion,
    "@deepseek-ai/cordis": supportedCordisVersion,
  });
});

test("explicit host mismatch cannot silently select a different cached installation", async (t) => {
  const root = await fixture(t);
  const explicit = join(root, "wrong");
  await writeVersions(explicit, "9.9.9");
  await writeVersions(join(root, "npm-cache", "_npx", "matching", "node_modules"));
  await assert.rejects(locateHost(explicit, { LOCALAPPDATA: root }), /dsh-session.*要求 0\.2\.0-rc\.2.*实际 9\.9\.9/);
});

test("Cordis mismatch is rejected before importing host code", async (t) => {
  const root = await fixture(t);
  await writeVersions(root, supportedSessionVersion, "0.0.0");
  await assert.rejects(loadHost(root), /cordis.*要求 4\.0\.4.*实际 0\.0\.0/);
});

test("missing and malformed manifests give the component name and read error", async (t) => {
  const root = await fixture(t);
  await assert.rejects(validateHost(root), /无法读取宿主组件 @deepseek-ai\/dsh-session/);
  await writeVersions(root);
  await writeFile(join(root, "@deepseek-ai", "cordis", "package.json"), "{");
  await assert.rejects(validateHost(root), /无法读取宿主组件 @deepseek-ai\/cordis/);
});

test("cache discovery skips mismatches and explains when no baseline is available", async (t) => {
  const root = await fixture(t);
  const cache = join(root, "npm-cache", "_npx");
  await writeVersions(join(cache, "a-wrong", "node_modules"), "9.9.9");
  await assert.rejects(locateHost(undefined, { LOCALAPPDATA: root }), /未找到匹配.*\n.*实际 9\.9\.9/);
  const matching = join(cache, "b-matching", "node_modules");
  await writeVersions(matching);
  assert.equal(await locateHost(undefined, { LOCALAPPDATA: root }), matching);
});
