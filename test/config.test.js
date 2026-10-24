import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readdir, readFile, rm } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { basename, isAbsolute, join, relative, resolve } from "node:path";
import { resolveConfig, DEFAULT_MAX_PENDING_BYTES, DEFAULT_MAX_EVENT_BYTES } from "../src/config.js";
import { apply } from "../src/index.js";

test("explicit outputDir takes priority even over an invalid environment value", () => {
  const outputDir = resolve("explicit-runs");
  assert.deepEqual(resolveConfig({ outputDir }, { env: { DSH_EVAL_OUTPUT_DIR: "relative" } }), { outputDir, maxPendingBytes: DEFAULT_MAX_PENDING_BYTES, maxEventBytes: DEFAULT_MAX_EVENT_BYTES });
});

test("environment outputDir is used when no explicit override is supplied", () => {
  const outputDir = resolve("env-runs");
  const options = { env: { DSH_EVAL_OUTPUT_DIR: outputDir } };
  assert.deepEqual(resolveConfig({}, options), { outputDir, maxPendingBytes: DEFAULT_MAX_PENDING_BYTES, maxEventBytes: DEFAULT_MAX_EVENT_BYTES });
  assert.deepEqual(resolveConfig({ outputDir: undefined }, options), { outputDir, maxPendingBytes: DEFAULT_MAX_PENDING_BYTES, maxEventBytes: DEFAULT_MAX_EVENT_BYTES });
});

test("default outputDir belongs to the user home, independent of the project location", () => {
  assert.equal(resolveConfig({}, { env: {} }).outputDir, join(homedir(), ".dsh-eval-lab", "runs"));
  const homeDir = resolve(tmpdir(), "another-user");
  assert.equal(resolveConfig({}, { env: {}, homeDir }).outputDir, join(homeDir, ".dsh-eval-lab", "runs"));
});

test("invalid explicit overrides fail instead of falling back to the environment", () => {
  for (const outputDir of ["", "runs", null, false, 123]) {
    assert.throws(() => resolveConfig({ outputDir }, {
      env: { DSH_EVAL_OUTPUT_DIR: resolve("valid-env") },
    }), /config.outputDir.*绝对路径/);
  }
});

test("invalid environment overrides fail instead of falling back to the home directory", () => {
  for (const outputDir of ["", "runs"]) {
    assert.throws(() => resolveConfig({}, { env: { DSH_EVAL_OUTPUT_DIR: outputDir } }), /DSH_EVAL_OUTPUT_DIR.*绝对路径/);
  }
});

test("non-object plugin configuration is rejected with a useful error", () => {
  for (const config of [null, "runs", 123, []]) {
    assert.throws(() => resolveConfig(config), /config 必须是对象/);
  }
});

test("pending byte limit defaults to 16 MiB and rejects invalid explicit values", () => {
  assert.equal(DEFAULT_MAX_PENDING_BYTES, 16 * 1024 * 1024);
  assert.equal(resolveConfig({ maxPendingBytes: 1024 }, { env: {} }).maxPendingBytes, 1024);
  for (const maxPendingBytes of [0, -1, 1.5, null, "1024", Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => resolveConfig({ maxPendingBytes }, { env: {} }), /maxPendingBytes/);
  }
});

test("plugin mounting uses the environment directory and persists its events there", async (t) => {
  const outputDir = await mkdtemp(join(tmpdir(), "dsh-eval-lab-env-"));
  const target = resolve(outputDir);
  const withinTemp = relative(resolve(tmpdir()), target);
  assert.ok(withinTemp && !withinTemp.startsWith("..") && !isAbsolute(withinTemp));
  assert.ok(basename(target).startsWith("dsh-eval-lab-"));
  const previous = process.env.DSH_EVAL_OUTPUT_DIR;
  t.after(async () => {
    if (previous === undefined) delete process.env.DSH_EVAL_OUTPUT_DIR;
    else process.env.DSH_EVAL_OUTPUT_DIR = previous;
    await rm(target, { recursive: true, force: true });
  });
  process.env.DSH_EVAL_OUTPUT_DIR = outputDir;
  const hooks = new Map();
  let dispose;
  apply({
    on: (type, listener) => hooks.set(type, listener),
    effect: (setup) => { dispose = setup(); },
  });
  try {
    hooks.get("session/event")({ id: "env-session" }, { seq: 0, type: "turn/start", data: { turn: 1 } });
    await hooks.get("session/flush")({ id: "env-session" });
  } finally { await dispose(); }
  const [runId] = await readdir(outputDir);
  const files = await readdir(join(outputDir, runId));
  const trace = files.find((file) => file.endsWith(".jsonl"));
  const row = JSON.parse(await readFile(join(outputDir, runId, trace), "utf8"));
  assert.equal(row.sessionId, "env-session");
});
