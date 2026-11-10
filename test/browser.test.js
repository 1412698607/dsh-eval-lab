import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import vm from "node:vm";

const script = await readFile(new URL("../dsh_eval/web/app.js", import.meta.url), "utf8");

// Minimal DOM surface: execute the real page's event handlers and text rendering without a browser dependency.
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.value = ""; this.text = ""; this.listeners = new Map(); }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map((child) => child.textContent).join(" "); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this.text = ""; }
  addEventListener(type, callback) { this.listeners.set(type, callback); }
  setAttribute() {}
  scrollIntoView() {}
  focus() {}
  trigger(type) { this.listeners.get(type)?.(); }
}

async function viewer(items, artifact = null, requests = []) {
  const elements = new Map();
  const get = (id) => {
    if (!elements.has(id)) elements.set(id, new Element(id));
    return elements.get(id);
  };
  const context = vm.createContext({
    document: { getElementById: get, createElement: (tag) => new Element(tag), createDocumentFragment: () => new Element("fragment") },
    Node: Element, URLSearchParams, location: { hash: "#token=test-token" },
    sessionStorage: { setItem() {}, getItem() { return null; } }, window: { scrollTo() {} },
    fetch: async (path) => {
      requests.push(path);
      return { ok: true, json: async () => path.startsWith("/api/catalog") ? { items, warnings: [], truncated: false }
        : typeof artifact === "function" ? artifact(path) : artifact };
    },
  });
  vm.runInContext(script, context, { filename: "dsh_eval/web/app.js" });
  await new Promise(setImmediate);
  return get;
}

function findButton(element, label) {
  if (element.tag === "button" && element.textContent === label) return element;
  for (const child of element.children) {
    const found = findButton(child, label);
    if (found) return found;
  }
  return null;
}

function descendants(element, tag) {
  return [...(element.tag === tag ? [element] : []), ...element.children.flatMap((child) => descendants(child, tag))];
}

function literalText(element) {
  return element.text + element.children.map(literalText).join("");
}

function diagnosticResult() {
  return { kind: "evaluation", links: [], assertionTrace: { id: "runs:trace/" + "a".repeat(64) + ".jsonl", runId: "run", sessionId: "session" },
    data: { caseId: "strict-answer", outcome: "failed", case: { assertions: [
      { id: "answer", type: "final_text", equals: "core-current" }, { id: "end", type: "turn_end", reason: { kind: "completed" } },
    ] }, assertions: { outcome: "failed", results: [
      { id: "end", type: "turn_end", outcome: "passed", actual: { kind: "completed" }, evidence: { endSeq: 110 } },
      { id: "answer", type: "final_text", outcome: "failed", actual: "**core-current**", evidence: { answerSeq: 109 } },
    ] } } };
}

async function openDiagnostic(artifact, requests = []) {
  const get = await viewer([{ id: "runs:case/evaluation.json", kind: "evaluation", title: "diagnostic", path: "case" }], artifact, requests);
  get("navigation").children.find((item) => item.children[1].textContent === "逐次结果").trigger("click");
  findButton(get("catalog"), "diagnostic").trigger("click");
  await new Promise(setImmediate);
  return get;
}

function comparisonArtifact() {
  const identity = { id: "runs:trace/" + "a".repeat(64) + ".jsonl", runId: "run", sessionId: "session" };
  const rule = { id: "answer", type: "final_text", equals: "done" };
  const result = { id: "answer", type: "final_text", outcome: "failed", actual: "**Done.**", evidence: { answerSeq: 48 } };
  return { kind: "assertion_comparison", links: [], assertionTrace: identity, data: {
    assertionComparisonFormatVersion: 1, caseId: "rename", status: "compared", source: "live",
    baseline: { outcome: "failed", assertionOutcome: "failed", recordingOutcome: "complete", executionStatus: "completed", assertionsSha256: "old" },
    candidate: { outcome: "passed", assertionOutcome: "passed", recordingOutcome: "complete", executionStatus: "completed", assertionsSha256: "new" },
    summary: { taskOutcomeChanged: true, changedAssertionIds: ["answer"] },
    assertions: [{ id: "answer", ruleChanged: true, resultChanged: true, outcomeChanged: false, positionChanged: false,
      baseline: { position: 1, definition: rule, result },
      candidate: { position: 1, definition: { ...rule, role: "diagnostic" }, result: { ...result, role: "diagnostic" } } },
    { id: "end", ruleChanged: false, resultChanged: false, outcomeChanged: false, positionChanged: false,
      baseline: { position: 2, definition: { id: "end", type: "turn_end" }, result: { outcome: "passed" } },
      candidate: { position: 2, definition: { id: "end", type: "turn_end" }, result: { outcome: "passed" } } }],
  } };
}

async function openComparison(artifact = comparisonArtifact(), requests = []) {
  const get = await viewer([{ id: "runs:comparison/assertion-comparison.json", kind: "assertion_comparison",
    title: "改名对照", path: "comparison", outcome: "passed", baselineOutcome: "failed", candidateOutcome: "passed", sources: ["live"] }], artifact, requests);
  get("navigation").children.find((item) => item.children[1].textContent === "断言对照").trigger("click");
  assert.match(get("catalog").textContent, /未通过 → 通过/);
  findButton(get("catalog"), "改名对照").trigger("click");
  await new Promise(setImmediate);
  return get;
}

test("assertion comparisons preserve both verdicts, literal results and changed-only filtering", async () => {
  const get = await openComparison();
  assert.match(get("detail").textContent, /原任务结论 未通过/);
  assert.match(get("detail").textContent, /候选任务结论 通过/);
  const panel = section(get, "逐项规则与判定对照");
  assert.equal(descendants(panel, "article").length, 2);
  assert.match(panel.textContent, /必需项/);
  assert.match(panel.textContent, /诊断项/);
  assert.ok(panel.textContent.includes("**Done.**"));
  findButton(panel, "仅看变化").trigger("click");
  assert.equal(descendants(panel, "article").length, 1);
  assert.equal(descendants(panel, "h3")[0].textContent, "answer");
  findButton(panel, "显示全部断言").trigger("click");
  assert.equal(descendants(panel, "article").length, 2);
});

test("comparison filters include evidence-only changes, missing sides and unchanged comparisons", async () => {
  const artifact = comparisonArtifact();
  artifact.data.status = "inconclusive";
  artifact.data.candidate.outcome = "unevaluable";
  artifact.data.candidate.assertionReason = "missing trace";
  artifact.data.assertions = [
    { id: "evidence", resultChanged: true, ruleChanged: false, outcomeChanged: false, positionChanged: false,
      baseline: { position: 1, definition: { type: "tool_result" }, result: { outcome: "passed", evidence: { afterResultSeq: 1 } } },
      candidate: { position: 1, definition: { type: "tool_result" }, result: { outcome: "passed", evidence: { afterResultSeq: 2 } } } },
    { id: "added", ruleChanged: true, baseline: null, candidate: { position: 2, definition: { type: "final_text", match: "confirmation_token" }, result: { outcome: "not_run" } } },
    { id: "removed", ruleChanged: true, baseline: { position: 3, definition: { type: "final_text" }, result: { outcome: "failed" } }, candidate: null },
    { id: "moved", positionChanged: true, baseline: { position: 2 }, candidate: { position: 1 } },
  ];
  delete artifact.assertionTrace;
  const get = await openComparison(artifact), panel = section(get, "逐项规则与判定对照");
  assert.match(get("detail").textContent, /无法完成对照/);
  assert.match(get("detail").textContent, /missing trace/);
  findButton(panel, "仅看变化").trigger("click");
  assert.equal(descendants(panel, "article").length, 4);
  assert.match(panel.textContent, /此侧无该断言/);
  assert.match(panel.textContent, /confirmation_token/);
  assert.match(panel.textContent, /关联轨迹不可用/);
  assert.equal(descendants(panel, "button").length, 1);
  const same = comparisonArtifact();
  same.data.assertions.forEach((row) => { row.ruleChanged = row.resultChanged = row.outcomeChanged = row.positionChanged = false; });
  const unchanged = await openComparison(same), unchangedPanel = section(unchanged, "逐项规则与判定对照");
  findButton(unchangedPanel, "仅看变化").trigger("click");
  assert.match(unchangedPanel.textContent, /没有标记为变化的断言/);
});

test("comparison event jumps reuse the associated trace identity", async () => {
  const artifact = comparisonArtifact(), requests = [];
  const get = await openComparison((path) => path.includes("seq=") ? { kind: "trace", links: [], offset: 0, nextOffset: null,
    focus: { seq: 48, line: 1 }, rows: [{ line: 1, data: { event: { seq: 48, type: "assistant/message" } } }] } : artifact, requests);
  findButton(section(get, "逐项规则与判定对照"), "最终答案 · seq 48").trigger("click");
  await new Promise(setImmediate);
  const query = new URLSearchParams(requests.at(-1).split("?")[1]);
  assert.equal(query.get("seq"), "48");
  assert.equal(query.get("runId"), "run");
  assert.equal(query.get("sessionId"), "session");
  assert.match(get("detail").textContent, /已定位 seq 48/);
});

function previewArtifact() {
  const change = comparisonArtifact().data.assertions[0];
  return { kind: "experiment_assertion_preview", links: [], sampleEvidence: [{ index: 1, id: "runs:one/evidence.json",
    assertionTrace: comparisonArtifact().assertionTrace }], data: {
    experimentAssertionPreviewFormatVersion: 1, experimentId: "four-samples", modelCalled: false, status: "inconclusive",
    summary: { plannedSamples: 5, comparedSamples: 4, passToFail: 1, failToPass: 1, unchangedPassed: 1, unchangedFailed: 1, inconclusive: 1 },
    samples: [{ sampleId: "bold-answer", caseEntryId: "rename", configurationId: "fixture", repeatIndex: 1, source: "synthetic",
      baselineOutcome: "passed", candidateOutcome: "failed", transition: "passToFail", verification: "verified", configurationMatch: "matched",
      changedAssertionIds: ["answer"], changes: [change], reasons: [] },
    { sampleId: "missing", baselineOutcome: null, candidateOutcome: null, transition: "inconclusive", reasons: ["<img src=x onerror=bad()>"], changes: [] }],
  } };
}

async function openPreview(artifact = previewArtifact(), requests = []) {
  const get = await viewer([{ id: "runs:preview/experiment-assertion-preview.json", kind: "experiment_assertion_preview",
    title: "四样本预览", path: "preview", sources: ["synthetic"], previewSummary: previewArtifact().data.summary }], artifact, requests);
  get("navigation").children.find((item) => item.children[1].textContent === "实验规则预览").trigger("click");
  assert.match(get("catalog").textContent, /可对照 4 \/ 5/);
  findButton(get("catalog"), "四样本预览").trigger("click");
  await new Promise(setImmediate);
  return get;
}

test("experiment rule previews show their denominator, all transitions and literal sample changes", async () => {
  const get = await openPreview(), detail = get("detail");
  assert.match(detail.textContent, /原计划样本 5/);
  assert.match(detail.textContent, /可对照样本 4/);
  assert.match(detail.textContent, /无法对照样本 1/);
  assert.match(detail.textContent, /通过 → 未通过/);
  assert.match(detail.textContent, /未通过 → 通过/);
  assert.match(detail.textContent, /仍通过/);
  assert.match(detail.textContent, /仍未通过/);
  const panel = section(get, "样本结论与变化断言");
  assert.equal(descendants(panel, "article").length, 2);
  assert.ok(literalText(panel).includes("**Done.**"));
  assert.ok(literalText(panel).includes("<img src=x onerror=bad()>"));
  assert.equal(descendants(panel, "img").length, 0);
  assert.match(panel.textContent, /源证据缺失、身份不匹配或超出浏览目录/);
  assert.match(detail.textContent, /模型调用 否/);
});

test("preview source evidence and event jumps use backend-approved sample associations", async () => {
  for (const action of ["查看源证据", "最终答案 · seq 48"]) {
    const artifact = previewArtifact(), requests = [];
    const get = await openPreview((path) => path.includes("id=runs%3Apreview") ? artifact
      : { kind: "evidence", links: [], data: { evidenceFormatVersion: 2 } }, requests);
    findButton(section(get, "样本结论与变化断言"), action).trigger("click");
    await new Promise(setImmediate);
    const query = new URLSearchParams(requests.at(-1).split("?")[1]);
    if (action === "查看源证据") assert.equal(query.get("id"), "runs:one/evidence.json");
    else {
      assert.equal(query.get("id"), artifact.sampleEvidence[0].assertionTrace.id);
      assert.equal(query.get("seq"), "48");
      assert.equal(query.get("runId"), "run");
      assert.equal(query.get("sessionId"), "session");
    }
  }
  const artifact = previewArtifact();
  artifact.sampleEvidence = [];
  const get = await openPreview(artifact);
  assert.equal(findButton(section(get, "样本结论与变化断言"), "查看源证据"), null);
  assert.equal(findButton(section(get, "样本结论与变化断言"), "最终答案 · seq 48"), null);
});

test("workflow index preserves scenario order and opens allowed result links", async () => {
  const requests = [], artifact = { kind: "workflow_demo", links: [
    { label: "场景 1 / evaluationPath", id: "runs:complete/evaluation.json" },
    { label: "场景 3 / previewPath", id: "runs:preview/experiment-assertion-preview.json" }], data: {
    workflowDemoFormatVersion: 1, workflowName: "可重复合成工作流演示", source: "synthetic", modelCalled: false, status: "completed", scenarios: [
      { id: "complete", title: "完整步骤", outcome: "passed", description: "先读回再重试" },
      { id: "skip-readbacks", title: "漏步", outcome: "unevaluable", description: "缺少前置证据" },
      { id: "rule-impact", title: "规则影响", outcome: "compared", description: "四个样本" }],
  } };
  const get = await viewer([{ id: "runs:demo/workflow-index.json", kind: "workflow_demo", title: "工作流", path: "demo" }], artifact, requests);
  get("navigation").children.find((item) => item.children[1].textContent === "工作流演示").trigger("click");
  findButton(get("catalog"), "工作流").trigger("click");
  await new Promise(setImmediate);
  const panel = section(get, "按顺序浏览三个场景"), text = panel.textContent;
  assert.equal(get("title").textContent, "可重复合成工作流演示");
  assert.match(text, /任务 \/ 对照结论/);
  assert.ok(text.indexOf("完整步骤") < text.indexOf("漏步"));
  assert.ok(text.indexOf("漏步") < text.indexOf("规则影响"));
  assert.match(text, /结果缺失或超出浏览目录/);
  assert.equal(findButton(panel, "漏步"), null);
  findButton(panel, "规则影响").trigger("click");
  await new Promise(setImmediate);
  assert.equal(new URLSearchParams(requests.at(-1).split("?")[1]).get("id"), "runs:preview/experiment-assertion-preview.json");
});

test("assertion cards prioritize saved failures, compare frozen expectations and preserve the raw verdict", async () => {
  const get = await openDiagnostic(diagnosticResult());
  const panel = section(get, "断言诊断 · 失败优先"), cards = descendants(panel, "article");
  assert.match(cards[0].textContent, /^answer 未通过/);
  assert.match(cards[1].textContent, /^end 通过/);
  assert.doesNotMatch(panel.textContent, /诊断项|必需项/);
  assert.match(cards[0].textContent, /core-current/);
  assert.match(cards[0].textContent, /\*\*core-current\*\*/);
  assert.equal(descendants(cards[0], "mark").find((item) => item.className === "actual-difference").textContent, "**core-current**");
  assert.ok(findButton(cards[0], "最终答案 · seq 109"));
  assert.ok(descendants(get("detail"), "h2").some((item) => item.textContent === "断言明细"));
});

test("synthetic evaluation metrics label generated model events without claiming real model calls", async () => {
  for (const source of ["synthetic", "live"]) {
    const artifact = diagnosticResult();
    artifact.data.source = source;
    artifact.data.metrics = { modelCalls: 1, toolCalls: 8 };
    const get = await openDiagnostic(artifact), panel = section(get, "观测指标");
    if (source === "synthetic") {
      assert.match(panel.textContent, /合成模型事件 1/);
      assert.match(panel.textContent, /合成事件计数不代表真实模型调用。/);
      assert.doesNotMatch(panel.textContent, /已结算模型调用/);
    } else {
      assert.match(panel.textContent, /已结算模型调用 1/);
      assert.doesNotMatch(panel.textContent, /合成模型事件|合成事件计数/);
    }
    assert.equal(artifact.data.metrics.modelCalls, 1);
  }
});

function dependencyResult() {
  const artifact = diagnosticResult();
  const toolIds = ["timeout", "source-still-present", "target-still-missing", "retry", "verify"];
  const rows = toolIds.map((id, index) => ({ id, type: "tool_result", outcome: index ? "insufficient_evidence" : "passed",
    ...(index ? { reason: "Saved missing evidence; this prose does not define dependencies." } : { evidence: { callSeq: 2, resultSeq: 3 } }) }));
  rows.push(...[["moves", "tool_call_count"], ["state", "environment_files"], ["answer", "final_text"],
    ["answer-exact", "final_text"], ["end", "turn_end"]].map(([id, type]) => ({ id, type, outcome: "passed",
      ...(id === "answer-exact" ? { role: "diagnostic" } : {}) })));
  artifact.data.outcome = "unevaluable";
  artifact.data.assertions = { outcome: "insufficient_evidence", results: rows };
  artifact.data.case.assertions = rows.map(({ id, type, role }) => ({ id, type, ...(role ? { role } : {}) }));
  artifact.data.assertionDiagnostics = { assertionDiagnosticsFormatVersion: 1, results: rows.map((row, index) => ({
    id: row.id, type: row.type, outcome: row.outcome,
    reasonCode: index === 1 ? "tool_evidence_missing" : index > 1 && index < 5 ? "dependency_not_passed" : "matched",
    ...(index > 0 && index < 5 ? { after: toolIds[index - 1] } : {}),
    ...(index > 1 && index < 5 ? { blockedBy: [toolIds[index - 1]], observedMatches: index === 3 ? [{ callId: "retry", callSeq: 4, resultSeq: 5, answerSeq: 8 }]
      : index === 4 ? [{ callId: "verify", callSeq: 6, resultSeq: 7, answerSeq: 8 }] : [] } : {}),
  })) };
  return artifact;
}

test("structured diagnostics identify the first missing step and three directly blocked successors", async () => {
  const artifact = dependencyResult(), before = JSON.stringify(artifact.data);
  const get = await openDiagnostic(artifact), panel = section(get, "断言原因与依赖");
  assert.match(panel.textContent, /首个缺证步骤 · source-still-present/);
  const roots = descendants(panel, "p").find((item) => item.textContent.startsWith("独立问题源头"));
  assert.equal(roots.textContent, "独立问题源头（按保存的断言顺序） · source-still-present（必需项）");
  const rows = descendants(panel, "tbody")[0].children;
  assert.equal(rows.length, 10);
  for (const [id, after] of [["target-still-missing", "source-still-present"], ["retry", "target-still-missing"], ["verify", "retry"]]) {
    const row = rows.find((item) => item.children[0].textContent.startsWith(id + " "));
    assert.equal(row.children[3].textContent, after);
    assert.equal(row.children[4].textContent, after);
    assert.match(row.children[2].textContent, /dependency_not_passed/);
  }
  assert.match(panel.textContent, /这些事件未计为本项通过证据/);
  assert.ok(findButton(panel, "工具返回 · seq 5"));
  assert.ok(findButton(panel, "工具返回 · seq 7"));
  const cards = descendants(section(get, "断言诊断 · 失败优先"), "article");
  assert.match(cards.find((card) => card.textContent.startsWith("source-still-present ")).textContent, /首个缺证步骤/);
  assert.equal(artifact.data.assertions.results.filter((row) => row.outcome === "passed").length, 6);
  assert.equal(artifact.data.assertions.results.filter((row) => row.outcome === "insufficient_evidence").length, 4);
  assert.equal(JSON.stringify(artifact.data), before);
});

test("diagnostics preserve independent roots and mark diagnostic failures without changing task verdict", async () => {
  const artifact = dependencyResult();
  for (const result of artifact.data.assertions.results) {
    if (["state", "answer-exact"].includes(result.id)) result.outcome = "failed";
  }
  for (const result of artifact.data.assertionDiagnostics.results) {
    if (result.id === "state") Object.assign(result, { outcome: "failed", reasonCode: "environment_files_mismatch" });
    if (result.id === "answer-exact") Object.assign(result, { outcome: "failed", reasonCode: "final_text_mismatch" });
  }
  const get = await openDiagnostic(artifact), panel = section(get, "断言原因与依赖");
  const roots = descendants(panel, "p").find((item) => item.textContent.startsWith("独立问题源头"));
  assert.match(roots.textContent, /source-still-present（必需项）.*state（必需项）.*answer-exact（诊断项）/);
  assert.match(panel.textContent, /诊断失败不会单独使任务失败/);
  assert.equal(artifact.data.outcome, "unevaluable");
});

test("reordered diagnostic metadata keeps the saved assertion order and first missing root", async () => {
  const artifact = dependencyResult();
  const extra = { id: "another-missing", type: "tool_result", outcome: "insufficient_evidence" };
  artifact.data.assertions.results.push({ ...extra });
  artifact.data.case.assertions.push({ id: extra.id, type: extra.type });
  artifact.data.assertionDiagnostics.results.push({ ...extra, reasonCode: "tool_evidence_missing" });
  artifact.data.assertionDiagnostics.results.reverse();
  const before = JSON.stringify(artifact.data);
  const get = await openDiagnostic(artifact), panel = section(get, "断言原因与依赖");
  const roots = descendants(panel, "p").find((item) => item.textContent.startsWith("独立问题源头"));
  assert.equal(roots.textContent, "独立问题源头（按保存的断言顺序） · source-still-present（必需项）、another-missing（必需项）");
  assert.match(panel.textContent, /首个缺证步骤 · source-still-present/);
  assert.doesNotMatch(panel.textContent, /首个缺证步骤 · another-missing/);
  const rows = descendants(panel, "tbody")[0].children;
  assert.deepEqual(rows.map((row) => descendants(row.children[0], "span")[0].textContent),
    artifact.data.assertions.results.map((row) => row.id));
  assert.equal(JSON.stringify(artifact.data), before);
});

test("a failed predecessor remains the root instead of treating its blocked successor as missing", async () => {
  const artifact = dependencyResult();
  artifact.data.outcome = artifact.data.assertions.outcome = "failed";
  artifact.data.assertions.results.slice(0, 5).forEach((row) => { row.outcome = "failed"; });
  artifact.data.assertionDiagnostics.results.slice(0, 5).forEach((row) => { row.outcome = "failed"; });
  Object.assign(artifact.data.assertionDiagnostics.results[0], { reasonCode: "tool_result_mismatch" });
  Object.assign(artifact.data.assertionDiagnostics.results[1], { reasonCode: "dependency_not_passed", blockedBy: ["timeout"],
    observedMatches: [{ callId: "source-read", callSeq: 60, resultSeq: 61, answerSeq: 70 }] });
  const before = JSON.stringify(artifact.data);
  const get = await openDiagnostic(artifact), panel = section(get, "断言原因与依赖");
  assert.match(panel.textContent, /独立问题源头（按保存的断言顺序） · timeout（必需项）/);
  assert.doesNotMatch(panel.textContent, /首个缺证步骤/);
  assert.doesNotMatch(panel.textContent, /依赖关系不可用|依赖结构存在/);
  assert.match(panel.textContent, /工具返回不符（tool_result_mismatch）/);
  assert.match(panel.textContent, /前置断言未通过，这些事件未计为本项通过证据/);
  assert.ok(findButton(panel, "工具返回 · seq 61"));
  assert.ok(findButton(panel, "工具返回 · seq 5"));
  assert.equal(artifact.data.assertions.results[1].outcome, "failed");
  assert.equal(JSON.stringify(artifact.data), before);
});

test("complete structured diagnostics show the passed chain and its scored event evidence", async () => {
  const artifact = dependencyResult();
  artifact.data.outcome = artifact.data.assertions.outcome = "passed";
  artifact.data.assertions.results.forEach((row, index) => { row.outcome = "passed"; row.evidence = { callSeq: index * 2 + 2, resultSeq: index * 2 + 3 }; });
  artifact.data.assertionDiagnostics.results.forEach((row) => {
    row.outcome = "passed"; row.reasonCode = "matched"; delete row.blockedBy; delete row.observedMatches;
  });
  const get = await openDiagnostic(artifact), panel = section(get, "断言原因与依赖");
  assert.match(panel.textContent, /独立问题源头（按保存的断言顺序） · 无/);
  assert.doesNotMatch(panel.textContent, /未计为本项通过证据|首个缺证步骤/);
  assert.equal(descendants(panel, "tbody")[0].children.length, 10);
  assert.ok(findButton(panel, "工具返回 · seq 11"));
  assert.match(panel.textContent, /匹配通过（matched）/);
});

test("legacy, unsupported and unmatched structured diagnostics do not infer relations from reason prose", async () => {
  for (const mode of ["legacy", "unsupported", "mismatched", "duplicate"]) {
    const artifact = dependencyResult();
    artifact.data.assertions.results[1].reason = "dependency_not_passed blockedBy timeout <script>bad()</script>";
    if (mode === "legacy") delete artifact.data.assertionDiagnostics;
    else if (mode === "unsupported") artifact.data.assertionDiagnostics.assertionDiagnosticsFormatVersion = 2;
    else if (mode === "mismatched") artifact.data.assertionDiagnostics.results.forEach((row) => { row.outcome = "failed"; });
    else artifact.data.assertionDiagnostics.results.push(...artifact.data.assertionDiagnostics.results.map((row) => ({ ...row })));
    const get = await openDiagnostic(artifact), panel = section(get, "断言原因与依赖");
    assert.doesNotMatch(panel.textContent, /首个缺证步骤|source-still-present（必需项）/);
    assert.match(panel.textContent, mode === "legacy" ? /未保存结构化断言诊断/ : mode === "unsupported" ? /版本不支持/ : /无法唯一关联/);
    assert.ok(literalText(section(get, "断言诊断 · 失败优先")).includes("<script>bad()</script>"));
    assert.equal(descendants(get("detail"), "script").length, 0);
  }
});

test("invalid dependency references and cycles remain unavailable while independent roots stay visible", async () => {
  for (const mode of ["unknown", "cycle", "non-direct"]) {
    const artifact = dependencyResult(), rows = artifact.data.assertionDiagnostics.results;
    if (mode === "unknown") rows.find((row) => row.id === "retry").after = "missing-id";
    if (mode === "cycle") rows.find((row) => row.id === "retry").after = "verify";
    if (mode === "non-direct") rows.find((row) => row.id === "retry").blockedBy = ["timeout"];
    const get = await openDiagnostic(artifact), panel = section(get, "断言原因与依赖");
    assert.match(panel.textContent, /依赖结构存在缺失引用、环、非直接阻断/);
    assert.match(panel.textContent, /依赖关系不可用/);
    assert.match(panel.textContent, /source-still-present（必需项）/);
    if (mode === "non-direct") {
      const rows = descendants(panel, "tbody")[0].children;
      assert.match(rows.find((row) => row.children[0].textContent.startsWith("verify ")).textContent, /依赖关系不可用/);
    }
  }
});

test("contradictory blockers do not claim passed prerequisites failed or trust unscored observed matches", async () => {
  for (const mode of ["passed-predecessor", "wrong-reason", "missing-blocker", "blocked-passed-row"]) {
    const artifact = dependencyResult(), metadata = artifact.data.assertionDiagnostics.results;
    const source = metadata.find((row) => row.id === "source-still-present");
    Object.assign(source, { reasonCode: "dependency_not_passed", blockedBy: ["timeout"],
      observedMatches: [{ callId: "observed", callSeq: 60, resultSeq: 61, answerSeq: 70 }] });
    if (mode === "wrong-reason") source.reasonCode = "tool_evidence_missing";
    if (mode === "missing-blocker") delete source.blockedBy;
    if (mode === "blocked-passed-row") {
      source.outcome = "passed";
      artifact.data.assertions.results.find((row) => row.id === source.id).outcome = "passed";
    }
    const get = await openDiagnostic(artifact), panel = section(get, "断言原因与依赖");
    const row = descendants(panel, "tbody")[0].children.find((item) => item.children[0].textContent.startsWith("source-still-present "));
    assert.match(row.textContent, /依赖关系不可用/);
    assert.doesNotMatch(row.textContent, /前置断言未通过，这些事件未计为本项通过证据/);
    assert.equal(findButton(row, "工具返回 · seq 61"), null);
    assert.doesNotMatch(panel.textContent, /首个缺证步骤 · source-still-present/);
    const card = descendants(section(get, "断言诊断 · 失败优先"), "article").find((item) => item.textContent.startsWith("source-still-present "));
    assert.equal(findButton(card, "工具返回 · seq 61"), null);
    if (source.blockedBy) assert.match(card.textContent, /保存的阻断字段（关系不可用）/);
  }
});

test("global evaluation gates preserve unscored reasons without inventing independent missing steps", async () => {
  for (const reasonCode of ["evaluation_evidence_invalid", "recording_not_complete", "execution_not_completed"]) {
    const artifact = dependencyResult(), outcome = reasonCode === "evaluation_evidence_invalid" ? "insufficient_evidence" : "not_run";
    artifact.data.assertions.results.forEach((row) => { row.outcome = outcome; delete row.evidence; });
    artifact.data.assertionDiagnostics.results.forEach((row) => {
      row.outcome = outcome; row.reasonCode = reasonCode; delete row.blockedBy; delete row.observedMatches;
    });
    const before = JSON.stringify(artifact.data);
    const get = await openDiagnostic(artifact), panel = section(get, "断言原因与依赖");
    assert.match(panel.textContent, /全局门禁未通过，相关断言未执行逐项评分/);
    assert.match(panel.textContent, /独立问题源头（按保存的断言顺序） · 无/);
    assert.doesNotMatch(panel.textContent, /首个缺证步骤/);
    assert.ok(panel.textContent.includes(reasonCode));
    assert.equal(descendants(panel, "tbody")[0].children.length, 10);
    assert.equal(JSON.stringify(artifact.data), before);
  }
});

test("partial diagnostics and unknown reason codes never fabricate missing roots or complete coverage", async () => {
  for (const mode of ["partial", "unknown"]) {
    const artifact = dependencyResult();
    if (mode === "partial") artifact.data.assertionDiagnostics.results = artifact.data.assertionDiagnostics.results.slice(0, 1);
    else artifact.data.assertionDiagnostics.results.find((row) => row.id === "source-still-present").reasonCode = "__proto__";
    const get = await openDiagnostic(artifact), panel = section(get, "断言原因与依赖");
    assert.match(panel.textContent, /独立问题源头（按保存的断言顺序） · 无/);
    assert.doesNotMatch(panel.textContent, /首个缺证步骤/);
    if (mode === "partial") {
      assert.match(panel.textContent, /结构化诊断不完整/);
      assert.equal(descendants(panel, "tbody")[0].children.length, 1);
    } else {
      assert.match(panel.textContent, /未知原因码只显示保存原值/);
      assert.match(panel.textContent, /未识别的原因码（__proto__）/);
    }
  }
});

test("observed blocked retry events keep the current trace identity and never replace saved scores", async () => {
  const artifact = dependencyResult(), requests = [];
  const get = await openDiagnostic((path) => path.includes("seq=") ? { kind: "trace", links: [], offset: 0, nextOffset: null,
    focus: { seq: 5, line: 1 }, rows: [{ line: 1, data: { event: { seq: 5, type: "tool/result" } } }] } : artifact, requests);
  findButton(section(get, "断言原因与依赖"), "工具返回 · seq 5").trigger("click");
  await new Promise(setImmediate);
  const query = new URLSearchParams(requests.at(-1).split("?")[1]);
  assert.equal(query.get("id"), artifact.assertionTrace.id);
  assert.equal(query.get("seq"), "5");
  assert.equal(query.get("runId"), "run");
  assert.equal(query.get("sessionId"), "session");
  assert.equal(artifact.data.assertions.results.find((row) => row.id === "retry").outcome, "insufficient_evidence");
  assert.equal(artifact.data.outcome, "unevaluable");
});

test("diagnostic assertion outcomes stay visible alongside the saved aggregate", async () => {
  for (const [rowOutcome, savedVerdict, rowLabel, verdictLabel] of [
    ["failed", "passed", "未通过", "通过"],
    ["insufficient_evidence", "unevaluable", "证据不足", "无法评测"],
  ]) {
    const artifact = diagnosticResult();
    artifact.data.case.assertions[0].role = "diagnostic";
    artifact.data.assertions.results[1].role = "diagnostic";
    artifact.data.assertions.results[1].outcome = rowOutcome;
    if (savedVerdict === "unevaluable") artifact.data.assertions.results[0].outcome = "insufficient_evidence";
    artifact.data.assertions.outcome = savedVerdict === "unevaluable" ? "insufficient_evidence" : "passed";
    artifact.data.outcome = savedVerdict;
    const get = await openDiagnostic(artifact), panel = section(get, "断言诊断 · 失败优先");
    assert.match(panel.textContent, /断言汇总只计入必需项/);
    const cards = descendants(panel, "article");
    const answer = cards.find((card) => descendants(card, "h3")[0].textContent === "answer");
    assert.ok(answer.textContent.includes(rowLabel));
    assert.match(answer.textContent, /诊断项/);
    assert.match(cards.find((card) => card !== answer).textContent, /必需项/);
    const summary = descendants(get("detail"), "div").filter((item) => item.className === "card");
    assert.equal(summary.find((item) => item.children[0].textContent === "任务结论").children[1].textContent, verdictLabel);
    assert.equal(summary.find((item) => item.children[0].textContent === "断言汇总").children[1].textContent,
      savedVerdict === "unevaluable" ? "证据不足" : "通过");
  }
});

test("confirmation token cards show the saved rule, literal texts and verdict without exact-match highlights", async () => {
  for (const [outcome, actual, label] of [
    ["passed", "**Done.**", "通过"], ["failed", "done after retry", "未通过"], ["not_run", undefined, "未执行"],
  ]) {
    const artifact = diagnosticResult(), row = artifact.data.assertions.results[1];
    Object.assign(artifact.data.case.assertions[0], { equals: "done", match: "confirmation_token" });
    Object.assign(row, { outcome, match: "confirmation_token" });
    if (actual === undefined) { delete row.actual; delete row.evidence; }
    else row.actual = actual;
    const get = await openDiagnostic(artifact);
    const card = descendants(section(get, "断言诊断 · 失败优先"), "article").find((item) => descendants(item, "h3")[0].textContent === "answer");
    assert.match(card.textContent, /确认词匹配/);
    assert.ok(card.textContent.startsWith("answer " + label));
    assert.equal(descendants(card, "mark").length, 0);
    if (actual === undefined) {
      assert.match(card.textContent, /未保存实际值/);
    } else {
      const values = descendants(card, "pre");
      assert.equal(literalText(values[0]), "done");
      assert.equal(literalText(values[1]), actual);
    }
  }
});

test("environment state cards show exact saved expected and actual files", async () => {
  const artifact = diagnosticResult();
  artifact.data.case.assertions = [{ id: "state", type: "environment_files", equals: { "result.txt": "done\n", "guard.txt": "keep" } }];
  artifact.data.assertions.results = [{ id: "state", type: "environment_files", outcome: "failed",
    actual: { "result.txt": "done\n", "guard.txt": "changed" }, evidence: { environmentSnapshotSha256: "a".repeat(64) } }];
  const get = await openDiagnostic(artifact);
  const cards = descendants(section(get, "断言诊断 · 失败优先"), "article");
  assert.match(cards[0].textContent, /keep/);
  assert.match(cards[0].textContent, /changed/);
  assert.match(cards[0].textContent, /guard.txt/);
  assert.equal(descendants(cards[0], "button").length, 0);
});

test("text differences preserve empty strings, unicode, whitespace and text-only HTML", async () => {
  for (const [expected, actual] of [["", " "], ["甲🙂乙", "甲🙃乙"], ["a\nb", "a b"], ["<img src=x>", "<script>alert(1)</script>"], ["same", "same"]]) {
    const artifact = diagnosticResult();
    artifact.data.case.assertions[0].equals = expected;
    artifact.data.assertions.results[1].actual = actual;
    const get = await openDiagnostic(artifact), card = descendants(section(get, "断言诊断 · 失败优先"), "article")[0];
    const values = descendants(card, "pre");
    assert.equal(literalText(values[0]), expected);
    assert.equal(literalText(values[1]), actual);
    assert.match(values[2].textContent, /"expected":/);
    assert.equal(descendants(card, "script").length, 0);
    assert.equal(descendants(card, "img").length, 0);
    assert.match(card.textContent, /未通过/);
    if (expected === actual) assert.match(card.textContent, /保存文本相同；原结论保持不变/);
  }
});

test("missing snapshots, duplicate IDs and unexecuted assertions do not invent expectations or evidence", async () => {
  for (const mode of ["missing", "duplicate", "wrong-type"]) {
    const artifact = diagnosticResult();
    if (mode === "missing") delete artifact.data.case;
    if (mode === "duplicate") artifact.data.case.assertions.push({ ...artifact.data.case.assertions[0] });
    if (mode === "wrong-type") artifact.data.case.assertions[0].type = "tool_result";
    delete artifact.assertionTrace;
    artifact.data.assertions.results[1] = { id: "answer", type: "final_text", outcome: "not_run" };
    const get = await openDiagnostic(artifact), panel = section(get, "断言诊断 · 失败优先");
    assert.match(panel.textContent, /期望值缺失或无法唯一匹配/);
    assert.match(panel.textContent, /未保存实际值/);
    assert.match(panel.textContent, /未保存可定位的事件序号/);
    assert.match(panel.textContent, /关联轨迹不可用/);
    assert.equal(descendants(panel, "button").length, 0);
  }
  const get = await openDiagnostic({ kind: "evaluation", links: [], data: { assertions: { reason: "Evidence unavailable" } } });
  assert.match(section(get, "断言诊断 · 失败优先").textContent, /没有保存逐条断言结果/);
  assert.match(section(get, "断言诊断 · 失败优先").textContent, /Evidence unavailable/);
});

test("tool mismatch cards retain expected predicates and all distinct saved evidence locations", async () => {
  const artifact = diagnosticResult();
  artifact.data.case.assertions = [{ id: "tool", type: "tool_result", tool: "eval_read", arguments: { path: "value.txt" },
    result: { isError: false, textEquals: "" }, after: "earlier" }];
  artifact.data.assertions.results = [{ id: "tool", type: "tool_result", outcome: "failed", reason: "Wrong content or order",
    evidence: [{ callSeq: 100, resultSeq: 101, afterResultSeq: 99, answerSeq: 109 },
      { callSeq: 103, resultSeq: 104, answerSeq: 109 }, { callSeq: -1, resultSeq: true, answerSeq: "109", endSeq: 1.5 }] }];
  const get = await openDiagnostic(artifact), panel = section(get, "断言诊断 · 失败优先");
  assert.match(panel.textContent, /"textEquals": ""/);
  assert.match(panel.textContent, /"after": "earlier"/);
  assert.match(panel.textContent, /未保存实际值/);
  assert.equal(descendants(panel, "button").length, 6);
  assert.ok(findButton(panel, "工具调用 · seq 103"));
  assert.ok(findButton(panel, "前置工具返回 · seq 99"));
});

test("evidence jumps request event identity, highlight the returned line and return to diagnosis", async () => {
  const artifact = diagnosticResult(), requests = [];
  const get = await openDiagnostic((path) => path.includes("seq=") ? { kind: "trace", links: [], offset: 50, nextOffset: 100,
    focus: { seq: 109, line: 56 }, rows: [{ line: 56, data: { event: { seq: 109, type: "assistant/message" } } }] } : artifact, requests);
  findButton(section(get, "断言诊断 · 失败优先"), "最终答案 · seq 109").trigger("click");
  await new Promise(setImmediate);
  const query = new URLSearchParams(requests.at(-1).split("?")[1]);
  assert.equal(query.get("seq"), "109");
  assert.equal(query.get("runId"), "run");
  assert.equal(query.get("sessionId"), "session");
  assert.equal(query.get("id"), artifact.assertionTrace.id);
  assert.match(get("detail").textContent, /seq 109 · 文件第 56 行/);
  const rows = descendants(section(get, "原始事件轨迹"), "tr");
  assert.equal(rows[1].className, "focused-event");
  get("back").trigger("click");
  await new Promise(setImmediate);
  assert.ok(section(get, "断言诊断 · 失败优先"));
  assert.ok(requests.every((path) => path.startsWith("/api/catalog") || path.startsWith("/api/document?")));
});

test("failed event lookup leaves the diagnostic page available", async () => {
  const artifact = diagnosticResult();
  const get = await openDiagnostic((path) => { if (path.includes("seq=")) throw new Error("Event locator is missing"); return artifact; });
  findButton(section(get, "断言诊断 · 失败优先"), "最终答案 · seq 109").trigger("click");
  await new Promise(setImmediate);
  assert.ok(section(get, "断言诊断 · 失败优先"));
  assert.match(get("message").textContent, /Event locator is missing/);
});

test("behavior cards show frozen selectors, inclusive bounds, observed counts and violating calls", async () => {
  const artifact = diagnosticResult();
  artifact.data.case.assertions = [
    { id: "forbidden", type: "tool_forbidden", tool: "read", arguments: { path: "restricted.md" } },
    { id: "count", type: "tool_call_count", tool: "read", min: 0, max: 1 },
  ];
  artifact.data.assertions.results = [
    { id: "forbidden", type: "tool_forbidden", outcome: "failed", actual: 1, evidence: [{ callId: "bad", callSeq: 7 }] },
    { id: "count", type: "tool_call_count", outcome: "failed", actual: 2, evidence: [{ callSeq: 2, resultSeq: 3 }, { callSeq: 7 }] },
  ];
  const get = await openDiagnostic(artifact), cards = descendants(section(get, "断言诊断 · 失败优先"), "article");
  const forbidden = descendants(cards[0], "pre"), count = descendants(cards[1], "pre");
  assert.deepEqual(JSON.parse(forbidden[0].textContent), { tool: "read", arguments: { path: "restricted.md" }, max: 0 });
  assert.equal(forbidden[1].textContent, "1");
  assert.deepEqual(JSON.parse(count[0].textContent), { tool: "read", arguments: {}, min: 0, max: 1 });
  assert.equal(count[1].textContent, "2");
  assert.ok(findButton(cards[0], "工具调用 · seq 7"));
  assert.ok(findButton(cards[1], "工具返回 · seq 3"));
  assert.match(cards[1].textContent, /包括失败、未返回及最终答案后的调用/);
});

test("behavior cards distinguish a saved zero count from unexecuted or missing results", async () => {
  for (const actual of [0, undefined]) {
    const artifact = diagnosticResult();
    artifact.data.case.assertions = [{ id: "count", type: "tool_call_count", tool: "write", max: 0 }];
    artifact.data.assertions.results = [{ id: "count", type: "tool_call_count", outcome: actual === 0 ? "passed" : "not_run",
      ...(actual === 0 ? { actual, evidence: [] } : {}) }];
    const get = await openDiagnostic(artifact), panel = section(get, "断言诊断 · 失败优先");
    assert.equal(descendants(panel, "button").length, 0);
    if (actual === 0) assert.match(panel.textContent, /匹配调用为 0，没有对应调用事件/);
    else {
      assert.match(panel.textContent, /未保存实际值/);
      assert.doesNotMatch(panel.textContent, /匹配调用为 0/);
    }
    const expected = JSON.parse(descendants(panel, "pre")[0].textContent);
    assert.equal(expected.max, 0);
    assert.ok(!Object.hasOwn(expected, "min"));
  }
});

test("repeat distributions keep case configuration source and unavailable coverage visible", async () => {
  const artifact = resumedReport();
  artifact.data.executionOrder = { order: "seeded-sha256-v1", randomSeed: 0 };
  artifact.data.repeatDistributions = [
    { caseEntryId: "case-a", configurationId: "baseline", source: "synthetic", plannedRepetitions: 3, sourceSamples: 2,
      outcomes: { passed: 1, failed: 1, unevaluable: 0, missing: 0 }, eligiblePassed: 1, eligibleFailed: 1, excludedSamples: 0,
      samples: [{ repeatIndex: 1, status: "finished", outcome: "passed", verification: "verified", configurationMatch: "matched" },
        { repeatIndex: 2, status: "finished", outcome: "failed", verification: "verified", configurationMatch: "matched" }] },
    { caseEntryId: "case-a", configurationId: "baseline", source: "unknown", plannedRepetitions: 3, sourceSamples: 1,
      outcomes: { passed: 0, failed: 0, unevaluable: 0, missing: 1 }, eligiblePassed: 0, eligibleFailed: 0, excludedSamples: 1,
      samples: [{ repeatIndex: 3, status: "skipped", outcome: null, verification: "skipped", configurationMatch: "unknown" }] },
  ];
  const get = await openReport(artifact);
  const rows = panelRows(get, "按用例查看重复结果分布");
  assert.deepEqual(rows["case-a / baseline / 合成声明"].slice(0, 4), ["2 / 3", "1 / 1 / 0 / 0", "1 / 1", "0"]);
  assert.deepEqual(rows["case-a / baseline / 未知"].slice(0, 4), ["1 / 3", "0 / 0 / 0 / 1", "0 / 0", "1"]);
  assert.match(section(get, "按用例查看重复结果分布").textContent, /第 2 轮：未通过/);
  assert.match(section(get, "按用例查看重复结果分布").textContent, /第 3 轮：缺失 · 已跳过/);
  assert.deepEqual(panelRows(get, "执行顺序")["seeded-sha256-v1"], ["0"]);
});

test("execution seeds retain exact integers and legacy reports do not invent distributions", async () => {
  const artifact = resumedReport();
  artifact.data.executionOrder = { order: "seeded-sha256-v1", randomSeed: 9007199254740991 };
  const get = await openReport(artifact);
  assert.deepEqual(panelRows(get, "执行顺序")["seeded-sha256-v1"], ["9007199254740991"]);
  assert.equal(section(get, "按用例查看重复结果分布"), undefined);
  const legacy = await openReport(resumedReport());
  assert.equal(section(legacy, "执行顺序"), undefined);
  assert.equal(section(legacy, "按用例查看重复结果分布"), undefined);
  artifact.data.executionOrder = { order: "seeded-sha256-v1" };
  const missing = await openReport(artifact);
  assert.deepEqual(panelRows(missing, "执行顺序")["seeded-sha256-v1"], ["缺失"]);
  artifact.data.executionOrder = { order: "repeat-case-configuration" };
  const fixed = await openReport(artifact);
  assert.deepEqual(panelRows(fixed, "执行顺序")["repeat-case-configuration"], ["未设置（固定顺序）"]);
});

test("confidence intervals display saved bounds, small samples and explicit unavailability", async () => {
  const artifact = resumedReport();
  const available = { status: "available", confidenceLevel: 0.95, method: "wilson-score", n: 2,
    estimate: 1, lower: 0.3423802275, upper: 1, reason: null, warnings: ["small_sample", "incomplete_coverage"] };
  artifact.data.repeatDistributions = [
    { caseEntryId: "case", configurationId: "one", source: "synthetic", plannedRepetitions: 3, sourceSamples: 2,
      outcomes: { passed: 2, failed: 0, unevaluable: 0, missing: 0 }, eligiblePassed: 2, eligibleFailed: 0, excludedSamples: 0,
      samples: [], passRateInterval: available },
    { caseEntryId: "case", configurationId: "one", source: "unknown", plannedRepetitions: 3, sourceSamples: 1,
      outcomes: { passed: 0, failed: 0, unevaluable: 0, missing: 1 }, eligiblePassed: 0, eligibleFailed: 0, excludedSamples: 1,
      samples: [], passRateInterval: { ...available, status: "unavailable", n: 0, estimate: null, lower: null, upper: null, reason: "no_evaluable_samples" } },
  ];
  const get = await openReport(artifact);
  const text = section(get, "通过率置信区间").textContent;
  assert.match(text, /100\.00% \[34\.24%, 100\.00%\]/);
  assert.match(text, /95% · n=2 · wilson-score/);
  assert.doesNotMatch(text, /9500/);
  assert.match(text, /小样本；覆盖不完整/);
  assert.match(text, /区间不可用：没有可评测样本/);
  artifact.data.repeatDistributions[0].passRateInterval = { ...available, confidenceLevel: null };
  const missing = await openReport(artifact);
  const missingText = section(missing, "通过率置信区间").textContent;
  assert.match(missingText, /区间不可用：区间字段缺失/);
  assert.match(missingText, /缺失% · n=2/);
});

test("paired interval panels use their own sample coverage and leave legacy comparisons intact", async () => {
  const artifact = resumedReport();
  const make = (extra) => ({ confidenceLevel: 0.95, n: 2, plannedPairs: 3, includedPairs: 2, excludedPairs: 1,
    excludedReasons: { missing_metric: 1 }, warnings: ["small_sample"], ...extra });
  artifact.data.comparisons = [{ caseEntryId: "case", leftConfigurationId: "left", rightConfigurationId: "right", source: "synthetic",
    plannedPairs: 3, pairedSamples: 3, excludedPairs: 0, rateDifferences: { attemptedPassRate: 0 }, metrics: {},
    uncertainty: { passRateDifference: make({ method: "hoeffding-paired-binary", status: "available", estimate: 0, lower: -1, upper: 1 }),
      metrics: { toolCalls: make({ method: "paired-student-t", status: "unavailable", estimate: 0, lower: null, upper: null, reason: "zero_observed_variance" }) } } }];
  const get = await openReport(artifact);
  const panel = section(get, "配对差值置信区间 · case / left → right / 合成声明");
  assert.match(panel.textContent, /0\.00% \[-100\.00%, 100\.00%\]/);
  assert.match(panel.textContent, /2 \/ 3/);
  assert.match(panel.textContent, /观察方差为零，不输出零宽区间/);
  assert.match(panel.textContent, /missing_metric/);
  delete artifact.data.comparisons[0].uncertainty;
  const legacy = await openReport(artifact);
  assert.equal(section(legacy, "配对差值置信区间 · case / left → right / 合成声明"), undefined);
  assert.ok(section(legacy, "配置比较 · 描述本次实验"));
});

test("source filters retain mixed results with missing sample provenance", async () => {
  const get = await viewer([
    { kind: "experiment", title: "mixed", path: "mixed", sources: ["live", "unknown"] },
    { kind: "experiment", title: "live", path: "live", sources: ["live"] },
    { kind: "experiment", title: "missing", path: "missing", sources: [] },
    { kind: "experiment", title: "synthetic", path: "synthetic", sources: ["synthetic"] },
  ]);
  for (const [source, count] of [["unknown", 2], ["live", 2], ["synthetic", 1], ["", 4]]) {
    get("source").value = source;
    get("source").trigger("change");
    assert.equal(get("count").textContent, `${count} 项`);
    if (source === "unknown") {
      assert.ok(findButton(get("catalog"), "mixed"));
      assert.equal(findButton(get("catalog"), "live"), null);
    }
  }
});

test("sample errors render their type and message while preserving string errors and reasons", async () => {
  const artifact = { kind: "experiment", links: [], data: { experimentName: "broken", entries: [
    { entryId: "one", status: "error", outcome: "unevaluable", error: { type: "ValueError", message: "Batch/case association mismatch" } },
    { entryId: "two", status: "error", error: "Legacy startup error" },
    { entryId: "three", status: "error", reasons: ["First reason", "Second reason"] },
  ] } };
  const get = await viewer([{ id: "runs:broken/experiment-result.json", kind: "experiment", title: "broken", path: "broken" }], artifact);
  findButton(get("catalog"), "broken").trigger("click");
  await new Promise(setImmediate);
  const text = get("detail").textContent;
  assert.match(text, /ValueError: Batch\/case association mismatch/);
  assert.match(text, /Legacy startup error/);
  assert.match(text, /First reason；Second reason/);
  assert.doesNotMatch(text, /\[object Object\]/);
});

function section(get, title) {
  return get("detail").children.find((item) => item.children[0]?.tag === "h2" && item.children[0].textContent === title);
}

function resumedReport() {
  const metric = (total, samples) => ({ observedTotal: total, observedSamples: samples, missingSamples: 0,
    observedMean: total / samples, observedMin: 1, observedMax: total });
  const aggregate = (planned, total) => ({ planned, attempted: planned, finished: planned, skipped: 0,
    attemptedPassRate: { numerator: planned, denominator: planned, value: 1 },
    evaluablePassRate: { numerator: planned, denominator: planned, value: 1 },
    evaluableCoverage: { numerator: planned, denominator: planned, value: 1 }, sourceCounts: { synthetic: planned },
    metrics: { modelCalls: metric(total, planned), cost: { observedTotal: null, observedSamples: 0, missingSamples: planned } } });
  return { kind: "report", links: [
    { label: "sourceResumeResult", id: "runs:resume/experiment-resume-result.json" },
    { label: "resumeVerification / batchResumeResult", id: null, path: "missing/resume-result.json" },
    { label: "1 / sourceBatchResult", id: "runs:old/batch-result.json" },
  ], data: { comparisonReportFormatVersion: 2, experimentName: "续跑报告", experimentId: "original-experiment",
    resumeId: "resume-identity", batchId: null, batchIds: ["old-batch", "new-batch"],
    resumeVerification: { status: "verified" }, summary: aggregate(8, 18),
    reusedSummary: aggregate(2, 5), newlyExecutedSummary: aggregate(6, 13),
    samples: Array.from({ length: 8 }, (_, index) => ({ sampleId: `sample-${index}`, caseId: "retry",
      caseEntryId: "retry-entry", repeatIndex: index < 4 ? 1 : 2, executionOrigin: index < 2 ? "reused" : "new",
      sourceBatchId: index < 2 ? "old-batch" : "new-batch", source: index === 7 ? null : "synthetic",
      status: "finished", outcome: "passed", verification: "verified", configurationMatch: "matched" })),
    groups: [{ caseEntryId: "retry-entry", configurationId: "baseline", summary: aggregate(4, 9),
      matchedSummary: { planned: 4 }, byExecutionOrigin: { reused: { planned: 1 }, new: { planned: 3 } } }],
    comparisons: [], savedSummary: aggregate(8, 18),
  } };
}

async function openReport(artifact, requests = []) {
  const get = await viewer([{ id: "runs:report/report.json", kind: "report", title: "续跑报告", path: "report" }], artifact, requests);
  get("navigation").children.find((item) => item.textContent.includes("配置报告")).trigger("click");
  findButton(get("catalog"), "续跑报告").trigger("click");
  await new Promise(setImmediate);
  return get;
}

test("diagnostic report summaries retain coverage and open sample rechecks", async () => {
  const artifact = resumedReport(), requests = [];
  artifact.data.summary.diagnosticSummary = { observedSamples: 1, missingSamples: 1, samplesWithDiagnostics: 1,
    samplesWithFailures: 1, passedSamplesWithFailures: 1,
    assertionCounts: { passed: 0, failed: 1, insufficient_evidence: 0, not_run: 0 } };
  artifact.data.samples[0].diagnosticSummary = { declaredAssertions: 1, outcomes: { failed: 1 },
    failedAssertionIds: ["format-answer"], insufficientAssertionIds: [], notRunAssertionIds: [] };
  artifact.data.samples[1].diagnosticSummary = null;
  artifact.links.push({ label: "1 / evaluationPath", id: "runs:recheck/evaluation.json" });
  const get = await openReport((path) => path.includes("recheck") ? diagnosticResult() : artifact, requests);
  const panel = section(get, "诊断项覆盖与结果");
  assert.match(panel.textContent, /1 \/ 1/);
  assert.match(panel.textContent, /0 \/ 1 \/ 0 \/ 0/);
  assert.match(panel.textContent, /format-answer/);
  assert.match(panel.textContent, /任务通过率仍取决于必需项/);
  const name = artifact.data.samples[0].sampleId || artifact.data.samples[0].caseRunId;
  findButton(panel, name).trigger("click");
  await new Promise(setImmediate);
  assert.ok(requests.at(-1).includes("recheck%2Fevaluation.json"));
});

test("old reports omit diagnostic panels and partial summaries show missing counts", async () => {
  const old = await openReport(resumedReport());
  assert.equal(section(old, "诊断项覆盖与结果"), undefined);
  const artifact = resumedReport();
  artifact.data.summary.diagnosticSummary = { observedSamples: 0 };
  const get = await openReport(artifact);
  const panel = section(get, "诊断项覆盖与结果");
  assert.match(panel.textContent, /0 \/ 缺失/);
  assert.match(panel.textContent, /缺失 \/ 缺失 \/ 缺失 \/ 缺失/);
});

async function openArchive(artifact, requests = []) {
  const get = await viewer([{ id: "runs:archive-manifest.json", kind: "archive_bundle", title: "归档索引", path: "archive-manifest.json" }], artifact, requests);
  get("navigation").children.find((item) => item.children[1].textContent === "归档包").trigger("click");
  findButton(get("catalog"), "归档索引").trigger("click");
  await new Promise(setImmediate);
  return get;
}

test("archive bundle index opens only approved primary and selected artifact links", async () => {
  const requests = [];
  const artifact = { kind: "archive_bundle", data: { archiveBundleFormatVersion: 1, archiveId: "archive-identity",
    logicalSourceRoot: "C:/retired/project/runs", modelCalled: false, entryPath: "payload/experiment-result.json",
    files: [{ path: "payload/experiment-result.json" }, { path: "payload/report/report.json" }],
    artifacts: [{ path: "payload/experiment-result.json", kind: "experiment" },
      { path: "payload/report/report.json", kind: "report" }] }, links: [
      { label: "entryPath", id: "runs:payload/experiment-result.json" },
      { label: "归档内容 1 / path", id: "runs:payload/experiment-result.json" },
      { label: "归档内容 2 / path", id: "runs:payload/report/report.json" },
    ] };
  const get = await openArchive((path) => path.includes("id=runs%3Aarchive-manifest.json") ? artifact
    : { kind: "experiment", links: [], data: { experimentName: "归档内实验", status: "completed" } }, requests);
  assert.equal(get("title").textContent, "archive-identity");
  const content = section(get, "归档内容");
  assert.match(get("detail").textContent, /清单文件数 2/);
  assert.match(get("detail").textContent, /打包时模型调用 否/);
  assert.match(get("detail").textContent, /浏览方式 只读/);
  assert.match(content.textContent, /配置报告/);
  findButton(content, "打开主入口").trigger("click");
  await new Promise(setImmediate);
  assert.ok(requests.at(-1).includes("id=runs%3Apayload%2Fexperiment-result.json"));
  get("back").trigger("click");
  await new Promise(setImmediate);
  findButton(section(get, "归档内容"), "打开归档内容 2").trigger("click");
  await new Promise(setImmediate);
  assert.ok(requests.at(-1).includes("id=runs%3Apayload%2Freport%2Freport.json"));
  assert.ok(requests.every((path) => path.startsWith("/api/catalog") || path.startsWith("/api/document?")));
});

test("archive origins and paths are literal text and inaccessible links stay unavailable", async () => {
  const html = "<img src=x onerror=bad()>";
  const artifact = { kind: "archive_bundle", data: { archiveBundleFormatVersion: 1, archiveId: "archive",
    logicalSourceRoot: "C:/" + html, entryPath: "payload/" + html, artifacts: [{ path: html, kind: "report" }] },
    links: [{ label: "entryPath", id: null }, { label: "归档内容 1 / path", id: null }] };
  const get = await openArchive(artifact), content = section(get, "归档内容");
  assert.ok(literalText(content).includes(html));
  assert.equal(descendants(content, "img").length, 0);
  assert.equal(findButton(content, "打开主入口"), null);
  assert.equal(findButton(content, "打开归档内容 1"), null);
  assert.match(content.textContent, /主入口缺失或不可访问/);
  assert.match(content.textContent, /内容缺失或不可访问/);
  assert.match(get("detail").textContent, /清单文件数 缺失/);
  assert.match(get("detail").textContent, /打包时模型调用 未知/);
});

function causeSample(required = {}, diagnostic = {}) {
  const role = (value) => ({ declaredAssertions: 1, rootIssues: [], blockedAssertions: [], globalGates: [], ...value });
  return { assertionCausesFormatVersion: 1, status: "available", byRole: { required: role(required), diagnostic: role(diagnostic) } };
}

function causeAggregate(planned, available, required = {}, diagnostic = {}, missingReasons = {}) {
  const role = (value) => ({ declaredSamples: available, rootAffectedSamples: 0, blockedAffectedSamples: 0,
    globalGateAffectedSamples: 0, rootIssueCount: 0, blockedAssertionCount: 0,
    rootReasons: [], globalGateReasons: [], blockedSampleIds: [], ...value });
  return { assertionCauseSummaryFormatVersion: 1, plannedSamples: planned, availableSamples: available,
    missingSamples: planned - available, missingReasons, byRole: { required: role(required), diagnostic: role(diagnostic) } };
}

function causeReport() {
  const artifact = resumedReport();
  const root = { rootAffectedSamples: 1, rootIssueCount: 1, blockedAffectedSamples: 1, blockedAssertionCount: 3,
    rootReasons: [{ reasonCode: "tool_evidence_missing", affectedSamples: 1, sampleIds: ["missing-chain"] }],
    blockedSampleIds: ["missing-chain"] };
  const gate = { globalGateAffectedSamples: 1,
    globalGateReasons: [{ reasonCode: "evaluation_evidence_invalid", affectedSamples: 1, sampleIds: ["global"] }] };
  const format = { declaredSamples: 2, rootAffectedSamples: 1, rootIssueCount: 1,
    rootReasons: [{ reasonCode: "final_text_mismatch", affectedSamples: 1, sampleIds: ["format"] }] };
  artifact.data.summary.assertionCauseSummary = causeAggregate(5, 4, { ...root, ...gate }, format, { not_evaluated: 1 });
  artifact.data.samples = [
    { sampleId: "missing-chain", caseEntryId: "retry-entry", configurationId: "baseline", source: "synthetic", outcome: "unevaluable",
      assertionCauses: causeSample({ declaredAssertions: 5, rootIssues: [{ id: "source", reasonCode: "tool_evidence_missing" }],
        blockedAssertions: [{ id: "target", blockedBy: ["source"] }, { id: "retry", blockedBy: ["target"] }, { id: "verify", blockedBy: ["retry"] }] }) },
    { sampleId: "format", caseEntryId: "rename-entry", configurationId: "baseline", source: "live", outcome: "passed",
      assertionCauses: causeSample({ declaredAssertions: 7 }, { rootIssues: [{ id: "answer-exact", reasonCode: "final_text_mismatch" }] }) },
    { sampleId: "global", caseEntryId: "retry-entry", configurationId: "baseline", source: "synthetic", outcome: "unevaluable",
      assertionCauses: causeSample({ globalGates: [{ id: "read", reasonCode: "evaluation_evidence_invalid" }] }, { declaredAssertions: 0 }) },
    { sampleId: "clean", caseEntryId: "retry-entry", configurationId: "baseline", source: "synthetic", outcome: "passed",
      assertionCauses: causeSample({}, { declaredAssertions: 0 }) },
    { sampleId: "unread", caseEntryId: "retry-entry", configurationId: "baseline", source: null, outcome: "unevaluable",
      assertionCauses: { assertionCausesFormatVersion: 1, status: "unavailable", reasonCode: "not_evaluated" } },
  ];
  artifact.data.groups = [
    { caseEntryId: "retry-entry", configurationId: "baseline", bySource: {
      synthetic: { assertionCauseSummary: causeAggregate(3, 3, { ...root, ...gate }, { declaredSamples: 1 }) },
      unknown: { assertionCauseSummary: causeAggregate(1, 0, {}, {}, { not_evaluated: 1 }) },
    } },
    { caseEntryId: "rename-entry", configurationId: "baseline", bySource: {
      live: { assertionCauseSummary: causeAggregate(1, 1, {}, { ...format, declaredSamples: 1 }) },
    } },
  ];
  artifact.links.push({ label: "1 / evaluationPath", id: "runs:recheck-root/evaluation.json" });
  return artifact;
}

function causeTable(panel, heading) {
  return descendants(panel, "table").find((item) => item.children[0].textContent.includes(heading));
}

test("structured cause reports separate roots, successors, global gates, roles and source coverage", async () => {
  const artifact = causeReport(), before = structuredClone(artifact);
  const get = await openReport(artifact), panel = section(get, "结构化原因汇总");
  assert.match(panel.textContent, /原计划样本 5/);
  assert.match(panel.textContent, /原因可用样本 4/);
  assert.match(panel.textContent, /原因缺失样本 1/);
  assert.match(panel.textContent, /一个源头和三个后继阻断分别统计/);
  const roleRows = causeTable(panel, "声明该角色 / 原因可用样本").children[1].children;
  assert.deepEqual(roleRows[0].children.map((cell) => cell.textContent), ["必需项", "4 / 4", "1", "1", "1", "1", "3"]);
  assert.deepEqual(roleRows[1].children.map((cell) => cell.textContent), ["诊断项", "2 / 4", "1", "0", "0", "1", "0"]);
  const grouped = causeTable(panel, "用例 / 配置 / 来源 / 筛选");
  assert.match(grouped.textContent, /retry-entry \/ baseline \/ 合成声明/);
  assert.match(grouped.textContent, /rename-entry \/ baseline \/ 真实运行声明/);
  assert.match(grouped.textContent, /retry-entry \/ baseline \/ 未知/);
  assert.match(grouped.textContent, /0 \/ 1 \/ 1/);
  const samples = causeTable(panel, "样本 / 逐项复验");
  assert.match(samples.textContent, /源头：source；阻断：target、retry、verify；门禁：无/);
  assert.match(samples.textContent, /未声明该角色断言/);
  assert.match(samples.textContent, /未取得复验结果/);
  assert.equal(artifact.data.samples[1].outcome, "passed");
  assert.deepEqual(artifact, before);
});

test("cause reason filters locally select affected samples then use approved evaluation links", async () => {
  const artifact = causeReport(), requests = [];
  const get = await openReport((path) => path.includes("recheck-root") ? diagnosticResult() : artifact, requests);
  const panel = section(get, "结构化原因汇总"), requestCount = requests.length;
  findButton(panel, "必需项 · 独立源头 · 缺少匹配的工具调用与返回（tool_evidence_missing）").trigger("click");
  let rows = causeTable(panel, "样本 / 逐项复验").children[1].children;
  assert.equal(rows.length, 1);
  assert.match(rows[0].textContent, /missing-chain/);
  assert.equal(requests.length, requestCount);
  findButton(panel, "显示全部原因样本").trigger("click");
  assert.equal(causeTable(panel, "样本 / 逐项复验").children[1].children.length, 5);
  findButton(panel, "retry-entry / baseline / 合成声明").trigger("click");
  rows = causeTable(panel, "样本 / 逐项复验").children[1].children;
  assert.equal(rows.length, 3);
  assert.ok(rows.every((row) => !row.textContent.includes("format") && !row.textContent.includes("unread")));
  findButton(panel, "missing-chain").trigger("click");
  await new Promise(setImmediate);
  assert.ok(requests.at(-1).includes("id=runs%3Arecheck-root%2Fevaluation.json"));
  assert.equal(get("title").textContent, "strict-answer");
});

test("cause report filters retain separate diagnostic and global gate samples without requiring links", async () => {
  const artifact = causeReport(), get = await openReport(artifact), panel = section(get, "结构化原因汇总");
  findButton(panel, "诊断项 · 独立源头 · 最终回复不符（final_text_mismatch）").trigger("click");
  let rows = causeTable(panel, "样本 / 逐项复验").children[1].children;
  assert.equal(rows.length, 1);
  assert.match(rows[0].textContent, /format/);
  assert.match(rows[0].textContent, /通过/);
  assert.match(rows[0].textContent, /复验文件缺失或超出浏览目录/);
  findButton(panel, "必需项 · 全局门禁 · 评测证据无效（evaluation_evidence_invalid）").trigger("click");
  rows = causeTable(panel, "样本 / 逐项复验").children[1].children;
  assert.equal(rows.length, 1);
  assert.match(rows[0].textContent, /global/);
  assert.match(rows[0].textContent, /源头：无；阻断：无；门禁：read/);
  findButton(panel, "必需项 · 后继阻断 · 前置断言未通过（dependency_not_passed）").trigger("click");
  assert.equal(causeTable(panel, "样本 / 逐项复验").children[1].children.length, 1);
});

test("legacy, unknown and incomplete cause summaries never invent zero issue coverage", async () => {
  const old = await openReport(resumedReport());
  assert.match(section(old, "结构化原因汇总").textContent, /未保存结构化原因汇总/);
  assert.match(section(old, "结构化原因汇总").textContent, /缺失不代表没有问题/);
  const future = causeReport();
  future.data.summary.assertionCauseSummary.assertionCauseSummaryFormatVersion = 2;
  const futureView = await openReport(future);
  assert.match(section(futureView, "结构化原因汇总").textContent, /版本不支持/);
  assert.equal(descendants(section(futureView, "结构化原因汇总"), "table").length, 0);
  const partial = resumedReport();
  partial.data.summary.assertionCauseSummary = { assertionCauseSummaryFormatVersion: 1, availableSamples: 0 };
  const partialView = await openReport(partial), panel = section(partialView, "结构化原因汇总");
  assert.match(panel.textContent, /原计划样本 缺失/);
  assert.match(panel.textContent, /原因缺失样本 缺失/);
  assert.match(panel.textContent, /原因列表不完整，不能推断零问题/);
});

test("cause report reason labels and sample IDs remain literal text without unapproved navigation", async () => {
  const artifact = causeReport(), html = "<img src=x onerror=bad()>";
  artifact.data.samples[0].sampleId = html;
  artifact.data.summary.assertionCauseSummary.byRole.required.rootReasons[0] = { reasonCode: html, affectedSamples: 1, sampleIds: [html] };
  artifact.links = [];
  const get = await openReport(artifact), panel = section(get, "结构化原因汇总");
  assert.ok(literalText(panel).includes(html));
  assert.equal(descendants(panel, "img").length, 0);
  assert.equal(findButton(panel, html), null);
  assert.match(panel.textContent, /复验文件缺失或超出浏览目录/);
});

test("empty cause lists require explicit zero counts before claiming no issues", async () => {
  const noIssues = "可用诊断中没有独立源头、后继阻断或全局门禁。";
  for (const role of ["required", "diagnostic"]) {
    for (const change of [
      (value) => Object.assign(value, { rootAffectedSamples: 1, rootIssueCount: 1 }),
      (value) => Object.assign(value, { blockedAffectedSamples: 1, blockedAssertionCount: 3 }),
      (value) => Object.assign(value, { globalGateAffectedSamples: 1 }),
      (value) => { delete value.rootIssueCount; },
    ]) {
      const artifact = causeReport(), value = causeAggregate(1, 1);
      change(value.byRole[role]);
      artifact.data.summary.assertionCauseSummary = value;
      const panel = section(await openReport(artifact), "结构化原因汇总");
      assert.match(panel.textContent, /原因列表与计数不一致或缺失，不能推断零问题/);
      assert.ok(!panel.textContent.includes(noIssues));
    }
  }
  const valid = causeReport();
  valid.data.summary.assertionCauseSummary = causeAggregate(1, 1, {}, { declaredSamples: 0 });
  assert.ok(section(await openReport(valid), "结构化原因汇总").textContent.includes(noIssues));
  valid.data.summary.assertionCauseSummary = causeAggregate(1, 0);
  const missing = section(await openReport(valid), "结构化原因汇总");
  assert.match(missing.textContent, /没有可用诊断，不能推断零问题/);
  assert.ok(!missing.textContent.includes(noIssues));
});

test("partial sample cause details stay unavailable instead of inventing empty issue lists", async () => {
  for (const change of [
    (value) => { delete value.byRole.diagnostic; },
    (value) => { delete value.byRole.required.declaredAssertions; },
    (value) => { delete value.byRole.required.rootIssues; },
    (value) => { value.byRole.required.declaredAssertions = 0; },
  ]) {
    const artifact = causeReport();
    change(artifact.data.samples[0].assertionCauses);
    const get = await openReport(artifact), panel = section(get, "结构化原因汇总");
    const row = causeTable(panel, "样本 / 逐项复验").children[1].children[0];
    assert.equal(row.children[3].textContent, "原因明细不完整");
    assert.equal(row.children[4].textContent, "缺失");
    assert.equal(row.children[5].textContent, "缺失");
    assert.doesNotMatch(row.textContent, /源头：无；阻断：无；门禁：无/);
    assert.match(panel.textContent, /原因可用样本 4/); // The stored aggregate is displayed independently.
  }
});

test("version two shows both batches, execution origins and separate historical and new usage", async () => {
  const requests = [], get = await openReport(resumedReport(), requests);
  const binding = section(get, "续跑来源与保存的关联复核");
  assert.ok(binding);
  assert.match(binding.textContent, /old-batch/);
  assert.match(binding.textContent, /new-batch/);
  const partition = section(get, "历史复用与本次新增");
  assert.match(partition.textContent, /历史复用/);
  assert.match(partition.textContent, /本次新增/);
  const metrics = section(get, "历史与新增用量（分别统计）");
  const cells = metrics.children.find((item) => item.tag === "table").children[1].children[0].children.map((item) => item.textContent);
  assert.deepEqual(cells, ["已结算模型调用", "5", "2 / 0", "13", "6 / 0"]);
  const costs = metrics.children.find((item) => item.tag === "table").children[1].children.at(-1).textContent;
  assert.match(costs, /缺失/);
  const samples = section(get, "逐次结果");
  assert.match(samples.textContent, /执行归属/);
  assert.match(samples.textContent, /历史复用/);
  assert.match(samples.textContent, /本次新增/);
  assert.match(samples.textContent, /合成声明/);
  const lastSample = samples.children.find((item) => item.tag === "table").children[1].children.at(-1);
  assert.equal(lastSample.children[3].textContent, "缺失");
  assert.ok(section(get, "续跑结果保存的合并汇总指标"));
  findButton(get("detail"), "查看来源批次").trigger("click");
  await new Promise(setImmediate);
  assert.ok(requests.some((path) => path.includes("id=runs%3Aold%2Fbatch-result.json")));
  findButton(get("detail"), "原实验续跑结果").trigger("click");
  await new Promise(setImmediate);
  assert.ok(requests.some((path) => path.includes("id=runs%3Aresume%2Fexperiment-resume-result.json")));
  assert.ok(requests.every((path) => path.startsWith("/api/catalog") || path.startsWith("/api/document?")));
});

test("version two preserves missing origin, absent aggregates and text-only malicious labels", async () => {
  const artifact = resumedReport();
  artifact.data.samples[0].executionOrigin = null;
  artifact.data.samples[0].sourceBatchId = "<script>alert(1)</script>";
  artifact.data.newlyExecutedSummary = null;
  const get = await openReport(artifact);
  const samples = section(get, "逐次结果");
  const firstRow = samples.children.find((item) => item.tag === "table").children[1].children[0];
  assert.match(firstRow.children[1].textContent, /未知/);
  assert.match(firstRow.children[1].textContent, /<script>alert\(1\)<\/script>/);
  assert.match(section(get, "历史与新增用量（分别统计）").textContent, /缺失/);
  assert.match(section(get, "关联文件与原始证据").textContent, /缺失或超出浏览目录/);
  const tags = [];
  function visit(item) { tags.push(item.tag); item.children.forEach(visit); }
  visit(get("detail"));
  assert.equal(tags.includes("script"), false);
});

test("version one report retains its original layout without continuation panels", async () => {
  const artifact = resumedReport();
  artifact.data.comparisonReportFormatVersion = 1;
  const get = await openReport(artifact);
  assert.equal(section(get, "历史复用与本次新增"), undefined);
  assert.equal(section(get, "续跑来源与保存的关联复核"), undefined);
  assert.ok(section(get, "原实验保存的汇总指标"));
  assert.doesNotMatch(section(get, "逐次结果").textContent, /执行归属/);
});

test("version three lists all historical batches and the latest batch without hiding the continuation chain", async () => {
  const artifact = resumedReport(), requests = [];
  artifact.data.comparisonReportFormatVersion = 3;
  artifact.data.batchIds = ["original", "middle", "latest"];
  artifact.data.resumeChain = [{ resumeId: "first-resume" }, { resumeId: "second-resume" }];
  artifact.links.push({ label: "续跑 1 / resultPath", id: "runs:chain/first.json" });
  const get = await openReport(artifact, requests);
  const binding = section(get, "续跑来源与保存的关联复核");
  assert.match(binding.textContent, /原批次\s+original/);
  assert.match(binding.textContent, /历史续跑\s+middle/);
  assert.match(binding.textContent, /本轮新增\s+latest/);
  assert.match(section(get, "连续续跑链").textContent, /first-resume/);
  assert.match(section(get, "连续续跑链").textContent, /second-resume/);
  assert.match(section(get, "连续续跑链").textContent, /缺失或超出浏览目录/);
  assert.ok(section(get, "历史与新增用量（分别统计）"));
  assert.match(section(get, "逐次结果").textContent, /执行归属/);
  findButton(get("detail"), "查看续跑结果").trigger("click");
  await new Promise(setImmediate);
  assert.ok(requests.some((path) => path.includes("id=runs%3Achain%2Ffirst.json")));
});

async function openSavedResult(kind, data, requests = []) {
  const artifact = { kind, links: [], data };
  const get = await viewer([{ id: "runs:saved/result.json", kind: "experiment", title: "保存结果", path: "saved" }], artifact, requests);
  findButton(get("catalog"), "保存结果").trigger("click");
  await new Promise(setImmediate);
  return get;
}

function schedulingRows(get) {
  const scheduling = section(get, "调度与停止");
  assert.ok(scheduling);
  function findTable(item) {
    return item.tag === "table" ? item : item.children.map(findTable).find(Boolean);
  }
  const rows = findTable(scheduling).children[1].children;
  return Object.fromEntries(rows.map((row) => row.children.map((cell) => cell.textContent)));
}

test("saved scheduling controls appear for batches, experiments and both continuation kinds", async () => {
  for (const kind of ["batch", "experiment", "batch_resume", "experiment_resume"]) {
    const requests = [], get = await openSavedResult(kind, {
      status: "stopped", stopReason: "stop_after", stopAfter: 2, stopAfterTokens: 100,
      tokenUsage: { observedTotal: 0, observedSamples: 2, missingSamples: 0 },
      combinedSummary: { metrics: { totalTokens: { observedTotal: 987654 } } },
      reusedSummary: { metrics: { totalTokens: { observedTotal: 987654 } } },
    }, requests);
    const rows = schedulingRows(get);
    assert.equal(rows["调度状态"], "已停止");
    assert.match(rows["停止原因"], /达到任务数阈值/);
    assert.match(rows["停止原因"], /stop_after/);
    assert.equal(rows["任务数停止阈值"], "2");
    assert.equal(rows["本轮 token 停止阈值"], "100");
    assert.equal(rows["本轮已观测 token"], "0");
    assert.equal(rows["本轮 token 观测 / 缺失样本"], "2 / 0");
    assert.doesNotMatch(section(get, "调度与停止").textContent, /987654/);
    assert.ok(requests.length >= 2);
    assert.ok(requests.every((path) => path.startsWith("/api/catalog") || path.startsWith("/api/document?")));
  }
});

test("configured thresholds do not imply a stop when the saved result completed", async () => {
  const get = await openSavedResult("experiment", {
    status: "completed", stopReason: null, stopAfter: null, stopAfterTokens: 2,
    tokenUsage: { observedTotal: 5, observedSamples: 1, missingSamples: 0 },
  });
  const rows = schedulingRows(get);
  assert.equal(rows["调度状态"], "已完成");
  assert.equal(rows["停止原因"], "未触发");
  assert.equal(rows["任务数停止阈值"], "未设置");
  assert.equal(rows["本轮 token 停止阈值"], "2");
  assert.equal(rows["本轮已观测 token"], "5");
  assert.doesNotMatch(rows["停止原因"], /达到/);
});

test("legacy and unavailable scheduling fields stay missing without zero or completion inference", async () => {
  for (const fields of [{}, { stopAfter: null, stopAfterTokens: null, tokenUsage: null }]) {
    const get = await openSavedResult("batch", { status: "stopped", ...fields });
    const rows = schedulingRows(get);
    assert.equal(rows["停止原因"], "缺失");
    assert.equal(rows["任务数停止阈值"], "stopAfter" in fields ? "未设置" : "缺失");
    assert.equal(rows["本轮 token 停止阈值"], "stopAfterTokens" in fields ? "未设置" : "缺失");
    assert.equal(rows["本轮已观测 token"], "缺失");
    assert.equal(rows["本轮 token 观测 / 缺失样本"], "缺失 / 缺失");
  }
  const get = await openSavedResult("batch_resume", {
    status: "stopped", stopReason: null, stopAfter: null, stopAfterTokens: 1,
    tokenUsage: { observedTotal: null, observedSamples: 0, missingSamples: 1 },
  });
  const rows = schedulingRows(get);
  assert.equal(rows["停止原因"], "无已保存停止原因");
  assert.equal(rows["本轮已观测 token"], "缺失");
  assert.equal(rows["本轮 token 观测 / 缺失样本"], "0 / 1");
});

test("saved stop reasons distinguish token thresholds, missing usage and execution failures", async () => {
  for (const [reason, label] of [
    ["stop_after_tokens", "达到 token 阈值"], ["token_usage_unavailable", "token 用量不可用"],
    ["failure_policy", "失败策略"], ["cleanup_unconfirmed", "清理未确认"],
    ["user_interrupt", "用户中断"], ["runner_error", "任务运行错误"],
  ]) {
    const get = await openSavedResult("experiment_resume", { status: "stopped", stopReason: reason, stopAfterTokens: 100 });
    const rows = schedulingRows(get);
    assert.ok(rows["停止原因"].includes(label));
    assert.ok(rows["停止原因"].includes(reason));
  }
});

test("unknown stop reasons remain text and reports do not acquire scheduling claims", async () => {
  const reason = "<script>alert(1)</script>";
  const get = await openSavedResult("experiment", { status: "stopped", stopReason: reason });
  assert.equal(schedulingRows(get)["停止原因"], reason);
  const tags = [];
  function visit(item) { tags.push(item.tag); item.children.forEach(visit); }
  visit(section(get, "调度与停止"));
  assert.equal(tags.includes("script"), false);
  assert.equal(section(await openReport(resumedReport()), "调度与停止"), undefined);
});

test("continuation categories keep independent counts, filters and readable result identities", async () => {
  const requests = [], get = await viewer([
    { id: "runs:experiment/experiment-result.json", kind: "experiment", title: "原实验", path: "experiment" },
    { id: "runs:first/experiment-resume-result.json", kind: "experiment_resume", title: "first", path: "first", outcome: "passed", sources: ["live"] },
    { id: "runs:second/experiment-resume-result.json", kind: "experiment_resume", title: "second", path: "second", outcome: "failed", sources: ["live", "unknown"] },
    { id: "runs:batch/resume-result.json", kind: "batch_resume", title: "batch", path: "batch", outcome: "passed", sources: ["synthetic"] },
  ], { kind: "experiment_resume", links: [], data: { resumeId: "first-resume-id", status: "completed" } }, requests);
  const nav = (label) => get("navigation").children.find((item) => item.children[1].textContent === label);
  assert.equal(nav("实验").children[2].textContent, "1");
  assert.equal(nav("实验续跑").children[2].textContent, "2");
  assert.equal(nav("批次续跑").children[2].textContent, "1");
  nav("实验续跑").trigger("click");
  assert.equal(get("count").textContent, "2 项");
  assert.equal(findButton(get("catalog"), "原实验"), null);
  get("source").value = "unknown";
  get("source").trigger("change");
  assert.equal(get("count").textContent, "1 项");
  assert.ok(findButton(get("catalog"), "second"));
  get("source").value = "";
  get("source").trigger("change");
  get("outcome").value = "passed";
  get("outcome").trigger("change");
  assert.equal(get("count").textContent, "1 项");
  findButton(get("catalog"), "first").trigger("click");
  await new Promise(setImmediate);
  assert.equal(get("title").textContent, "first-resume-id");
  assert.ok(section(get, "调度与停止"));
  get("back").trigger("click");
  assert.equal(get("title").textContent, "实验续跑");
  nav("批次续跑").trigger("click");
  assert.equal(get("count").textContent, "1 项");
  assert.ok(findButton(get("catalog"), "batch"));
  assert.ok(requests.every((path) => path.startsWith("/api/catalog") || path.startsWith("/api/document?")));
});

function panelRows(get, title) {
  const panel = section(get, title);
  assert.ok(panel);
  function findTable(item) {
    return item.tag === "table" ? item : item.children.map(findTable).find(Boolean);
  }
  return Object.fromEntries(findTable(panel).children[1].children.map((row) =>
    [row.children[0].textContent, row.children.slice(1).map((cell) => cell.textContent)]));
}

function savedContinuation() {
  const aggregate = (planned, attempted, passed, failed, tokens) => ({ planned, attempted, finished: attempted,
    skipped: planned - attempted, errors: 0, outcomes: { passed, failed, unevaluable: 0 },
    attemptedPassRate: { numerator: passed, denominator: attempted, value: passed / attempted },
    evaluablePassRate: { numerator: passed, denominator: passed + failed, value: passed / (passed + failed) },
    evaluableCoverage: { numerator: passed + failed, denominator: planned, value: (passed + failed) / planned },
    metrics: { totalTokens: { observedTotal: tokens, observedSamples: attempted, missingSamples: planned - attempted },
      cost: { observedTotal: null, observedSamples: 0, missingSamples: planned } } });
  return { resumeId: "current-resume", sourceExperimentId: "original-experiment", sourceBatchId: "latest-source-batch",
    sourceResumeId: "previous-resume", status: "stopped", outcome: "failed", stopReason: "stop_after",
    counts: { original: 8, reused: 2, newSamples: 6, blocked: 0 },
    newlyExecutedSummary: aggregate(6, 2, 2, 0, 0), combinedSummary: aggregate(8, 4, 3, 1, 700) };
}

test("continuation details separate startup counts from saved new and combined results", async () => {
  for (const kind of ["batch_resume", "experiment_resume"]) {
    const data = savedContinuation(), requests = [];
    data[kind === "batch_resume" ? "batchResumeResultFormatVersion" : "experimentResumeResultFormatVersion"] = kind === "batch_resume" ? 1 : 2;
    const get = await openSavedResult(kind, data, requests);
    const identity = panelRows(get, "续跑身份与启动计划");
    assert.deepEqual(identity["续跑 ID"], ["current-resume"]);
    assert.deepEqual(identity["来源批次 ID"], ["latest-source-batch"]);
    assert.deepEqual(identity["任务结论"], ["未通过"]);
    if (kind === "experiment_resume") {
      assert.deepEqual(identity["原实验 ID"], ["original-experiment"]);
      assert.deepEqual(identity["上轮续跑 ID"], ["previous-resume"]);
      assert.deepEqual(identity["启动时原计划"], ["8"]);
      assert.deepEqual(identity["启动时历史复用"], ["2"]);
      assert.deepEqual(identity["启动时本轮计划"], ["6"]);
      assert.deepEqual(identity["启动时阻断"], ["0"]);
    } else {
      assert.equal(identity["原实验 ID"], undefined);
      assert.equal(identity["启动时原计划"], undefined);
    }
    const results = panelRows(get, "续跑保存结果汇总");
    for (const [label, expected] of [
      ["计划样本", ["6", "8"]], ["已尝试", ["2", "4"]], ["已结束", ["2", "4"]],
      ["跳过", ["4", "4"]], ["错误", ["0", "0"]], ["通过", ["2", "3"]],
      ["未通过", ["0", "1"]], ["无法评测", ["0", "0"]],
    ]) assert.deepEqual(results[label], expected);
    assert.ok(results["全尝试通过"][0].includes("2 / 2"));
    assert.ok(results["全尝试通过"][1].includes("3 / 4"));
    assert.ok(results["可评测覆盖"][0].includes("2 / 6"));
    assert.ok(results["可评测覆盖"][1].includes("4 / 8"));
    const usage = panelRows(get, "续跑保存用量");
    assert.deepEqual(usage["总 token"], ["0", "2 / 4", "700", "4 / 4"]);
    assert.deepEqual(usage["费用"], ["缺失", "0 / 6", "缺失", "0 / 8"]);
    assert.ok(requests.every((path) => path.startsWith("/api/catalog") || path.startsWith("/api/document?")));
  }
});

test("version one experiment continuation keeps absent combined results missing", async () => {
  const data = savedContinuation();
  data.experimentResumeResultFormatVersion = 1;
  delete data.combinedSummary;
  delete data.sourceResumeId;
  const get = await openSavedResult("experiment_resume", data);
  assert.deepEqual(panelRows(get, "续跑身份与启动计划")["上轮续跑 ID"], ["缺失"]);
  const results = panelRows(get, "续跑保存结果汇总");
  assert.deepEqual(results["计划样本"], ["6", "缺失"]);
  assert.ok(Object.values(results).every((cells) => cells[1] === "缺失"));
  assert.deepEqual(panelRows(get, "续跑保存用量")["总 token"], ["0", "2 / 4", "缺失", "缺失 / 缺失"]);
});

test("running continuation summaries remain missing instead of borrowing startup plans", async () => {
  const data = { ...savedContinuation(), experimentResumeResultFormatVersion: 2, status: "running", outcome: null,
    newlyExecutedSummary: null, combinedSummary: null };
  const get = await openSavedResult("experiment_resume", data);
  const identity = panelRows(get, "续跑身份与启动计划");
  assert.deepEqual(identity["启动时本轮计划"], ["6"]);
  assert.deepEqual(identity["任务结论"], ["缺失"]);
  assert.ok(Object.values(panelRows(get, "续跑保存结果汇总")).every((cells) => cells.every((cell) => cell === "缺失")));
  assert.deepEqual(panelRows(get, "续跑保存用量")["总 token"], ["缺失", "缺失 / 缺失", "缺失", "缺失 / 缺失"]);
});

test("ordinary experiments and reports retain their layouts without continuation result panels", async () => {
  for (const get of [await openSavedResult("experiment", savedContinuation()), await openReport(resumedReport())]) {
    for (const title of ["续跑身份与启动计划", "续跑保存结果汇总", "续跑保存用量"]) {
      assert.equal(section(get, title), undefined);
    }
  }
});

test("nested batch continuation summaries describe the source batch rather than the whole experiment", async () => {
  const data = savedContinuation();
  data.batchResumeResultFormatVersion = 1;
  data.newlyExecutedSummary = { planned: 2 };
  data.combinedSummary = { planned: 4 };
  const get = await openSavedResult("batch_resume", data);
  const results = section(get, "续跑保存结果汇总"), usage = section(get, "续跑保存用量");
  assert.match(results.textContent, /来源批次计划（含复用）/);
  assert.doesNotMatch(results.textContent, /全部原计划/);
  assert.match(usage.textContent, /来源批次累计/);
  assert.doesNotMatch(usage.textContent, /全部累计/);
  assert.match(section(get, "续跑身份与启动计划").textContent, /不代表整个原实验/);
  assert.deepEqual(panelRows(get, "续跑保存结果汇总")["计划样本"], ["2", "4"]);
  const experiment = await openSavedResult("experiment_resume", savedContinuation());
  assert.match(section(experiment, "续跑保存结果汇总").textContent, /全部原计划（含历史）/);
});

test("reserved execution batch links open saved checkpoints and keep inaccessible bindings visible", async () => {
  for (const id of ["runs:active/batch-result.json", null]) {
    const artifact = { kind: "experiment", data: { status: "running" },
      links: [{ label: "batchBinding / resultPath", id, path: "active/batch-result.json" }] };
    const requests = [], get = await viewer([
      { id: "runs:experiment/experiment-result.json", kind: "experiment", title: "进行中", path: "experiment" },
    ], artifact, requests);
    findButton(get("catalog"), "进行中").trigger("click");
    await new Promise(setImmediate);
    const files = section(get, "关联文件与原始证据");
    assert.match(files.textContent, /执行批次检查点（保存关联）/);
    if (id) {
      findButton(files, "执行批次检查点（保存关联）").trigger("click");
      await new Promise(setImmediate);
      assert.ok(requests.some((path) => path.includes("id=runs%3Aactive%2Fbatch-result.json")));
    } else {
      assert.equal(findButton(files, "执行批次检查点（保存关联）"), null);
      assert.match(files.textContent, /缺失或超出浏览目录/);
    }
    assert.ok(requests.every((path) => path.startsWith("/api/catalog") || path.startsWith("/api/document?")));
  }
});

function regressionArtifact(code = 2) {
  const ref = { provider: "synthetic", model: "base-model", profile: "headless", pluginVersion: "0.1.2" };
  const sample = (side, repeat, outcome) => ({ sampleId: `${side}-${repeat}`, caseEntryId: "confirmation", caseId: "rename",
    configurationId: side, repeatIndex: repeat, status: "finished", caseRunId: `${side}-case-${repeat}`,
    runId: `${side}-run-${repeat}`, sessionId: `${side}-session-${repeat}`, source: "synthetic", outcome,
    verification: "verified", configurationMatch: "matched", executionStatus: "completed", recordingOutcome: "complete",
    assertionOutcome: outcome, requestedConfiguration: side === "candidate" ? { ...ref, model: "candidate-model" } : ref,
    configuration: side === "candidate" ? { ...ref, model: "candidate-model" } : ref, changedFields: [], reasons: [],
    sourceEvidencePath: `runs:unapproved-${side}-${repeat}`, saved: { outcome, source: "synthetic", configurationMatch: "matched",
      executionStatus: "completed", recordingOutcome: "complete", assertionOutcome: outcome } });
  const pairs = [1, 2].map((repeat) => ({ caseEntryId: "confirmation", repeatIndex: repeat,
    change: code === 0 ? "unchanged_failed" : repeat === 1 ? "regression" : code === 2 ? "unavailable" : "unchanged_passed",
    reasons: code === 2 && repeat === 2 ? ["candidate_evidence_unavailable"] : [], taskChanges: [],
    baseline: sample("baseline", repeat, code === 0 ? "failed" : "passed"),
    candidate: sample("candidate", repeat, code === 0 || repeat === 1 ? "failed" : "passed") }));
  if (code !== 0) {
    pairs[0].candidate.saved.outcome = "passed";
    pairs[0].candidate.changedFields = ["outcome", "assertionOutcome"];
  }
  if (code === 2) Object.assign(pairs[1].candidate, { status: "skipped", outcome: null, source: null,
    executionStatus: null, recordingOutcome: null, assertionOutcome: null, verification: "skipped" });
  const approved = (side, repeat) => ({ status: "available", evaluationId: `runs:${side}/sample-${repeat}/evaluation.json`,
    evidenceId: `runs:${side}/sample-${repeat}/evidence.json`, assertionTrace: { id: `runs:${side}/sample-${repeat}/traces/${"a".repeat(64)}.jsonl`,
      runId: `${side}-run-${repeat}`, sessionId: `${side}-session-${repeat}` } });
  return { kind: "regression_comparison", links: [{ id: "runs:unapproved-footer", label: "unapproved generic link" }],
    regressionSources: { baseline: { status: "available", id: "runs:baseline/experiment-result.json" },
      candidate: { status: "available", id: "runs:candidate/experiment-result.json" } },
    regressionEvidence: [1, 2].map((index) => ({ index, baseline: approved("baseline", index),
      candidate: code === 2 && index === 2 ? { status: "not_recorded", reason: "该侧尚未执行，没有保存证据。" } : approved("candidate", index) })),
    data: { regressionComparisonFormatVersion: 1, status: "compared", modelCalled: false, generatedAt: "2026-11-11T00:00:00Z",
      baseline: { experimentId: "base-experiment", sourceResult: "runs:unapproved-source-baseline", plannedSamples: 2,
        planVerification: { status: "verified" }, configuration: { configurationId: "baseline", configRef: ref } },
      candidate: { experimentId: "candidate-experiment", sourceResult: "runs:unapproved-source-candidate", plannedSamples: 2,
        planVerification: { status: "verified" }, configuration: { configurationId: "candidate", configRef: { ...ref, model: "candidate-model" } } },
      allowedConfigurationChanges: ["model"], configurationChanges: [{ field: "model", baseline: "base-model", candidate: "candidate-model", allowed: true }],
      comparability: { status: code === 2 ? "incomplete" : "comparable", issues: [] },
      counts: { regression: code === 0 ? 0 : 1, improvement: 0, unchanged_passed: code === 1 ? 1 : 0,
        unchanged_failed: code === 0 ? 2 : 0, missing_in_baseline: 0, missing_in_candidate: 0, incompatible: 0,
        unavailable: code === 2 ? 1 : 0, compared: code === 2 ? 1 : 2, total: 2 },
      outcome: ["passed", "failed", "unevaluable"][code], exitCode: code, hasRegressions: code !== 0,
      samples: pairs, limitations: ["Only the saved independent experiments are compared."] } };
}

async function openRegression(artifact = regressionArtifact(), requests = []) {
  const saved = typeof artifact === "function" ? regressionArtifact() : artifact;
  const get = await viewer([{ id: "runs:regression.json", kind: "regression_comparison", title: "保存的基线回归", path: "regression.json",
    outcome: saved.data.outcome, status: saved.data.status, regressionCounts: saved.data.counts, sources: ["synthetic", "unknown"] }], artifact, requests);
  get("navigation").children.find((item) => item.children[1].textContent === "基线回归比较").trigger("click");
  findButton(get("catalog"), "保存的基线回归").trigger("click");
  await new Promise(setImmediate);
  return get;
}

test("baseline regression pages retain gate exit codes, coverage and fresh versus saved sample verdicts", async () => {
  for (const code of [0, 1, 2]) {
    const artifact = regressionArtifact(code), before = JSON.stringify(artifact.data);
    const get = await openRegression(artifact);
    assert.equal(get("title").textContent, "基线回归比较");
    assert.match(get("section-label").textContent, /筛选使用保存的门禁结论/);
    assert.match(get("detail").textContent, new RegExp(`原退出码 ${code}`));
    assert.match(get("detail").textContent, new RegExp(`可比 / 样本键并集 ${code === 2 ? 1 : 2} / 2`));
    assert.match(section(get, "比较门禁与覆盖").textContent, /0 表示完整可比且无退化，不表示所有任务通过/);
    assert.match(get("detail").textContent, /base-experiment/);
    assert.match(get("detail").textContent, /candidate-experiment/);
    assert.match(section(get, "配置变化与允许范围").textContent, /base-model candidate-model 是/);
    assert.match(section(get, "逐样本基线回归对照").textContent, /比较时复验值 来源保存值/);
    if (code !== 0) assert.match(get("detail").textContent, /任务结论 未通过 通过/);
    assert.equal(JSON.stringify(artifact.data), before);
  }
});

test("regression catalog uses gate outcomes and preserves source filters", async () => {
  const get = await openRegression();
  assert.equal(get("outcome-label").textContent, "门禁结论");
  get("back").trigger("click");
  assert.match(get("catalog").textContent, /门禁结论 \/ 覆盖/);
  assert.match(get("catalog").textContent, /退化 1 · 可比 1 \/ 2/);
  get("outcome").value = "failed"; get("outcome").trigger("change");
  assert.match(get("catalog").textContent, /暂无匹配记录/);
  get("outcome").value = "unevaluable"; get("outcome").trigger("change");
  get("source").value = "unknown"; get("source").trigger("change");
  assert.ok(findButton(get("catalog"), "保存的基线回归"));
  get("navigation").children.find((item) => item.children[1].textContent === "实验").trigger("click");
  assert.equal(get("outcome-label").textContent, "任务结论");
  assert.equal(get("outcome").value, "");
});

test("regression evidence buttons navigate only separately approved source and side identifiers", async () => {
  const fixture = regressionArtifact(), requests = [];
  const get = await openRegression((path) => new URLSearchParams(path.split("?")[1]).get("id") === "runs:regression.json"
    ? fixture : { kind: "markdown", text: "approved destination", links: [] }, requests);
  for (const [label, expected] of [["基线来源实验", "runs:baseline/experiment-result.json"], ["候选来源实验", "runs:candidate/experiment-result.json"],
    ["基线原评测", "runs:baseline/sample-1/evaluation.json"], ["候选原评测", "runs:candidate/sample-1/evaluation.json"],
    ["基线证据", "runs:baseline/sample-1/evidence.json"], ["候选证据", "runs:candidate/sample-1/evidence.json"],
    ["基线轨迹", `runs:baseline/sample-1/traces/${"a".repeat(64)}.jsonl`], ["候选轨迹", `runs:candidate/sample-1/traces/${"a".repeat(64)}.jsonl`]]) {
    findButton(get("detail"), label).trigger("click");
    await new Promise(setImmediate);
    const query = new URLSearchParams(requests.at(-1).split("?")[1]);
    assert.equal(query.get("id"), expected);
    assert.equal(query.has("seq") || query.has("runId") || query.has("sessionId"), false);
    get("back").trigger("click"); await new Promise(setImmediate);
  }
  assert.ok(requests.every((path) => !decodeURIComponent(path).includes("unapproved")));
});

test("regression filters keep the original sample index and overall denominator", async () => {
  const fixture = regressionArtifact(), requests = [];
  fixture.regressionEvidence.reverse();
  const get = await openRegression(fixture, requests);
  const scope = section(get, "逐样本基线回归对照"), filter = descendants(scope, "select")[0];
  filter.value = "unavailable"; filter.trigger("change");
  assert.match(scope.textContent, /当前显示 1 \/ 2/);
  assert.match(scope.textContent, /第 2 轮/);
  assert.doesNotMatch(scope.textContent, /第 1 轮/);
  assert.match(get("detail").textContent, /可比 \/ 样本键并集 1 \/ 2/);
  assert.equal(findButton(scope, "候选原评测"), null);
  findButton(scope, "基线原评测").trigger("click"); await new Promise(setImmediate);
  assert.equal(new URLSearchParams(requests.at(-1).split("?")[1]).get("id"), "runs:baseline/sample-2/evaluation.json");
});

test("regression change selectors distinguish improvement, unchanged, missing and incompatible pairs", async () => {
  const fixture = regressionArtifact();
  const base = fixture.data.samples[0];
  fixture.data.samples = ["regression", "improvement", "unchanged_passed", "unchanged_failed", "missing_in_baseline", "missing_in_candidate", "incompatible", "unavailable", "future_change"]
    .map((change, index) => ({ ...base, change, caseEntryId: `entry-${index}`, repeatIndex: index + 1 }));
  fixture.regressionEvidence = [];
  const get = await openRegression(fixture), scope = section(get, "逐样本基线回归对照"), filter = descendants(scope, "select")[0];
  for (const [value, entries] of [["improvement", [1]], ["unchanged", [2, 3]], ["missing", [4, 5]], ["incompatible", [6]], ["unavailable", [7]]]) {
    filter.value = value; filter.trigger("change");
    const cards = descendants(scope, "article");
    assert.equal(cards.length, entries.length);
    assert.deepEqual(cards.map((card) => descendants(card, "h3")[0].textContent), entries.map((index) => `entry-${index} · 第 ${index + 1} 轮`));
  }
  filter.value = "all"; filter.trigger("change");
  assert.match(scope.textContent, /future_change/);
});

test("CI-only regression JSON keeps conclusions without inventing evidence links", async () => {
  const fixture = regressionArtifact(), requests = [];
  delete fixture.regressionSources; delete fixture.regressionEvidence;
  const get = await openRegression(fixture, requests);
  assert.match(get("detail").textContent, /已确认退化 1/);
  assert.match(get("detail").textContent, /来源归档缺失或未通过关联检查/);
  assert.match(get("detail").textContent, /基线原评测不可用/);
  assert.equal(descendants(get("detail"), "button").length, 0);
  assert.equal(requests.filter((path) => path.startsWith("/api/document?")).length, 1);
});

test("partly available regression evidence keeps only the independently approved actions", async () => {
  const fixture = regressionArtifact();
  delete fixture.regressionEvidence[0].baseline.evaluationId;
  fixture.regressionEvidence[0].baseline.reason = "原评测文件缺失；其余关联仍可用。";
  fixture.regressionEvidence[0].candidate = { status: "unavailable", reasonCode: "evidence_identity_mismatch" };
  const get = await openRegression(fixture), scope = descendants(section(get, "逐样本基线回归对照"), "article")[0];
  assert.equal(findButton(scope, "基线原评测"), null);
  assert.ok(findButton(scope, "基线证据"));
  assert.ok(findButton(scope, "基线轨迹"));
  assert.equal(findButton(scope, "候选原评测"), null);
  assert.equal(findButton(scope, "候选证据"), null);
  assert.equal(findButton(scope, "候选轨迹"), null);
  assert.match(scope.textContent, /原评测文件缺失/);
  assert.match(scope.textContent, /evidence_identity_mismatch/);
});

test("regression input errors and missing counters never become normal incomplete comparisons or zeros", async () => {
  const fixture = regressionArtifact();
  fixture.data = { regressionComparisonFormatVersion: 1, status: "error", exitCode: 2, outcome: "unevaluable", modelCalled: false,
    error: "<img src=x onerror=alert(1)>" };
  const get = await openRegression(fixture);
  assert.match(section(get, "比较门禁与覆盖").textContent, /比较输入或输出错误：<img/);
  assert.match(get("detail").textContent, /可比 \/ 样本键并集 缺失 \/ 缺失/);
  assert.match(get("detail").textContent, /已确认退化 缺失/);
  assert.match(get("detail").textContent, /逐样本配对明细缺失/);
  assert.equal(descendants(get("detail"), "button").length, 0);
  assert.equal(descendants(get("detail"), "img").length, 0);
  const normal = await openRegression(regressionArtifact());
  assert.doesNotMatch(section(normal, "比较门禁与覆盖").textContent, /比较输入或输出错误/);
});

test("regression metadata and unknown enums remain literal text without inherited-name translation", async () => {
  const fixture = regressionArtifact(), attack = '<img src=x onerror="alert(1)">';
  fixture.data.baseline.experimentId = attack;
  fixture.data.baseline.planVerification.status = "__proto__";
  fixture.data.samples[0].caseEntryId = attack;
  fixture.data.samples[0].change = "__proto__";
  fixture.data.samples[0].reasons = [attack, { toString: null, valueOf: null }];
  fixture.data.samples[0].candidate.outcome = { toString: null, valueOf: null };
  fixture.data.samples[0].candidate.saved.outcome = "__proto__";
  fixture.data.counts.compared = "1";
  fixture.data.counts.total = -1;
  fixture.data.configurationChanges[0].field = attack;
  fixture.data.outcome = "__proto__";
  const get = await openRegression(fixture);
  assert.ok(literalText(get("detail")).includes(attack));
  assert.match(get("detail").textContent, /__proto__/);
  assert.match(get("detail").textContent, /\{"toString":null,"valueOf":null\}/);
  assert.match(get("detail").textContent, /可比 \/ 样本键并集 缺失 \/ 缺失/);
  assert.equal(descendants(get("detail"), "img").length, 0);
  assert.equal(descendants(get("detail"), "script").length, 0);
  get("back").trigger("click");
  assert.match(get("catalog").textContent, /__proto__/);
});

test("regression limitations preserve malformed saved values without interrupting document rendering", async () => {
  const fixture = regressionArtifact(), attack = '<img src=x onerror="alert(1)">';
  fixture.data.limitations = [attack, null, { toString: null, valueOf: null }];
  const get = await openRegression(fixture);
  assert.equal(get("message").textContent, "");
  assert.match(section(get, "解释边界").textContent, /缺失/);
  assert.match(section(get, "解释边界").textContent, /\{"toString":null,"valueOf":null\}/);
  assert.ok(literalText(get("detail")).includes(attack));
  assert.equal(descendants(get("detail"), "img").length, 0);
  assert.ok(descendants(get("detail"), "summary").some((item) => item.textContent === "查看保存的完整 JSON"));
});

test("regression side evaluations reuse their own precise assertion event locators", async () => {
  for (const side of ["baseline", "candidate"]) {
    const fixture = regressionArtifact(1), requests = [], evaluation = diagnosticResult();
    evaluation.assertionTrace = { id: `runs:${side}/actual-trace.jsonl`, runId: `${side}-run`, sessionId: `${side}-session` };
    const get = await openRegression((path) => {
      const query = new URLSearchParams(path.split("?")[1]);
      if (query.get("id") === "runs:regression.json") return fixture;
      if (query.has("seq")) return { kind: "trace", links: [], offset: 0, nextOffset: null, focus: { seq: 109, line: 9 },
        rows: [{ line: 9, data: { event: { seq: 109, type: "assistant/message" } } }] };
      return evaluation;
    }, requests);
    findButton(get("detail"), side === "baseline" ? "基线原评测" : "候选原评测").trigger("click"); await new Promise(setImmediate);
    findButton(get("detail"), "最终答案 · seq 109").trigger("click"); await new Promise(setImmediate);
    const query = new URLSearchParams(requests.at(-1).split("?")[1]);
    assert.equal(query.get("id"), evaluation.assertionTrace.id);
    assert.equal(query.get("runId"), `${side}-run`);
    assert.equal(query.get("sessionId"), `${side}-session`);
    assert.equal(query.get("seq"), "109");
    assert.match(get("detail").textContent, /已定位 seq 109/);
  }
});
