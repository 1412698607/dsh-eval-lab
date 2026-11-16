import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { syncBuiltinESMExports } from "node:module";
import { tmpdir } from "node:os";
import { basename, isAbsolute, join, relative, resolve } from "node:path";
import { writeStatus } from "../src/session-status.js";

async function setup(t) {
  const directory = await fs.mkdtemp(join(tmpdir(), "dsh-eval-lab-status-cleanup-"));
  const target = resolve(directory);
  const withinTemp = relative(resolve(tmpdir()), target);
  assert.ok(withinTemp && !withinTemp.startsWith("..") && !isAbsolute(withinTemp));
  assert.ok(basename(target).startsWith("dsh-eval-lab-status-cleanup-"));
  t.after(async () => {
    t.mock.restoreAll();
    syncBuiltinESMExports();
    await fs.rm(target, { recursive: true, force: true });
  });
  const path = join(directory, "status.json");
  await fs.writeFile(path, "old");
  return { directory, path };
}

function replace(t, name, implementation) {
  t.mock.method(fs, name, implementation(fs[name]));
  syncBuiltinESMExports();
}

test("successful status replacement avoids deleting the consumed temporary name", async (t) => {
  const { directory, path } = await setup(t);
  let unlinks = 0;
  replace(t, "unlink", (original) => async (...args) => { unlinks++; return original(...args); });
  await writeStatus(path, { saved: true });
  assert.deepEqual(JSON.parse(await fs.readFile(path, "utf8")), { saved: true });
  assert.deepEqual(await fs.readdir(directory), ["status.json"]);
  assert.equal(unlinks, 0);
});

test("retried status replacement consumes one temporary file without cleanup after success", async (t) => {
  const { directory, path } = await setup(t);
  const sources = [];
  let unlinks = 0;
  replace(t, "unlink", (original) => async (...args) => { unlinks++; return original(...args); });
  replace(t, "rename", (original) => async (source, destination) => {
    sources.push(source);
    if (sources.length <= 3) {
      assert.equal(await fs.readFile(path, "utf8"), "old");
      throw Object.assign(new Error("transient replacement failure"), {
        code: ["EPERM", "EACCES", "EBUSY"][sources.length - 1],
      });
    }
    return original(source, destination);
  });
  await writeStatus(path, { saved: true });
  assert.equal(sources.length, 4);
  assert.equal(new Set(sources).size, 1);
  assert.deepEqual(JSON.parse(await fs.readFile(path, "utf8")), { saved: true });
  assert.deepEqual(await fs.readdir(directory), ["status.json"]);
  assert.equal(unlinks, 0);
});

test("failed status replacements still remove their temporary file and retain the old target", async (t) => {
  for (const [code, expectedAttempts] of [["EPERM", 6], ["ENOSPC", 1]]) {
    await t.test(code, async (t) => {
      const { directory, path } = await setup(t);
      const failure = Object.assign(new Error("replacement failed"), { code });
      const sources = [];
      const removed = [];
      replace(t, "rename", () => async (source) => { sources.push(source); throw failure; });
      replace(t, "unlink", (original) => async (source) => { removed.push(source); return original(source); });
      await assert.rejects(writeStatus(path, { saved: true }), (error) => error === failure);
      assert.equal(sources.length, expectedAttempts);
      assert.equal(new Set(sources).size, 1);
      assert.deepEqual(removed, [sources[0]]);
      assert.equal(await fs.readFile(path, "utf8"), "old");
      assert.deepEqual(await fs.readdir(directory), ["status.json"]);
    });
  }
});

test("a partially created temporary status is removed when its write rejects", async (t) => {
  const { directory, path } = await setup(t);
  const failure = Object.assign(new Error("partial write failed"), { code: "ENOSPC" });
  let created;
  let renames = 0;
  const removed = [];
  replace(t, "writeFile", (original) => async (source, _data, options) => {
    created = source;
    await original(source, "partial", options);
    throw failure;
  });
  replace(t, "rename", () => async () => { renames++; });
  replace(t, "unlink", (original) => async (source) => { removed.push(source); return original(source); });
  await assert.rejects(writeStatus(path, { saved: true }), (error) => error === failure);
  assert.equal(renames, 0);
  assert.deepEqual(removed, [created]);
  assert.equal(await fs.readFile(path, "utf8"), "old");
  assert.deepEqual(await fs.readdir(directory), ["status.json"]);
});

test("a failed cleanup remains visible and leaves the unremoved temporary evidence", async (t) => {
  const { directory, path } = await setup(t);
  const renameFailure = Object.assign(new Error("replacement failed"), { code: "ENOSPC" });
  const cleanupFailure = Object.assign(new Error("cleanup failed"), { code: "EACCES" });
  let temporary;
  const removed = [];
  replace(t, "rename", () => async (source) => { temporary = source; throw renameFailure; });
  replace(t, "unlink", () => async (source) => { removed.push(source); throw cleanupFailure; });
  await assert.rejects(writeStatus(path, { saved: true }), (error) => error === cleanupFailure);
  assert.deepEqual(removed, [temporary]);
  assert.equal(await fs.readFile(path, "utf8"), "old");
  assert.deepEqual(JSON.parse(await fs.readFile(temporary, "utf8")), { saved: true });
  assert.deepEqual((await fs.readdir(directory)).sort(), ["status.json", basename(temporary)].sort());
});
