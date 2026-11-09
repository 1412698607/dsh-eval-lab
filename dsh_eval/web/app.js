"use strict";

const $ = (id) => document.getElementById(id);
const categories = [
  ["workflow_demo", "工作流演示", "▷"],
  ["experiment", "实验", "◫"], ["experiment_resume", "实验续跑", "↻"], ["report", "配置报告", "▤"],
  ["assertion_comparison", "断言对照", "⇄"],
  ["experiment_assertion_preview", "实验规则预览", "◈"],
  ["batch", "批次", "☷"], ["batch_resume", "批次续跑", "↻"],
  ["evaluation", "逐次结果", "◷"], ["case", "用例库", "◇"],
];
const words = { passed: "通过", failed: "未通过", unevaluable: "无法评测", completed: "已完成", running: "进行中",
  stopped: "已停止", interrupted: "已中断", error: "出错", finished: "已结束", skipped: "已跳过", generated: "已生成",
  complete: "完整", invalid: "无效", unverified: "未核验", not_run: "未执行", insufficient_evidence: "证据不足",
  timed_out: "超时", cancelled: "已取消", runtime_error: "运行错误", unknown: "未知", live: "真实运行声明",
  synthetic: "合成声明", matched: "匹配", mismatched: "不匹配", verified: "复验已处理", rejected: "关联被拒绝", unavailable: "不可用",
  reused: "历史复用", new: "本次新增", compared: "已对照", inconclusive: "无法完成对照",
  passToFail: "通过转未通过", failToPass: "未通过转通过", unchangedPassed: "仍通过", unchangedFailed: "仍未通过" };
const metricNames = { modelCalls: "已结算模型调用", toolCalls: "工具调用", inputTokens: "输入 token", outputTokens: "输出 token",
  totalTokens: "总 token", elapsedSeconds: "运行耗时（秒）", cost: "费用" };
let token = new URLSearchParams(location.hash.slice(1)).get("token");
try {
  if (token) sessionStorage.setItem("dsh-viewer-token", token);
  else token = sessionStorage.getItem("dsh-viewer-token");
} catch { /* The startup fragment still works when browser storage is unavailable. */ }
let catalog = [], category = "experiment", currentId = null, stack = [], requestSequence = 0;

function node(tag, text, className) {
  const result = document.createElement(tag);
  if (text !== undefined && text !== null) result.textContent = String(text);
  if (className) result.className = className;
  return result;
}
function append(parent, ...children) { parent.append(...children); return parent; }
function display(value) { return value === null || value === undefined ? "缺失" : (words[value] || String(value)); }
function number(value) { return typeof value === "number" && Number.isFinite(value) ? String(Number(value.toPrecision(6))) : "缺失"; }
function badge(value) {
  const style = ["passed", "completed", "complete", "matched"].includes(value) ? "good"
    : ["failed", "invalid", "runtime_error", "mismatched", "rejected", "error"].includes(value) ? "bad"
      : ["unevaluable", "cancelled", "timed_out", "unavailable"].includes(value) ? "warn" : "";
  return node("span", display(value), "badge " + style);
}
function button(text, action, className = "link") {
  const result = node("button", text, className);
  result.type = "button";
  result.addEventListener("click", action);
  return result;
}
function json(value) { return node("pre", JSON.stringify(value, null, 2)); }
function panel(title, content) { return append(node("section", null, "panel padded"), node("h2", title), content); }
function table(headers, rows) {
  const result = node("table"), head = node("tr");
  headers.forEach((text) => head.append(node("th", text)));
  result.append(append(node("thead"), head));
  const body = node("tbody");
  rows.forEach((cells) => {
    const row = node("tr");
    cells.forEach((value) => row.append(append(node("td"), value instanceof Node ? value : node("span", display(value)))));
    body.append(row);
  });
  result.append(body);
  return result;
}
function date(value) {
  if (!value) return "时间缺失";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? String(value) : parsed.toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
}
async function api(path) {
  const response = await fetch(path, { headers: { Authorization: "Bearer " + (token || "") }, cache: "no-store" });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "无法读取文件");
  return result;
}
function message(text) { $("message").replaceChildren(text ? node("div", text, "error") : document.createDocumentFragment()); }
function navigation() {
  $("navigation").replaceChildren(...categories.map(([kind, title, icon]) => {
    const result = button("", () => select(kind), kind === category ? "active" : "");
    result.setAttribute("aria-current", kind === category ? "page" : "false");
    return append(result, node("span", icon), node("span", title), node("span", catalog.filter((item) => item.kind === kind).length, "nav-count"));
  }));
}
function select(kind) {
  requestSequence++;
  category = kind;
  currentId = null;
  stack = [];
  $("search").value = "";
  $("outcome").value = "";
  $("source").value = "";
  const title = categories.find((item) => item[0] === kind)[1];
  $("title").textContent = title;
  $("section-label").textContent = title;
  $("detail-view").hidden = true;
  $("catalog-view").hidden = false;
  navigation();
  renderCatalog();
}
function renderCatalog() {
  const query = $("search").value.toLocaleLowerCase(), outcome = $("outcome").value, source = $("source").value;
  const items = catalog.filter((item) => (item.kind === category || item.kind === "unknown")
    && (!outcome || item.outcome === outcome || (!item.outcome && item.outcomes?.[outcome] > 0))
    && (!source || item.sources?.includes(source) || (source === "unknown" && !item.sources?.length))
    && (String(item.title || "") + " " + item.path).toLocaleLowerCase().includes(query));
  $("count").textContent = items.length + " 项";
  if (!items.length) {
    $("catalog").replaceChildren(append(node("div", null, "empty"), node("strong", "暂无匹配记录"), node("span", "已有文件会在刷新后显示；可切换分类或调整筛选。")));
    return;
  }
  $("catalog").replaceChildren(table(["名称 / 标识", "任务结论", "状态", "来源声明", "保存时间"], items.map((item) => [
    append(node("div"), button(item.title || item.path, () => openDocument(item.id)), node("div", item.path, "subtext"), ...(item.error ? [node("div", item.error, "error")] : [])),
    item.kind === "assertion_comparison" ? node("span", `${display(item.baselineOutcome)} → ${display(item.candidateOutcome)}`)
      : item.kind === "experiment_assertion_preview" ? node("span", `可对照 ${number(item.previewSummary?.comparedSamples)} / ${number(item.previewSummary?.plannedSamples)} · 无法对照 ${number(item.previewSummary?.inconclusive)}`)
      : item.kind === "report" && item.outcomes ? node("span", `通过 ${item.outcomes.passed ?? "缺失"} · 未通过 ${item.outcomes.failed ?? "缺失"} · 无法评测 ${item.outcomes.unevaluable ?? "缺失"}`)
      : item.kind === "case" ? node("span", "用例定义", "subtext") : badge(item.outcome),
    item.kind === "case" ? "—" : badge(item.status), item.kind === "case" ? "—" : item.sources?.length ? item.sources.map(display).join("、") : "缺失", item.kind === "case" ? "—" : date(item.time),
  ])));
}
function cards(items) {
  return append(node("div", null, "cards"), ...items.map(([label, value, note]) => append(node("div", null, "card"),
    node("div", label, "label"), node("div", value, "value"), node("div", note || "", "subtext"))));
}
function rate(value) {
  return value && value.value !== null && value.value !== undefined ? (value.value * 100).toFixed(1) + "%" : "缺失";
}
function countRate(value) { return value ? `${value.numerator} / ${value.denominator}` : "缺失"; }
function intervalCell(value, proportion = false) {
  if (!value) return node("span", "未保存区间", "subtext");
  const labels = { no_evaluable_samples: "没有可评测样本", no_evaluable_pairs: "没有共同可评测配对",
    no_metric_pairs: "没有完整指标配对", insufficient_pairs: "不足两对", zero_observed_variance: "观察方差为零，不输出零宽区间",
    numeric_unavailable: "数值不可用", precision_loss: "数值精度不足", same_configuration: "配置相同",
    small_sample: "小样本", incomplete_coverage: "覆盖不完整", conservative_bound: "保守界限",
    normal_difference_assumption: "需差值近似正态" };
  const label = (key) => Object.hasOwn(labels, key) ? labels[key] : String(key);
  const format = (item) => typeof item === "number" && Number.isFinite(item)
    ? proportion ? `${(item * 100).toFixed(2)}%` : number(item) : "缺失";
  const level = typeof value.confidenceLevel === "number" && Number.isFinite(value.confidenceLevel)
    && value.confidenceLevel > 0 && value.confidenceLevel < 1 ? number(value.confidenceLevel * 100) : "缺失";
  const available = value.status === "available" && [value.estimate, value.lower, value.upper]
    .every((item) => typeof item === "number" && Number.isFinite(item)) && value.lower <= value.upper && level !== "缺失";
  const text = available ? `${format(value.estimate)} [${format(value.lower)}, ${format(value.upper)}]`
    : `区间不可用：${value.reason ? label(value.reason) : "区间字段缺失"}`;
  return append(node("div"), node("span", text), node("div", `${level}% · n=${number(value.n)} · ${value.method ?? "方法缺失"}`, "subtext"),
    node("div", (Array.isArray(value.warnings) ? value.warnings : []).map(label).join("；"), "subtext"));
}
function summary(data) {
  return cards([["原计划样本", data.planned, `已尝试 ${data.attempted} · 已结束 ${data.finished} · 跳过 ${data.skipped}`],
    ["全尝试通过比例", rate(data.attemptedPassRate), countRate(data.attemptedPassRate)],
    ["可评测通过比例", rate(data.evaluablePassRate), countRate(data.evaluablePassRate)],
    ["可评测覆盖", rate(data.evaluableCoverage), countRate(data.evaluableCoverage)]]);
}
function scheduling(data) {
  const reasons = { stop_after: "达到任务数阈值", stop_after_tokens: "达到 token 阈值", token_usage_unavailable: "token 用量不可用",
    failure_policy: "失败策略", cleanup_unconfirmed: "清理未确认", user_interrupt: "用户中断", runner_error: "任务运行错误" };
  const reason = data.stopReason === undefined ? "缺失" : data.stopReason === null
    ? (data.status === "completed" ? "未触发" : "无已保存停止原因")
    : Object.hasOwn(reasons, data.stopReason) ? `${reasons[data.stopReason]}（${data.stopReason}）` : String(data.stopReason);
  const limit = (value) => value === null ? "未设置" : number(value);
  return panel("调度与停止", append(node("div"), table(["项目", "保存值"], [
    ["调度状态", badge(data.status)], ["停止原因", node("span", reason)],
    ["任务数停止阈值", limit(data.stopAfter)], ["本轮 token 停止阈值", limit(data.stopAfterTokens)],
    ["本轮已观测 token", number(data.tokenUsage?.observedTotal)],
    ["本轮 token 观测 / 缺失样本", `${number(data.tokenUsage?.observedSamples)} / ${number(data.tokenUsage?.missingSamples)}`],
  ]), node("p", "阈值和用量只计本轮新增任务，不含历史复用；阈值在任务结束后检查，当前任务可超过阈值，不是任务内 token 或费用硬限额。", "subtext"),
  node("p", "以上为保存值，阈值已设置不代表已经触发。旧文件缺失的字段不从汇总推算；浏览不会重新评测或启动任务。", "subtext")));
}
function continuation(data, kind) {
  const batch = kind === "batch_resume";
  const identity = [["续跑 ID", data.resumeId], ["任务结论", badge(data.outcome)], ["来源批次 ID", data.sourceBatchId]];
  if (kind === "experiment_resume") identity.push(["原实验 ID", data.sourceExperimentId], ["上轮续跑 ID", data.sourceResumeId],
    ["启动时原计划", number(data.counts?.original)], ["启动时历史复用", number(data.counts?.reused)],
    ["启动时本轮计划", number(data.counts?.newSamples)], ["启动时阻断", number(data.counts?.blocked)]);
  const fresh = data.newlyExecutedSummary, combined = data.combinedSummary;
  const rows = [["计划样本", "planned"], ["已尝试", "attempted"], ["已结束", "finished"], ["跳过", "skipped"], ["错误", "errors"]]
    .map(([label, key]) => [label, number(fresh?.[key]), number(combined?.[key])]);
  for (const [label, key] of [["通过", "passed"], ["未通过", "failed"], ["无法评测", "unevaluable"]]) {
    rows.push([label, number(fresh?.outcomes?.[key]), number(combined?.outcomes?.[key])]);
  }
  for (const [label, key] of [["全尝试通过", "attemptedPassRate"], ["可评测通过", "evaluablePassRate"], ["可评测覆盖", "evaluableCoverage"]]) {
    rows.push([label, countRate(fresh?.[key]), countRate(combined?.[key])]);
  }
  const scope = batch ? "批次续跑汇总只覆盖来源批次计划，包含其中的复用项，不代表整个原实验。"
    : "启动计划反映预检时分类，不等于本轮实际执行数或当前剩余数。";
  return [panel("续跑身份与启动计划", append(node("div"), table(["项目", "保存值"], identity),
    node("p", scope + "结果和用量只显示本文件保存的汇总，缺失不从原实验补算。", "subtext"))),
  panel("续跑保存结果汇总", table(["项目", "本轮新增", batch ? "来源批次计划（含复用）" : "全部原计划（含历史）"], rows)),
  panel("续跑保存用量", table(["观测指标", "本轮新增累计", "新增观测 / 缺失", batch ? "来源批次累计" : "全部累计（含历史）", "合并观测 / 缺失"],
    Object.entries(metricNames).map(([key, label]) => {
      const recent = fresh?.metrics?.[key], all = combined?.metrics?.[key];
      return [label, number(recent?.observedTotal), `${number(recent?.observedSamples)} / ${number(recent?.missingSamples)}`,
        number(all?.observedTotal), `${number(all?.observedSamples)} / ${number(all?.missingSamples)}`];
    })))];
}
function metricsTable(metrics, aggregate = false, synthetic = false) {
  if (!metrics) return node("p", "指标缺失");
  return table(aggregate ? ["观测指标", "已观测总和", "已观测均值", "观测 / 缺失样本", "观测范围"] : ["观测指标", "已观测值"],
    Object.entries(metricNames).map(([key, label]) => {
      if (synthetic && key === "modelCalls") label = "合成模型事件";
      const value = metrics[key];
      if (!aggregate) return [label, number(value)];
      return [append(node("div"), node("span", label), ...(value?.reason ? [node("div", value.reason, "subtext")] : [])),
        number(value?.observedTotal), number(value?.observedMean), `${value?.observedSamples ?? "缺失"} / ${value?.missingSamples ?? "缺失"}`,
        number(value?.observedMin) + " .. " + number(value?.observedMax)];
    }));
}
function sampleTable(data, links) {
  const rows = data.samples || data.entries;
  if (!Array.isArray(rows)) return;
  const resumed = [2, 3].includes(data.comparisonReportFormatVersion);
  const body = rows.map((row, index) => {
    const link = links.find((item) => item.label === `${index + 1} / evaluationPath` && item.id);
    const name = row.sampleId || row.entryId || row.caseRunId;
    const identity = append(node("div"), link ? button(name, () => openDocument(link.id)) : node("span", name),
      node("div", `${row.caseId || ""} · 重复 ${row.repeatIndex ?? "—"}`, "subtext"), badge(row.status));
    const origin = append(node("div"), node("div", display(row.executionOrigin || "unknown")),
      node("div", row.sourceBatchId ?? "批次缺失", "subtext"));
    if (resumed) {
      const batch = links.find((item) => item.label === `${index + 1} / sourceBatchResult` && item.id);
      if (batch) origin.append(button("查看来源批次", () => openDocument(batch.id)));
    }
    const config = append(node("div"), node("div", row.configurationId || row.requestedConfiguration?.model || "缺失"),
      node("div", `请求 ${row.requestedConfiguration?.provider || "缺失"} / ${row.requestedConfiguration?.model || "缺失"}`, "subtext"), badge(row.configurationMatch),
      node("div", `实际 ${row.configuration?.provider || "缺失"} / ${row.configuration?.model || "缺失"}`, "subtext"));
    const result = append(node("div"), badge(row.outcome));
    if (row.verification) result.append(node("div", display(row.verification), "subtext"));
    if (row.changedFields?.length) result.append(node("div", "复验变化：" + row.changedFields.join("、"), "subtext"));
    if (row.saved) result.append(node("div", "原保存结论：" + display(row.saved.outcome), "subtext"));
    const error = typeof row.error === "string" ? row.error : [row.error?.type, row.error?.message].filter(Boolean).join(": ");
    if (row.reasons?.length || row.error) result.append(node("div", error || row.reasons?.join("；") || "未知错误", "subtext"));
    return [identity, ...(resumed ? [origin] : []), config, display(row.source), badge(row.executionStatus), badge(row.recordingOutcome), badge(row.assertionOutcome), result];
  });
  return panel("逐次结果", table(["样本", ...(resumed ? ["执行归属"] : []), "请求 / 实际配置", "来源声明", "执行", "录制", "断言", "任务结论"], body));
}
function evidence(links) {
  if (!links.length) return;
  const names = { casePath: "用例快照", evidencePath: "证据清单", evaluationPath: "评测结果", runtimeReport: "执行事实",
    manifestPath: "输入清单", batchResultPath: "批次结果", sourceExperimentResult: "原实验", sourceEvidencePath: "原证据", association: "本次运行",
    sourceResumeResult: "原实验续跑结果", sourceBatchResult: "来源批次", batchResumeResult: "批次续跑结果",
    batchResumeResultPath: "下游批次续跑结果", resumeVerification: "保存的续跑关联", resultPath: "实验续跑结果" };
  function label(link) {
    if (link.label === "batchBinding / resultPath") return "执行批次检查点（保存关联）";
    return link.label.split(" / ").map((part) => names[part] || (part.endsWith(".jsonl") ? "事件轨迹" : part.endsWith(".status.json")
      ? "录制状态" : part === "run.json" ? "录制信息" : part === "runDir" ? "录制" : part)).join(" / ");
  }
  return panel("关联文件与原始证据", append(node("div", null, "evidence"), ...links.map((link) => link.id
    ? button(label(link), () => openDocument(link.id))
    : node("span", label(link) + "（缺失或超出浏览目录）", "subtext"))));
}
function textDifference(expected, actual) {
  const left = Array.from(expected), right = Array.from(actual);
  let start = 0, end = 0;
  while (start < Math.min(left.length, right.length) && left[start] === right[start]) start++;
  while (end < Math.min(left.length, right.length) - start && left[left.length - end - 1] === right[right.length - end - 1]) end++;
  const render = (chars, className) => {
    const text = node("pre", null, "assertion-value");
    text.append(node("span", chars.slice(0, start).join("")));
    if (chars.length - end > start) text.append(node("mark", chars.slice(start, chars.length - end).join(""), className));
    text.append(node("span", end ? chars.slice(-end).join("") : ""));
    return text;
  };
  return [render(left, "expected-difference"), render(right, "actual-difference")];
}
function assertionEvidence(row, assertionTrace) {
  const locations = Array.isArray(row.evidence) ? row.evidence : [row.evidence];
  const jumps = node("div", null, "evidence"), seen = new Set();
  for (const location of locations) {
    if (!location || typeof location !== "object") continue;
    for (const [key, label] of [["callSeq", "工具调用"], ["resultSeq", "工具返回"], ["afterResultSeq", "前置工具返回"], ["answerSeq", "最终答案"], ["endSeq", "任务结束"]]) {
      const seq = location[key], identity = `${key}:${seq}`;
      if (!Number.isSafeInteger(seq) || seq < 0 || seen.has(identity)) continue;
      seen.add(identity);
      const title = `${label} · seq ${seq}`;
      jumps.append(assertionTrace?.id ? button(title, () => openDocument(assertionTrace.id, 0, true, { ...assertionTrace, seq }))
        : node("span", title + "（关联轨迹不可用）", "subtext"));
    }
  }
  if (!seen.size) jumps.append(node("span", ["tool_forbidden", "tool_call_count"].includes(row.type) && row.actual === 0
    ? "匹配调用为 0，没有对应调用事件。" : "未保存可定位的事件序号。", "subtext"));
  return jumps;
}
const assertionReasonNames = {
  matched: "匹配通过", environment_snapshot_missing: "缺少环境快照", environment_files_mismatch: "最终文件集合不符",
  final_text_mismatch: "最终回复不符", turn_end_mismatch: "结束原因不符", forbidden_tool_observed: "发现禁止的工具调用",
  tool_call_count_out_of_bounds: "工具调用次数超出范围", dependency_not_passed: "前置断言未通过",
  tool_evidence_missing: "缺少匹配的工具调用与返回", tool_result_mismatch: "工具返回不符", tool_order_mismatch: "工具顺序不符",
  tool_result_and_order_mismatch: "候选证据分别存在返回或顺序不符", recording_not_complete: "录制未通过完整性检查",
  execution_not_completed: "执行未正常完成", evaluation_evidence_invalid: "评测证据无效",
};
const assertionGlobalGateCodes = ["recording_not_complete", "execution_not_completed", "evaluation_evidence_invalid"];
function structuredAssertionDiagnostics(data) {
  const saved = data.assertionDiagnostics;
  if (saved === undefined || saved === null) return { rows: [], unavailable: "本结果未保存结构化断言诊断；不从原因文字推断依赖。" };
  if (saved.assertionDiagnosticsFormatVersion !== 1) return { rows: [], unavailable: "结构化断言诊断版本不支持；原判定与证据保持显示。" };
  if (!Array.isArray(saved.results)) return { rows: [], unavailable: "结构化断言诊断明细不可用；原判定与证据保持显示。" };
  const results = Array.isArray(data.assertions?.results) ? data.assertions.results : [];
  let rows = saved.results.filter((row) => row && typeof row === "object" && typeof row.id === "string" && typeof row.type === "string"
    && typeof row.reasonCode === "string" && (!Object.hasOwn(row, "after") || typeof row.after === "string")
    && (!Object.hasOwn(row, "blockedBy") || Array.isArray(row.blockedBy) && row.blockedBy.every((id) => typeof id === "string"))
    && (!Object.hasOwn(row, "observedMatches") || Array.isArray(row.observedMatches))
    && saved.results.filter((item) => item?.id === row.id).length === 1
    && results.filter((item) => item?.id === row.id).length === 1
    && results.some((item) => item?.id === row.id && item?.type === row.type && item?.outcome === row.outcome));
  const positions = new Map(results.map((row, index) => [row?.id, index]));
  rows.sort((left, right) => positions.get(left.id) - positions.get(right.id));
  const byId = new Map(rows.map((row) => [row.id, row]));
  rows = rows.map((row) => {
    let current = row;
    const seen = new Set();
    let invalid = false;
    while (current && !invalid) {
      const blockers = current.blockedBy ?? [];
      if (current.reasonCode === "dependency_not_passed") {
        const predecessor = blockers.length === 1 ? byId.get(blockers[0]) : null;
        if (blockers.length !== 1 || blockers[0] !== current.after || !predecessor || predecessor.outcome === "passed"
          || current.outcome !== (predecessor.outcome === "failed" ? "failed" : "insufficient_evidence")) invalid = true;
      } else if (blockers.length) invalid = true;
      if (!current.after) break;
      if (seen.has(current.id) || !byId.has(current.after)) invalid = true;
      seen.add(current.id);
      current = byId.get(current.after);
    }
    return { ...row, ...(invalid ? { relationshipUnavailable: true } : {}) };
  });
  return { rows, ...(rows.length === saved.results.length && rows.length === results.length ? {} : { warning: "结构化诊断不完整，或部分诊断无法唯一关联保存的断言结果；未补全缺失原因与依赖。" }),
    ...(rows.some((row) => !Object.hasOwn(assertionReasonNames, row.reasonCode)) ? { reasonWarning: "未知原因码只显示保存原值，不据此识别问题源头。" } : {}),
    ...(rows.some((row) => row.relationshipUnavailable) ? { relationshipWarning: "依赖结构存在缺失引用、环、非直接阻断或与保存判定矛盾的阻断；相关项只展示保存字段，不据此识别问题源头。" } : {}) };
}
function diagnosticReason(row) {
  if (row.relationshipUnavailable && row.reasonCode === "dependency_not_passed") return "保存原因码 dependency_not_passed（依赖关系不可用）";
  return `${Object.hasOwn(assertionReasonNames, row.reasonCode) ? assertionReasonNames[row.reasonCode] : "未识别的原因码"}（${row.reasonCode}）`;
}
function independentAssertionProblems(rows) {
  return rows.filter((row) => ["failed", "insufficient_evidence"].includes(row.outcome)
    && !row.blockedBy?.length && Object.hasOwn(assertionReasonNames, row.reasonCode)
    && !["matched", "dependency_not_passed", ...assertionGlobalGateCodes].includes(row.reasonCode) && !row.relationshipUnavailable);
}
function observedAssertionMatches(row, assertionTrace) {
  if (row.relationshipUnavailable || row.reasonCode !== "dependency_not_passed" || !row.blockedBy?.length || !Array.isArray(row.observedMatches)) return null;
  const body = append(node("div"), node("p", "实际发生的匹配事件仅供查看：前置断言未通过，这些事件未计为本项通过证据。", "notice"));
  body.append(row.observedMatches.length ? assertionEvidence({ evidence: row.observedMatches }, assertionTrace)
    : node("p", "未观察到符合本项工具与返回要求的事件。", "subtext"));
  return body;
}
function assertionDependencies(documentData) {
  const { data, assertionTrace } = documentData, saved = structuredAssertionDiagnostics(data);
  const body = node("div");
  if (saved.unavailable) return panel("断言原因与依赖", node("p", saved.unavailable, "subtext"));
  body.append(node("p", "原因来自评分分支保存的结构化字段。前置与阻断只显示直接关系；事件定位不会改变保存的判定。问题列表包括必需项与诊断项，诊断失败不会单独使任务失败。", "subtext"));
  if (saved.warning) body.append(node("p", saved.warning, "notice"));
  if (saved.reasonWarning) body.append(node("p", saved.reasonWarning, "notice"));
  if (saved.relationshipWarning) body.append(node("p", saved.relationshipWarning, "notice"));
  const gates = [...new Set(saved.rows.filter((row) => assertionGlobalGateCodes.includes(row.reasonCode)).map((row) => row.reasonCode))];
  if (gates.length) body.append(node("p", "全局门禁未通过，相关断言未执行逐项评分；这些原因不作为独立步骤缺证源头。 · "
    + gates.map((code) => diagnosticReason({ reasonCode: code })).join("；"), "notice"));
  const roots = independentAssertionProblems(saved.rows), first = roots.find((row) => row.outcome === "insufficient_evidence");
  const results = Array.isArray(data.assertions?.results) ? data.assertions.results : [];
  const roleName = (row) => {
    const role = results.find((item) => item?.id === row.id && item?.type === row.type)?.role ?? "required";
    return role === "diagnostic" ? "诊断项" : role === "required" ? "必需项" : "未知角色";
  };
  body.append(node("p", "独立问题源头（按保存的断言顺序） · " + (roots.map((row) => `${row.id}（${roleName(row)}）`).join("、") || "无")));
  if (first) body.append(append(node("p", null, "notice"), node("strong", "首个缺证步骤 · " + first.id), node("span", " · " + diagnosticReason(first))));
  body.append(table(["断言 / 角色", "保存判定", "结构化原因", "声明的直接前置", "阻断前置", "已评分证据 / 实际观察"], saved.rows.map((row) => {
    const legacy = results.find((item) => item?.id === row.id && item?.type === row.type);
    const observed = observedAssertionMatches(row, assertionTrace);
    return [append(node("div"), node("span", row.id), node("p", roleName(row), "subtext")), badge(row.outcome), diagnosticReason(row),
      append(node("div"), node("span", row.after ?? "无"), ...(row.relationshipUnavailable ? [node("p", "依赖关系不可用", "subtext")] : [])), row.blockedBy?.join("、") || "无",
      observed || assertionEvidence(legacy || {}, assertionTrace)];
  })));
  if (!saved.rows.length) body.append(node("p", "没有可关联的结构化诊断明细。", "subtext"));
  return panel("断言原因与依赖", body);
}
function assertionCards(documentData) {
  const { data, assertionTrace } = documentData;
  const results = Array.isArray(data.assertions?.results) ? data.assertions.results : [];
  const definitions = Array.isArray(data.case?.assertions) ? data.case.assertions : [];
  const body = node("div", null, "assertion-list");
  body.append(node("p", "显示保存的断言结论与本结果内嵌的用例快照。浏览不会重新评测；定位到事件也不代表证据已经复验。", "subtext"));
  const hasRoles = results.some((row) => row && Object.hasOwn(row, "role"));
  const diagnosticRows = structuredAssertionDiagnostics(data).rows;
  const firstMissing = independentAssertionProblems(diagnosticRows).find((row) => row.outcome === "insufficient_evidence");
  if (hasRoles) body.append(node("p", "断言汇总只计入必需项。诊断项单独记录，诊断失败仍显示在这里。", "subtext"));
  if (data.assertions?.reason) body.append(node("p", data.assertions.reason, "error"));
  if (!results.length) body.append(node("p", "没有保存逐条断言结果。", "subtext"));
  const ordered = results.filter((row) => row && typeof row === "object")
    .sort((a, b) => Number(b.outcome === "failed") - Number(a.outcome === "failed"));
  for (const row of ordered) {
    const matches = definitions.filter((item) => item && typeof row.id === "string" && item.id === row.id && item.type === row.type);
    const definition = matches.length === 1 ? matches[0] : null;
    const confirmationToken = row.type === "final_text" && row.match === "confirmation_token";
    const behavior = ["tool_forbidden", "tool_call_count"].includes(row.type);
    const expected = ["final_text", "environment_files"].includes(row.type) ? definition?.equals : row.type === "turn_end" ? definition?.reason
      : behavior && definition ? { tool: definition.tool, arguments: definition.arguments ?? {},
        ...(row.type === "tool_forbidden" ? { max: 0 }
          : { ...(Object.hasOwn(definition, "min") ? { min: definition.min } : {}),
            ...(Object.hasOwn(definition, "max") ? { max: definition.max } : {}) }) }
      : row.type === "tool_result" && definition ? { tool: definition.tool, arguments: definition.arguments, result: definition.result,
        ...(definition.after ? { after: definition.after } : {}) } : undefined;
    const card = node("article", null, "assertion-card" + (row.outcome === "failed" ? " assertion-failed" : ""));
    const heading = append(node("div", null, "assertion-heading"), node("h3", row.id ?? "断言标识缺失"), badge(row.outcome), node("span", row.type, "subtext"));
    if (hasRoles) {
      const role = Object.hasOwn(row, "role") ? row.role : "required";
      const label = role === "diagnostic" ? "诊断项" : role === "required" ? "必需项" : "未知角色";
      heading.append(node("span", label, "badge"));
    }
    card.append(heading);
    const diagnostic = diagnosticRows.find((item) => item.id === row.id && item.type === row.type);
    if (diagnostic) {
      if (diagnostic.id === firstMissing?.id) card.append(node("p", "首个缺证步骤（按保存的断言顺序）", "notice"));
      card.append(node("p", "结构化原因 · " + diagnosticReason(diagnostic), "subtext"));
      if (diagnostic.relationshipUnavailable) card.append(node("p", "依赖关系不可用；只展示保存的前置与阻断字段。", "notice"));
      if (diagnostic.after) card.append(node("p", "声明的直接前置 · " + diagnostic.after, "subtext"));
      if (diagnostic.blockedBy?.length) card.append(node("p", (diagnostic.relationshipUnavailable ? "保存的阻断字段（关系不可用） · " : "依赖阻断 · ") + diagnostic.blockedBy.join("、"), "notice"));
      const observed = observedAssertionMatches(diagnostic, assertionTrace);
      if (observed) card.append(observed);
    }
    if (row.reason) card.append(node("p", row.reason));
    if (confirmationToken) card.append(node("p", "确认词匹配只接受一个由 A–Z 或 a–z 组成的词，忽略大小写。整词可以用 ** 或 __ 加粗，末尾允许一个英文句号，句号可放在加粗标记内或外。", "subtext"));
    if (behavior) card.append(node("p", "实际值为任务范围内匹配的工具调用次数，包括失败、未返回及最终答案后的调用；这是保存的离线评测结果，不是运行时拦截。", "subtext"));
    let values = [expected === undefined ? node("p", "期望值缺失或无法唯一匹配用例快照。", "subtext") : json(expected),
      Object.hasOwn(row, "actual") ? json(row.actual) : node("p", "未保存实际值；可通过下方证据查看原始事件。", "subtext")];
    if (typeof expected === "string" && typeof row.actual === "string") {
      if (confirmationToken) {
        values = [node("pre", expected, "assertion-value"), node("pre", row.actual, "assertion-value")];
      } else {
        values = textDifference(expected, row.actual);
        card.append(node("p", expected === row.actual ? "保存文本相同；原结论保持不变。" : "高亮首尾相同部分之间的差异；不移除 Markdown 或归一化答案。", "subtext"));
      }
      if (row.type === "final_text") card.append(node("p", "实际值为评测时保存的文本（已去除首尾空白）；原始答案见事件。", "subtext"));
    }
    card.append(append(node("div", null, "two-columns assertion-values"),
      append(node("div"), node("h3", "期望（用例快照）"), values[0]), append(node("div"), node("h3", "实际（保存值）"), values[1])));
    if (typeof expected === "string" || typeof row.actual === "string") card.append(append(node("details"),
      node("summary", "查看转义文本（区分空字符串、空格和换行）"), json({ expected, actual: row.actual })));
    card.append(assertionEvidence(row, assertionTrace));
    body.append(card);
  }
  return panel("断言诊断 · 失败优先", body);
}
function assertionComparison(documentData) {
  const { data, assertionTrace } = documentData;
  const target = node("div"), rows = Array.isArray(data.assertions) ? data.assertions : [];
  target.append(cards([["对照状态", display(data.status)], ["原任务结论", display(data.baseline?.outcome)],
    ["候选任务结论", display(data.candidate?.outcome)], ["来源声明", display(data.source)]]));
  target.append(panel("保存的对照摘要", append(node("div"),
    node("p", "读取已保存的两次离线评测。浏览不会重评。列表的任务结论筛选使用候选侧结论。", "subtext"),
    node("p", data.summary?.taskOutcomeChanged === true ? "任务总判定发生变化" : data.summary?.taskOutcomeChanged === false ? "任务总判定相同" : "总判定变化记录缺失"),
    node("p", Array.isArray(data.summary?.changedAssertionIds) ? "变化断言 · " + (data.summary.changedAssertionIds.join("、") || "无") : "变化断言记录缺失"),
    table(["规则侧", "执行", "录制", "断言汇总", "规则摘要", "原因"], [["原规则", data.baseline], ["候选规则", data.candidate]].map(([label, value]) => [
      label, display(value?.executionStatus), display(value?.recordingOutcome), display(value?.assertionOutcome),
      value?.assertionsSha256 ?? "缺失", [value?.assertionReason, ...(Array.isArray(value?.recordingReasons) ? value.recordingReasons : [])].filter(Boolean).join("；") || "无",
    ])))));
  const list = node("div", null, "assertion-list");
  let changedOnly = false;
  const toggle = button("仅看变化", () => { changedOnly = !changedOnly; render(); }, "secondary");
  const side = (label, value) => {
    if (!value) return append(node("div"), node("h3", label), node("p", "此侧无该断言", "subtext"));
    const role = value.definition?.role ?? "required";
    const match = value.definition?.type === "final_text" ? " · 匹配 " + (value.definition.match ?? "exact") : "";
    return append(node("div"), node("h3", label), badge(value.result?.outcome),
      node("p", `位置 ${value.position ?? "缺失"} · ${role === "diagnostic" ? "诊断项" : role === "required" ? "必需项" : "未知角色"}${match}`, "subtext"),
      node("h3", "规则定义"), json(value.definition), node("h3", "实际结果与证据"), json(value.result),
      assertionEvidence(value.result || {}, assertionTrace));
  };
  function render() {
    toggle.textContent = changedOnly ? "显示全部断言" : "仅看变化";
    toggle.setAttribute("aria-pressed", String(changedOnly));
    const shown = rows.filter((row) => row && typeof row === "object" && (!changedOnly ||
      row.ruleChanged === true || row.outcomeChanged === true || row.resultChanged === true || row.positionChanged === true));
    list.replaceChildren(...shown.map((row) => append(node("article", null, "assertion-card"),
      node("h3", row.id ?? "断言 ID 缺失"),
      node("p", [["ruleChanged", "规则变化"], ["outcomeChanged", "单项判定变化"], ["resultChanged", "结果明细变化"], ["positionChanged", "位置变化"]]
        .filter(([key]) => row[key] === true).map(([, label]) => label).join(" · ") || "保存记录未标记变化", "subtext"),
      append(node("div", null, "two-columns"), side("原规则", row.baseline), side("候选规则", row.candidate)))));
    if (!shown.length) list.append(node("p", changedOnly ? "没有标记为变化的断言。" : "没有保存逐项对照结果。", "subtext"));
  }
  render();
  target.append(panel("逐项规则与判定对照", append(node("div"), toggle, list)));
  return target;
}
function diagnosticSummary(data, links) {
  const value = data.summary?.diagnosticSummary;
  if (!value || typeof value !== "object") return;
  const counts = value.assertionCounts;
  const body = append(node("div"),
    node("p", "诊断项逐项统计。任务通过率仍取决于必需项；未取得复验结果的样本单列为缺失。", "subtext"),
    table(["已复验 / 缺失样本", "含诊断样本", "含诊断失败样本", "任务通过且诊断失败", "诊断通过 / 失败 / 证据不足 / 未执行"],
      [[`${number(value.observedSamples)} / ${number(value.missingSamples)}`, number(value.samplesWithDiagnostics),
        number(value.samplesWithFailures), number(value.passedSamplesWithFailures),
        ["passed", "failed", "insufficient_evidence", "not_run"].map((key) => number(counts?.[key])).join(" / ")]]));
  const rows = (Array.isArray(data.samples) ? data.samples : []).flatMap((row, index) => {
    const saved = row?.diagnosticSummary;
    if (!saved || !(saved.declaredAssertions > 0)) return [];
    const link = links.find((item) => item.label === `${index + 1} / evaluationPath` && item.id);
    const name = row.sampleId || row.caseRunId || "样本标识缺失";
    return [[link ? button(name, () => openDocument(link.id)) : node("span", name),
      display(row.outcome), ...["failedAssertionIds", "insufficientAssertionIds", "notRunAssertionIds"].map((key) =>
        Array.isArray(saved[key]) ? saved[key].join("、") || "无" : "缺失")]];
  });
  body.append(table(["样本 / 逐项复验", "任务结论", "诊断失败 ID", "证据不足 ID", "未执行 ID"], rows));
  return panel("诊断项覆盖与结果", body);
}
function experimentAssertionPreview(documentData) {
  const { data } = documentData, saved = data.summary;
  const target = node("div");
  target.append(cards([["原计划样本", number(saved?.plannedSamples)], ["可对照样本", number(saved?.comparedSamples)],
    ["无法对照样本", number(saved?.inconclusive)], ["预览状态", display(data.status)]]));
  target.append(panel("实验规则影响", append(node("div"),
    node("p", "读取保存的离线规则预览，浏览不会重评或调用模型。任务结论筛选使用候选侧结论；无法对照样本不纳入四类转移。", "subtext"),
    table(["通过 → 未通过", "未通过 → 通过", "仍通过", "仍未通过", "无法对照"],
      [["passToFail", "failToPass", "unchangedPassed", "unchangedFailed", "inconclusive"].map((key) => number(saved?.[key]))]),
    node("p", `实验 ${data.experimentId ?? "缺失"} · 模型调用 ${data.modelCalled === false ? "否" : "未知"}`, "subtext"))));
  const rows = Array.isArray(data.samples) ? data.samples : [];
  const list = node("div", null, "assertion-list");
  rows.forEach((row, index) => {
    if (!row || typeof row !== "object") return;
    const link = (Array.isArray(documentData.sampleEvidence) ? documentData.sampleEvidence : []).find((item) => item.index === index + 1);
    const card = append(node("article", null, "assertion-card"), node("h3", row.sampleId ?? "样本标识缺失"),
      node("p", `${row.caseEntryId ?? "用例缺失"} · ${row.configurationId ?? "配置缺失"} · 第 ${row.repeatIndex ?? "缺失"} 轮 · ${display(row.source)}`, "subtext"),
      node("p", `${display(row.baselineOutcome)} → ${display(row.candidateOutcome)} · ${display(row.transition)}`),
      node("p", `复验 ${display(row.verification)} · 配置 ${display(row.configurationMatch)}`, "subtext"));
    card.append(link?.id ? button("查看源证据", () => openDocument(link.id)) : node("p", "源证据缺失、身份不匹配或超出浏览目录", "subtext"));
    for (const reason of Array.isArray(row.reasons) ? row.reasons : []) card.append(node("p", reason, "error"));
    const changes = Array.isArray(row.changes) ? row.changes : [];
    card.append(node("p", "变化断言 · " + (Array.isArray(row.changedAssertionIds) ? row.changedAssertionIds.join("、") || "无" : "缺失")));
    for (const change of changes) {
      if (!change || typeof change !== "object") continue;
      const sides = ["baseline", "candidate"].map((key) => {
        const value = change[key];
        return append(node("div"), node("h3", key === "baseline" ? "原规则" : "候选规则"),
          value ? json(value) : node("p", "此侧无该断言", "subtext"),
          ...(value ? [assertionEvidence(value.result || {}, link?.assertionTrace)] : []));
      });
      card.append(append(node("details"), node("summary", change.id ?? "断言 ID 缺失"), append(node("div", null, "two-columns"), ...sides)));
    }
    list.append(card);
  });
  if (!list.children.length) list.append(node("p", "没有保存样本明细。", "subtext"));
  target.append(panel("样本结论与变化断言", list));
  return target;
}
function renderDocument(documentData) {
  const target = $("detail"), data = documentData.data, links = documentData.links;
  target.replaceChildren();
  if (documentData.kind === "trace") {
    const rows = documentData.rows.map((row) => {
      const event = row.data?.event;
      return [row.line, event?.seq ?? "缺失", event?.type || (row.error ? "无法解析 / 预览" : "原始记录"), json(row.error ? { error: row.error, preview: row.preview } : row.data)];
    });
    const traceTable = table(["行号", "事件序号", "事件", "记录内容"], rows);
    if (documentData.focus) {
      const index = documentData.rows.findIndex((row) => row.line === documentData.focus.line);
      if (index >= 0) {
        const focusedRow = traceTable.children[1].children[index];
        focusedRow.className = "focused-event";
        focusedRow.id = "focused-event";
        focusedRow.setAttribute("tabindex", "-1");
      }
      target.append(node("p", `已定位 seq ${documentData.focus.seq} · 文件第 ${documentData.focus.line} 行。这里只定位保存的关联，未重新复验证据。`, "notice"));
    }
    target.append(panel("原始事件轨迹", traceTable));
    const pagination = append(node("div", null, "pagination"), node("span", `从第 ${documentData.offset + 1} 行开始 · 本页 ${rows.length} 行`));
    if (documentData.offset > 0) pagination.append(button("上一页", () => openDocument(currentId, Math.max(0, documentData.offset - 50), false), "secondary"));
    if (documentData.nextOffset !== null) pagination.append(button("下一页", () => openDocument(currentId, documentData.nextOffset, false), "secondary"));
    target.append(pagination);
    return;
  }
  if (documentData.kind === "markdown") { target.append(panel("报告文本", node("pre", documentData.text))); return; }
  if (documentData.kind === "workflow_demo") {
    target.append(cards([["生成状态", display(data.status)], ["来源声明", display(data.source)],
      ["模型调用", data.modelCalled === false ? "否" : "未知"]]));
    target.append(panel("按顺序浏览三个场景", table(["顺序", "场景", "任务 / 对照结论", "说明"],
      (Array.isArray(data.scenarios) ? data.scenarios : []).map((row, index) => {
        const link = links.find((item) => item.id && (item.label === `场景 ${index + 1} / evaluationPath` || item.label === `场景 ${index + 1} / previewPath`));
        return [index + 1, link ? button(row.title || row.id || "场景", () => openDocument(link.id)) : node("span", row.title || row.id || "场景"),
          display(row.outcome), append(node("div"), node("p", row.description), ...(!link ? [node("p", "结果缺失或超出浏览目录", "subtext")] : []))];
      }))));
    const files = evidence(links);
    if (files) target.append(files);
    target.append(append(node("details", null, "panel padded"), node("summary", "查看保存的完整 JSON"), json(data)));
    return;
  }
  if (documentData.kind === "experiment_assertion_preview") {
    target.append(...experimentAssertionPreview(documentData).children);
    const files = evidence(links);
    if (files) target.append(files);
    target.append(append(node("details", null, "panel padded"), node("summary", "查看保存的完整 JSON"), json(data)));
    return;
  }
  if (documentData.kind === "assertion_comparison") {
    target.append(...assertionComparison(documentData).children);
    const files = evidence(links);
    if (files) target.append(files);
    target.append(append(node("details", null, "panel padded"), node("summary", "查看保存的完整 JSON"), json(data)));
    return;
  }
  const resumed = [2, 3].includes(data.comparisonReportFormatVersion);
  if (data.summary) target.append(summary(data.summary));
  if (["batch", "experiment", "batch_resume", "experiment_resume"].includes(documentData.kind)) target.append(scheduling(data));
  if (["batch_resume", "experiment_resume"].includes(documentData.kind)) target.append(...continuation(data, documentData.kind));
  if (resumed) {
    const batches = Array.isArray(data.batchIds) ? data.batchIds : [];
    const batchRows = data.comparisonReportFormatVersion === 3
      ? batches.map((id, index) => [`批次 ${index + 1} · ${index === 0 ? "原批次" : index === batches.length - 1 ? "本轮新增" : "历史续跑"}`, id])
      : [["原批次 ID", batches[0]], ["新批次 ID", batches[1]]];
    target.append(panel("续跑来源与保存的关联复核", table(["关联", "保存值"], [
      ["原实验 ID", data.experimentId], ["实验续跑 ID", data.resumeId], ...batchRows,
      ["原计划复核", display(data.planVerification?.status)], ["续跑关联复核", display(data.resumeVerification?.status)],
    ])));
    if (data.comparisonReportFormatVersion === 3 && Array.isArray(data.resumeChain)) {
      target.append(panel("连续续跑链", table(["轮次", "续跑 ID", "保存结果"], data.resumeChain.map((row, index) => {
        const link = links.find((item) => item.label === `续跑 ${index + 1} / resultPath` && item.id);
        return [index + 1, row.resumeId, link ? button("查看续跑结果", () => openDocument(link.id)) : "缺失或超出浏览目录"];
      }))));
    }
    const origins = [["历史复用", data.reusedSummary], ["本次新增", data.newlyExecutedSummary]];
    target.append(panel("历史复用与本次新增", append(node("div"),
      node("p", "历史复用的用量属于原执行；本次新增只统计新批次。以下为保存的报告，浏览不会重新复验。"),
      table(["执行归属", "计划 / 尝试 / 跳过", "全尝试通过", "可评测通过", "可评测覆盖", "来源声明 / 样本"],
        origins.map(([label, value]) => [label, `${value?.planned ?? "缺失"} / ${value?.attempted ?? "缺失"} / ${value?.skipped ?? "缺失"}`,
          countRate(value?.attemptedPassRate), countRate(value?.evaluablePassRate), countRate(value?.evaluableCoverage),
          Object.entries(value?.sourceCounts || {}).map(([source, count]) => `${display(source)} / ${count}`).join("；") || "缺失"])))));
    target.append(panel("历史与新增用量（分别统计）", table(["观测指标", "历史观测累计", "历史观测 / 缺失", "本次新增累计", "新增观测 / 缺失"],
      Object.entries(metricNames).map(([key, label]) => {
        const old = data.reusedSummary?.metrics?.[key], fresh = data.newlyExecutedSummary?.metrics?.[key];
        return [label, number(old?.observedTotal), `${old?.observedSamples ?? "缺失"} / ${old?.missingSamples ?? "缺失"}`,
          number(fresh?.observedTotal), `${fresh?.observedSamples ?? "缺失"} / ${fresh?.missingSamples ?? "缺失"}`];
      }))));
  }
  if (documentData.kind === "case") {
    target.append(panel("任务", node("p", data.input)), append(node("div", null, "two-columns"),
      panel("配置与预算", json({ configuration: data.configRef, budget: data.budget })), panel("初始环境", json(data.environment))), panel("断言定义", json(data.assertions)));
  }
  if (documentData.kind === "evaluation") {
    target.append(cards([["任务结论", display(data.outcome)], ["执行状态", display(data.execution?.status)],
      ["录制状态", display(data.recording?.outcome)], ["断言汇总", display(data.assertions?.outcome)]]));
    target.append(assertionDependencies(documentData), assertionCards(documentData));
    target.append(append(node("div", null, "two-columns"), panel("请求配置、实际配置与来源声明", json({ requestedConfiguration: data.case?.configRef,
      configuration: data.configuration, source: data.source, caseRunId: data.caseRunId, budgetEnforcement: data.budgetEnforcement })),
      panel("断言明细", json(data.assertions))), panel("观测指标", append(node("div"), metricsTable(data.metrics, false, data.source === "synthetic"),
        ...(data.source === "synthetic" ? [node("p", "合成事件计数不代表真实模型调用。", "subtext")] : []))));
  }
  const samples = sampleTable(data, links);
  if (samples) target.append(samples);
  const diagnostics = diagnosticSummary(data, links);
  if (diagnostics) target.append(diagnostics);
  if (data.summary?.metrics) target.append(panel(resumed ? "全部原计划样本的汇总指标（含历史复用）" : "汇总指标与缺失覆盖", metricsTable(data.summary.metrics, true)));
  if (data.comparisons) {
    target.append(panel("配置比较 · 描述本次实验", table(["配置对 / 用例", "来源声明", "共同配对 / 原计划", "排除", "通过比例差（右 − 左）", "说明"], data.comparisons.map((row) => [
      `${row.leftConfigurationId} → ${row.rightConfigurationId} / ${row.caseEntryId}`, display(row.source),
      `${row.pairedSamples} / ${row.plannedPairs}`, row.excludedPairs,
      row.rateDifferences?.attemptedPassRate === null ? "缺失" : String(row.rateDifferences?.attemptedPassRate), row.reason || "仅描述已观测配对",
    ]))));
    for (const comparison of data.comparisons) {
      target.append(panel(`指标差值 · ${comparison.leftConfigurationId} → ${comparison.rightConfigurationId} / ${comparison.caseEntryId} / ${display(comparison.source)}`,
        table(["观测指标", "共同观测 / 缺失配对", "左侧均值", "右侧均值", "均值差（右 − 左）", "差值范围"],
          Object.entries(comparison.metrics || {}).map(([key, metric]) => [metricNames[key] || key, `${metric.pairedSamples} / ${metric.missingPairs}`,
            number(metric.left?.observedMean), number(metric.right?.observedMean), number(metric.meanDifference),
            number(metric.minDifference) + " .. " + number(metric.maxDifference)]))));
      if (comparison.uncertainty) {
        const intervals = [["通过率差（右 − 左）", comparison.uncertainty.passRateDifference, true],
          ...Object.entries(comparison.uncertainty.metrics || {}).map(([key, value]) => [metricNames[key] || key, value, false])];
        target.append(panel(`配对差值置信区间 · ${comparison.caseEntryId} / ${comparison.leftConfigurationId} → ${comparison.rightConfigurationId} / ${display(comparison.source)}`,
          append(node("div"), node("p", "仅使用双方均可评测的完整配对，各指标再排除缺值；区间点估计属于此子集，可能不同于上方描述性差值。依赖独立重复等假设，未校正多重比较或可选停止，不据此宣布配置优胜。", "subtext"),
            table(["目标", "点估计与区间", "纳入 / 原计划", "排除", "排除原因"], intervals.map(([label, value, proportion]) => [
              label, intervalCell(value, proportion), `${number(value?.includedPairs)} / ${number(value?.plannedPairs)}`,
              number(value?.excludedPairs), json(value?.excludedReasons),
            ])))));
      }
    }
    if (data.savedSummary) target.append(panel(resumed ? "续跑结果保存的合并汇总指标" : "原实验保存的汇总指标", metricsTable(data.savedSummary.metrics, true)));
  }
  if (data.groups?.length) target.append(panel("按用例 / 配置分组的分母与覆盖", table(["用例 / 配置", "原计划", ...(resumed ? ["历史复用 / 本次新增"] : []), "全尝试通过", "可评测通过", "可评测覆盖", "复验匹配子集", "来源声明 / 样本"],
    data.groups.map((group) => [`${group.caseEntryId} / ${group.configurationId}`, group.summary?.planned,
      ...(resumed ? [`${group.byExecutionOrigin?.reused?.planned ?? "缺失"} / ${group.byExecutionOrigin?.new?.planned ?? "缺失"}`] : []),
      countRate(group.summary?.attemptedPassRate), countRate(group.summary?.evaluablePassRate), countRate(group.summary?.evaluableCoverage),
      group.matchedSummary?.planned ?? "缺失", Object.entries(group.bySource || group.summary?.sourceCounts || {}).map(([source, value]) => `${display(source)} / ${typeof value === "number" ? value : value.planned}`).join("；") || "缺失"]))));
  if (data.executionOrder) target.append(panel("执行顺序", table(["规则", "随机种子"], [[data.executionOrder.order,
    Object.hasOwn(data.executionOrder, "randomSeed") ? (Number.isSafeInteger(data.executionOrder.randomSeed)
      && data.executionOrder.randomSeed >= 0 ? String(data.executionOrder.randomSeed) : "缺失")
      : data.executionOrder.order === "repeat-case-configuration" ? "未设置（固定顺序）" : "缺失"]])));
  const hasIntervals = Array.isArray(data.repeatDistributions) && data.repeatDistributions.some((item) => Object.hasOwn(item, "passRateInterval"));
  if (Array.isArray(data.repeatDistributions)) target.append(panel("按用例查看重复结果分布", append(node("div"),
    node("p", "各配置、来源分开展示。有效通过 / 失败仅含复验匹配且正常完成的可评测样本；排除项不补零。区间若存在，只针对纳入子集，不能消除缺失与排除的选择偏差。", "subtext"),
    table(["用例 / 配置 / 来源", "本来源 / 原计划轮次", "通过 / 失败 / 无法评测 / 缺失", "有效通过 / 失败", "排除", "每轮结果"],
      data.repeatDistributions.map((item) => [
        `${item.caseEntryId} / ${item.configurationId} / ${display(item.source)}`,
        `${number(item.sourceSamples)} / ${number(item.plannedRepetitions)}`,
        ["passed", "failed", "unevaluable", "missing"].map((key) => number(item.outcomes?.[key])).join(" / "),
        `${number(item.eligiblePassed)} / ${number(item.eligibleFailed)}`, number(item.excludedSamples),
        append(node("div"), ...(Array.isArray(item.samples) ? item.samples : []).map((row) => node("p",
          `第 ${row.repeatIndex} 轮：${display(row.outcome)} · ${display(row.status)} · ${display(row.verification)} · ${display(row.configurationMatch)}`))),
      ])))));
  if (hasIntervals) target.append(panel("通过率置信区间", append(node("div"),
    node("p", "按用例 / 配置 / 来源独立计算，仅以可评测匹配样本为分母；区间依赖独立重复等假设，缺失与排除可能引入选择偏差。", "subtext"),
    table(["用例 / 配置 / 来源", "点估计与置信区间", "纳入 / 原计划", "本来源排除 / 其他来源"],
      data.repeatDistributions.map((item) => [
        `${item.caseEntryId} / ${item.configurationId} / ${display(item.source)}`, intervalCell(item.passRateInterval, true),
        `${number(item.passRateInterval?.n)} / ${number(item.passRateInterval?.plannedSamples)}`,
        `${number(item.passRateInterval?.excludedSamples)} / ${number(item.passRateInterval?.otherSourceSamples)}`,
      ])))));
  if (data.limitations?.length) target.append(panel("解释边界", append(node("div"), ...data.limitations.map((item) => node("p", item)))));
  const files = evidence(links);
  if (files) target.append(files);
  target.append(append(node("details", null, "panel padded"), node("summary", "查看保存的完整 JSON"), json(data)));
}
async function openDocument(id, offset = 0, remember = true, focus = null) {
  const sequence = ++requestSequence;
  try {
    const result = await api("/api/document?" + new URLSearchParams({ id, offset,
      ...(focus ? { seq: focus.seq, runId: focus.runId, sessionId: focus.sessionId } : {}) }));
    if (sequence !== requestSequence) return;
    if (remember && currentId && currentId !== id) stack.push(currentId);
    currentId = id;
    $("back").textContent = stack.length ? "← 返回上一页" : "← 返回列表";
    $("catalog-view").hidden = true;
    $("detail-view").hidden = false;
    $("document-path").textContent = id;
    $("title").textContent = result.data?.workflowName || result.data?.experimentName || result.data?.batchName || result.data?.caseId || result.data?.resumeId || "证据详情";
    renderDocument(result);
    message("");
    window.scrollTo(0, 0);
    if (result.focus) {
      $("focused-event")?.scrollIntoView({ block: "center" });
      $("focused-event")?.focus({ preventScroll: true });
    }
  } catch (error) { if (sequence === requestSequence) message(error.message); }
}
async function refresh() {
  $("refresh").disabled = true;
  try {
    const result = await api("/api/catalog");
    catalog = result.items;
    const warnings = [...result.warnings];
    if (result.truncated) warnings.push("目录超过 2000 项，当前列表已截断。请用更小的结果目录启动浏览。");
    message(warnings.join("\n"));
    navigation();
    if (currentId) await openDocument(currentId, 0, false);
    else renderCatalog();
  } catch (error) { message(error.message); }
  finally { $("refresh").disabled = false; }
}
$("search").addEventListener("input", renderCatalog);
$("outcome").addEventListener("change", renderCatalog);
$("source").addEventListener("change", renderCatalog);
$("refresh").addEventListener("click", refresh);
$("back").addEventListener("click", () => stack.length ? openDocument(stack.pop(), 0, false) : select(category));
select(category);
refresh();
