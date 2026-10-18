import assert from "node:assert/strict";
import test from "node:test";
import { summarizeProtocol } from "../scripts/case-host.js";

const frames = [
  { type: "session", sessionId: "session-one" },
  { type: "status", phase: "turn_end", reason: { kind: "completed" } },
  { type: "final", text: "answer" },
];
const lines = (values) => values.map(JSON.stringify).join("\n") + "\n";

test("headless protocol binds the streamed session and end reason", () => {
  assert.deepEqual(summarizeProtocol(lines(frames), "session-one"), {
    valid: true, sessionId: "session-one", turnEndReason: { kind: "completed" },
  });
});

test("wrong session, missing final and malformed headless frames do not pass", () => {
  assert.equal(summarizeProtocol(lines(frames), "another-session").valid, false);
  assert.equal(summarizeProtocol(lines(frames.slice(0, -1)), "session-one").valid, false);
  assert.equal(summarizeProtocol("broken json", "session-one").valid, false);
});

test("protocol exposes cancellation without treating it as task completion", () => {
  const cancelled = structuredClone(frames);
  cancelled[1].reason = { kind: "aborted", reason: { kind: "user" } };
  const report = summarizeProtocol(lines(cancelled), "session-one");
  assert.equal(report.valid, true);
  assert.deepEqual(report.turnEndReason, cancelled[1].reason);
});
