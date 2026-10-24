import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { checkpoint, isUserSubmission } from "../scripts/web-lifecycle-live.js";
import { apply as observe } from "../scripts/fixtures/web-lifecycle-observer.js";
import { createRecorder } from "../src/recorder.js";

test("Web submission count excludes runtime context and skill catalogs", () => {
  for (const sourceKind of ["runtime-context", "skill-catalog", undefined, null]) {
    assert.equal(isUserSubmission({ kind: "session/event", type: "user/message", sourceKind }), false);
  }
  assert.equal(isUserSubmission({ kind: "session/event", type: "user/message", sourceKind: "user" }), true);
});

test("Web operation reads the real recorder checkpoint without a flush call", async () => {
  const directory = await mkdtemp(join(tmpdir(), "web-live-checkpoint-"));
  try {
    const recorder = createRecorder({ outputDir: join(directory, "traces") });
    recorder.record("one", { seq: 10, type: "turn/start", data: { turn: 1 } });
    await recorder.flush();
    assert.deepEqual(checkpoint(directory, "one"), {
      runId: recorder.runId, sessionId: "one", runDir: `traces/${recorder.runId}`, afterSeq: 10,
    });
    assert.throws(() => checkpoint(directory, "other"), /not registered/);
    await recorder.close();
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("Web observer records source and one real stream notification without control calls", async () => {
  const directory = await mkdtemp(join(tmpdir(), "web-live-observer-"));
  const previous = process.env.DSH_EVAL_WEB_OBSERVATIONS;
  const hooks = new Map();
  let dispose;
  try {
    process.env.DSH_EVAL_WEB_OBSERVATIONS = join(directory, "observations.jsonl");
    observe({ agentDefaultModel: { currentSelection: () => ({ provider: "test", model: "test" }) },
      on: (name, handler) => hooks.set(name, handler), effect: (effect) => { dispose = effect(); },
      sessions: { flush: () => assert.fail("Observer must not flush") } });
    hooks.get("session/event")({ id: "one" }, { seq: 3, type: "user/message", data: { source: { kind: "runtime-context" } } });
    const frame = { agent: { session: { id: "one" }, cancel: () => assert.fail("Observer must not cancel") }, frame: { type: "chunk" } };
    hooks.get("agent/assistant-stream")(frame);
    hooks.get("agent/assistant-stream")(frame);
    dispose();
    dispose = null;
    const rows = (await readFile(process.env.DSH_EVAL_WEB_OBSERVATIONS, "utf8")).trim().split("\n").map(JSON.parse);
    assert.equal(rows.find((item) => item.type === "user/message").sourceKind, "runtime-context");
    assert.equal(rows.filter((item) => item.kind === "model/first-chunk").length, 1);
    assert.equal(rows.at(-1).kind, "observer/disposed");
  } finally {
    dispose?.();
    if (previous === undefined) delete process.env.DSH_EVAL_WEB_OBSERVATIONS;
    else process.env.DSH_EVAL_WEB_OBSERVATIONS = previous;
    await rm(directory, { recursive: true, force: true });
  }
});
