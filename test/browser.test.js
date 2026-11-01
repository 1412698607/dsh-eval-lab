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

test("assertion cards prioritize saved failures, compare frozen expectations and preserve the raw verdict", async () => {
  const get = await openDiagnostic(diagnosticResult());
  const panel = section(get, "断言诊断 · 失败优先"), cards = descendants(panel, "article");
  assert.match(cards[0].textContent, /^answer 未通过/);
  assert.match(cards[1].textContent, /^end 通过/);
  assert.match(cards[0].textContent, /core-current/);
  assert.match(cards[0].textContent, /\*\*core-current\*\*/);
  assert.equal(descendants(cards[0], "mark").find((item) => item.className === "actual-difference").textContent, "**core-current**");
  assert.ok(findButton(cards[0], "最终答案 · seq 109"));
  assert.ok(descendants(get("detail"), "h2").some((item) => item.textContent === "断言明细"));
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
