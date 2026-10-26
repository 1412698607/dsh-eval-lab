import test from "node:test";
import assert from "node:assert/strict";
import childProcess from "node:child_process";
import { mkdirSync } from "node:fs";
import { mkdtemp, mkdir, readFile, writeFile, rm } from "node:fs/promises";
import { syncBuiltinESMExports } from "node:module";
import { tmpdir } from "node:os";
import { basename, isAbsolute, join, relative, resolve } from "node:path";
import { prepareCase } from "../scripts/case-host.js";
import { createRecorder } from "../src/recorder.js";
import { inspectRun } from "../src/inspect.js";
import { validateModelProviders } from "../scripts/lib/model-providers.js";

async function setup(t, recorder) {
  const directory = await mkdtemp(join(tmpdir(), "dsh-eval-lab-case-config-"));
  const target = resolve(directory);
  const withinTemp = relative(resolve(tmpdir()), target);
  assert.ok(withinTemp && !withinTemp.startsWith("..") && !isAbsolute(withinTemp));
  assert.ok(basename(target).startsWith("dsh-eval-lab-case-config-"));
  t.after(() => rm(target, { recursive: true, force: true }));
  const caseData = { configRef: { profile: "headless", provider: "synthetic", model: "none" } };
  if (recorder !== undefined) caseData.recorder = recorder;
  await writeFile(join(directory, "case.json"), JSON.stringify(caseData));
  await mkdir(join(directory, "workspace"));
  const modules = join(directory, "modules");
  for (const [name, version] of [["dsh", "0.2.0-rc.2"], ["dsh-session", "0.2.0-rc.2"], ["cordis", "4.0.4"]]) {
    const path = join(modules, "@deepseek-ai", name);
    await mkdir(path, { recursive: true });
    await writeFile(join(path, "package.json"), JSON.stringify({ version }));
  }
  // The unit test isolates only installation; preparation still writes its real
  // profile/setup files. A separate no-model check uses the installed Harness.
  t.mock.method(childProcess, "execFileSync", () => {
    mkdirSync(join(directory, "home", "profiles", "headless"), { recursive: true });
  });
  syncBuiltinESMExports();
  t.after(() => { t.mock.restoreAll(); syncBuiltinESMExports(); });
  return { directory, modules };
}

const externalProviders = () => ({ bailian: { api: "openai-completions",
  baseURL: "https://dashscope.aliyuncs.com/compatible-mode/v1", apiKeyEnv: "DASHSCOPE_API_KEY",
  models: [{ id: "qwen3.7-plus", contextWindow: 1000000, maxTokens: 131072 }] } });

test("external routes reach the isolated profile and setup without importing another profile", async (t) => {
  const { directory, modules } = await setup(t);
  const caseData = JSON.parse(await readFile(join(directory, "case.json"), "utf8"));
  caseData.modelProviders = externalProviders();
  await writeFile(join(directory, "case.json"), JSON.stringify(caseData));
  const prepared = await prepareCase(directory, modules);
  const patch = JSON.parse(await readFile(join(prepared.home, "profiles", "headless", "cordis.patch.yml"), "utf8"));
  assert.deepEqual(patch.find((row) => row.id === "llm-pi-ai").config, { providers: externalProviders() });
  assert.deepEqual(prepared.modelProviders, caseData.modelProviders);
  assert.deepEqual(JSON.parse(await readFile(join(directory, "case.json"), "utf8")), caseData);
  assert.deepEqual(JSON.parse(await readFile(join(directory, "setup.json"), "utf8")).modelProviders, externalProviders());
});

test("invalid routes and literal secrets are rejected before installation", async (t) => {
  const { directory, modules } = await setup(t);
  let installed = false;
  t.mock.method(childProcess, "execFileSync", () => { installed = true; });
  syncBuiltinESMExports();
  const caseData = JSON.parse(await readFile(join(directory, "case.json"), "utf8"));
  const mutations = [
    (routes) => { routes.bailian.apiKey = "must-not-be-saved"; },
    (routes) => { routes.bailian.headers = { Authorization: "secret" }; },
    (routes) => { routes.bailian.baseURL = "https://user:secret@example.com/v1"; },
    (routes) => { routes.bailian.baseURL = "https://example.com/v1?key=secret"; },
    (routes) => { routes.bailian.baseURL = "https://example.com:99999/v1"; },
    (routes) => { routes.bailian.models[0].contextWindow = true; },
    (routes) => { routes.bailian.models.push({ ...routes.bailian.models[0] }); },
    (routes) => { routes["deepseek-official"] = routes.bailian; },
  ];
  for (const mutate of mutations) {
    caseData.modelProviders = externalProviders();
    mutate(caseData.modelProviders);
    await writeFile(join(directory, "case.json"), JSON.stringify(caseData));
    await assert.rejects(prepareCase(directory, modules));
  }
  for (const value of [null, [], true, { bailian: null }]) assert.throws(() => validateModelProviders(value));
  assert.equal(installed, false);
  await assert.rejects(readFile(join(directory, "setup.json")), { code: "ENOENT" });
});

test("prepared profiles resolve independent case recorder limits and defaults", async (t) => {
  const { directory, modules } = await setup(t, { maxEventBytes: 4 * 1024 * 1024, maxPendingBytes: 7 * 1024 * 1024 });
  const setupData = await prepareCase(directory, modules);
  const patch = JSON.parse(await readFile(join(setupData.home, "profiles", "headless", "cordis.patch.yml"), "utf8"));
  const expected = { maxEventBytes: 4 * 1024 * 1024, maxPendingBytes: 7 * 1024 * 1024 };
  assert.deepEqual(patch.find((entry) => entry.id === "eval-lab")?.config, expected);
  assert.deepEqual(setupData.recorder, expected);
  assert.deepEqual(JSON.parse(await readFile(join(directory, "setup.json"), "utf8")).recorder, expected);
});

test("omitted and partial recorder options retain the other default without rewriting the frozen case", async (t) => {
  const { directory, modules } = await setup(t);
  const original = await readFile(join(directory, "case.json"), "utf8");
  const setupData = await prepareCase(directory, modules);
  assert.deepEqual(setupData.recorder, { maxEventBytes: 1048576, maxPendingBytes: 16777216 });
  assert.equal(await readFile(join(directory, "case.json"), "utf8"), original);
  // Use a new execution directory for each fresh setup.json.
  const other = join(directory, "partial");
  await mkdir(join(other, "workspace"), { recursive: true });
  await mkdir(join(other, "home", "profiles", "headless"), { recursive: true });
  await writeFile(join(other, "case.json"), JSON.stringify({ configRef: { profile: "headless" }, recorder: { maxPendingBytes: 99 } }));
  assert.deepEqual((await prepareCase(other, modules)).recorder, { maxEventBytes: 1048576, maxPendingBytes: 99 });
});

test("invalid recorder options fail before installation", async (t) => {
  const { directory, modules } = await setup(t);
  for (const recorder of [null, [], "bad", { outputDir: "elsewhere" }, ...[true, null, "4", 0, -1, 1.5, 2 ** 53].flatMap((value) => [
    { maxEventBytes: value }, { maxPendingBytes: value },
  ])]) {
    await writeFile(join(directory, "case.json"), JSON.stringify({ configRef: { profile: "headless" }, recorder }));
    await assert.rejects(prepareCase(directory, modules));
  }
  assert.equal(childProcess.execFileSync.mock.callCount(), 0);
});

test("a large event uses the limits from the generated isolated profile", async (t) => {
  const { directory, modules } = await setup(t, { maxEventBytes: 4194304 });
  const setupData = await prepareCase(directory, modules);
  const patch = JSON.parse(await readFile(join(setupData.home, "profiles", "headless", "cordis.patch.yml"), "utf8"));
  const config = patch.find((entry) => entry.id === "eval-lab")?.config;
  const text = "x".repeat(1280 * 1024);
  const enlarged = createRecorder({ outputDir: join(directory, "raised"), ...config });
  assert.equal(enlarged.record("session", { seq: 0, text }), true);
  await enlarged.close();
  assert.equal((await inspectRun(enlarged.runDir)).exitCode, 0);
  const metadata = JSON.parse(await readFile(join(enlarged.runDir, "run.json"), "utf8"));
  assert.equal(metadata.maxEventBytes, 4194304);
  assert.equal(metadata.maxPendingBytes, 16777216);
  const defaults = createRecorder({ outputDir: join(directory, "default") });
  assert.equal(defaults.record("session", { seq: 0, text }), false);
  await assert.rejects(defaults.close(), AggregateError);
  assert.equal((await inspectRun(defaults.runDir)).exitCode, 1);
});
