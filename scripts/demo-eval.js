import { readFile, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createRecorder } from "../src/recorder.js";
import { pluginVersion } from "../src/metadata.js";

// Public synthetic events pass through the actual recorder, not a second status implementation.
export async function recordExample(casePath, events, outputDir, { seal = true } = {}) {
  const caseData = JSON.parse(await readFile(casePath, "utf8"));
  const caseRunId = randomUUID();
  const sessionId = `synthetic-${caseRunId}`;
  const recorder = createRecorder({ outputDir: resolve(outputDir) });
  for (const event of events) {
    if (!recorder.record(sessionId, event)) throw new Error("Synthetic recording was rejected");
  }
  if (seal) await recorder.close();
  else await recorder.flush();
  const evidencePath = join(recorder.runDir, "evidence.json");
  await writeFile(evidencePath, JSON.stringify({
    evidenceFormatVersion: 1, caseRunId, caseId: caseData.caseId,
    runId: recorder.runId, sessionId, runDir: ".", source: "synthetic",
    configuration: { ...caseData.configRef, pluginVersion },
    budgetEnforcement: { timeoutSeconds: false }, execution: { status: "completed", exitCode: 0, signal: null },
  }, null, 2) + "\n", { flag: "wx" });
  return { casePath: relative(resolve("."), resolve(casePath)), evidencePath, caseRunId, runId: recorder.runId, sessionId };
}

export async function main() {
  const outputDir = resolve("runs", "eval-demo", randomUUID());
  const examples = [];
  for (const name of ["read-project", "missing-file"]) {
    const casePath = fileURLToPath(new URL(`../fixtures/evaluation/${name}.case.json`, import.meta.url));
    const events = JSON.parse(await readFile(new URL(`../fixtures/evaluation/${name}.events.json`, import.meta.url), "utf8"));
    examples.push(await recordExample(casePath, events, outputDir));
  }
  console.info(JSON.stringify({ source: "synthetic", modelCalled: false, examples }, null, 2));
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
