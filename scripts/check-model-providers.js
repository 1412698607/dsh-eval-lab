import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { HOST_FIBER_ACTIVE, loadHost, locateHost } from "./lib/host.js";
import { validateModelProviders } from "./lib/model-providers.js";

// Checks local registration and credential presence; never requests a generation
// or endpoint discovery. Missing credentials do not prevent catalog validation.
if (!process.argv[2]) throw new Error("Usage: check-model-providers.js <case.json> [modules-dir]");
const caseData = JSON.parse(await readFile(resolve(process.argv[2]), "utf8"));
const providers = validateModelProviders(caseData.modelProviders);
const modulesDir = await locateHost(process.argv[3]);
const { Context, versions } = await loadHost(modulesDir);
const hostModule = (name) => import(pathToFileURL(join(modulesDir, "@deepseek-ai", name, "lib", "index.js")).href);
const llm = await hostModule("dsh-llm");
const credentials = await hostModule("dsh-credentials-local");
const pi = await hostModule("dsh-llm-pi-ai");
const ctx = new Context();
const fibers = [];
try {
  for (const [plugin, config] of [
    [llm.default, undefined],
    [credentials.default, { path: join(resolve(process.env.DSH_HOME || join(homedir(), ".dsh")), ".credentials.yaml"), watch: false }],
    [pi, { providers }],
  ]) {
    const fiber = await ctx.plugin(plugin, config);
    fibers.push(fiber);
    assert.equal(fiber.state, HOST_FIBER_ACTIVE, "Host component must be active");
  }
  const registered = ctx.llm.listProviders();
  const routes = [];
  for (const [provider, profile] of Object.entries(providers)) {
    assert.ok(registered.some((entry) => entry.id === provider), "Provider route was not registered");
    const models = await ctx.llm.listModels(provider);
    for (const expected of profile.models) {
      assert.ok(models.some((model) => model.id === expected.id), "Declared model missing from local catalog");
    }
    const credential = await ctx.credentials.describe(profile.apiKeyEnv);
    routes.push({ provider, models: models.map((model) => model.id), apiKeyEnv: profile.apiKeyEnv,
      credentialConfigured: credential.configured });
  }
  const ready = routes.length > 0 && routes.every((route) => route.credentialConfigured);
  console.info(JSON.stringify({ modelProviderCheckFormatVersion: 1, modelCalled: false, versions,
    registrationVerified: true, endpointVerified: false, credentialsPresent: ready, routes }, null, 2));
  process.exitCode = ready ? 0 : 2;
} finally {
  for (const fiber of fibers.reverse()) await fiber.dispose();
}
