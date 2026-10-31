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
      return { ok: true, json: async () => path.startsWith("/api/catalog") ? { items, warnings: [], truncated: false } : artifact };
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
