"use strict";

const $ = (id) => document.getElementById(id);
const categories = [
  ["experiment", "实验", "◫"], ["report", "配置报告", "▤"], ["batch", "批次", "☷"],
  ["evaluation", "逐次结果", "◷"], ["case", "用例库", "◇"],
];
const words = { passed: "通过", failed: "未通过", unevaluable: "无法评测", completed: "已完成", running: "进行中",
  stopped: "已停止", interrupted: "已中断", error: "出错", finished: "已结束", skipped: "已跳过", generated: "已生成",
  complete: "完整", invalid: "无效", unverified: "未核验", not_run: "未执行", insufficient_evidence: "证据不足",
  timed_out: "超时", cancelled: "已取消", runtime_error: "运行错误", unknown: "未知", live: "真实运行声明",
  synthetic: "合成声明", matched: "匹配", mismatched: "不匹配", verified: "复验已处理", rejected: "关联被拒绝", unavailable: "不可用",
  reused: "历史复用", new: "本次新增" };
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
    item.kind === "report" && item.outcomes ? node("span", `通过 ${item.outcomes.passed ?? "缺失"} · 未通过 ${item.outcomes.failed ?? "缺失"} · 无法评测 ${item.outcomes.unevaluable ?? "缺失"}`)
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
function summary(data) {
  return cards([["原计划样本", data.planned, `已尝试 ${data.attempted} · 已结束 ${data.finished} · 跳过 ${data.skipped}`],
    ["全尝试通过比例", rate(data.attemptedPassRate), countRate(data.attemptedPassRate)],
    ["可评测通过比例", rate(data.evaluablePassRate), countRate(data.evaluablePassRate)],
    ["可评测覆盖", rate(data.evaluableCoverage), countRate(data.evaluableCoverage)]]);
}
function metricsTable(metrics, aggregate = false) {
  if (!metrics) return node("p", "指标缺失");
  return table(aggregate ? ["观测指标", "已观测总和", "已观测均值", "观测 / 缺失样本", "观测范围"] : ["观测指标", "已观测值"],
    Object.entries(metricNames).map(([key, label]) => {
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
    return link.label.split(" / ").map((part) => names[part] || (part.endsWith(".jsonl") ? "事件轨迹" : part.endsWith(".status.json")
      ? "录制状态" : part === "run.json" ? "录制信息" : part === "runDir" ? "录制" : part)).join(" / ");
  }
  return panel("关联文件与原始证据", append(node("div", null, "evidence"), ...links.map((link) => link.id
    ? button(label(link), () => openDocument(link.id))
    : node("span", label(link) + "（缺失或超出浏览目录）", "subtext"))));
}
function renderDocument(documentData) {
  const target = $("detail"), data = documentData.data, links = documentData.links;
  target.replaceChildren();
  if (documentData.kind === "trace") {
    const rows = documentData.rows.map((row) => {
      const event = row.data?.event;
      return [row.line, event?.type || (row.error ? "无法解析 / 预览" : "原始记录"), json(row.error ? { error: row.error, preview: row.preview } : row.data)];
    });
    target.append(panel("原始事件轨迹", table(["行号", "事件", "记录内容"], rows)));
    const pagination = append(node("div", null, "pagination"), node("span", `从第 ${documentData.offset + 1} 行开始 · 本页 ${rows.length} 行`));
    if (documentData.offset > 0) pagination.append(button("上一页", () => openDocument(currentId, Math.max(0, documentData.offset - 50), false), "secondary"));
    if (documentData.nextOffset !== null) pagination.append(button("下一页", () => openDocument(currentId, documentData.nextOffset, false), "secondary"));
    target.append(pagination);
    return;
  }
  if (documentData.kind === "markdown") { target.append(panel("报告文本", node("pre", documentData.text))); return; }
  const resumed = [2, 3].includes(data.comparisonReportFormatVersion);
  if (data.summary) target.append(summary(data.summary));
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
      panel("配置与预算", json({ configuration: data.configRef, budget: data.budget })), panel("初始环境", json(data.environment))), panel("必要断言", json(data.assertions)));
  }
  if (documentData.kind === "evaluation") {
    target.append(cards([["任务结论", display(data.outcome)], ["执行状态", display(data.execution?.status)],
      ["录制状态", display(data.recording?.outcome)], ["断言状态", display(data.assertions?.outcome)]]));
    target.append(append(node("div", null, "two-columns"), panel("请求配置、实际配置与来源声明", json({ requestedConfiguration: data.case?.configRef,
      configuration: data.configuration, source: data.source, caseRunId: data.caseRunId, budgetEnforcement: data.budgetEnforcement })),
      panel("断言明细", json(data.assertions))), panel("观测指标", metricsTable(data.metrics)));
  }
  const samples = sampleTable(data, links);
  if (samples) target.append(samples);
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
    }
    if (data.savedSummary) target.append(panel(resumed ? "续跑结果保存的合并汇总指标" : "原实验保存的汇总指标", metricsTable(data.savedSummary.metrics, true)));
  }
  if (data.groups?.length) target.append(panel("按用例 / 配置分组的分母与覆盖", table(["用例 / 配置", "原计划", ...(resumed ? ["历史复用 / 本次新增"] : []), "全尝试通过", "可评测通过", "可评测覆盖", "复验匹配子集", "来源声明 / 样本"],
    data.groups.map((group) => [`${group.caseEntryId} / ${group.configurationId}`, group.summary?.planned,
      ...(resumed ? [`${group.byExecutionOrigin?.reused?.planned ?? "缺失"} / ${group.byExecutionOrigin?.new?.planned ?? "缺失"}`] : []),
      countRate(group.summary?.attemptedPassRate), countRate(group.summary?.evaluablePassRate), countRate(group.summary?.evaluableCoverage),
      group.matchedSummary?.planned ?? "缺失", Object.entries(group.bySource || group.summary?.sourceCounts || {}).map(([source, value]) => `${display(source)} / ${typeof value === "number" ? value : value.planned}`).join("；") || "缺失"]))));
  if (data.limitations?.length) target.append(panel("解释边界", append(node("div"), ...data.limitations.map((item) => node("p", item)))));
  const files = evidence(links);
  if (files) target.append(files);
  target.append(append(node("details", null, "panel padded"), node("summary", "查看保存的完整 JSON"), json(data)));
}
async function openDocument(id, offset = 0, remember = true) {
  const sequence = ++requestSequence;
  try {
    const result = await api("/api/document?" + new URLSearchParams({ id, offset }));
    if (sequence !== requestSequence) return;
    if (remember && currentId && currentId !== id) stack.push(currentId);
    currentId = id;
    $("back").textContent = stack.length ? "← 返回上一页" : "← 返回列表";
    $("catalog-view").hidden = true;
    $("detail-view").hidden = false;
    $("document-path").textContent = id;
    $("title").textContent = result.data?.experimentName || result.data?.batchName || result.data?.caseId || "证据详情";
    renderDocument(result);
    window.scrollTo(0, 0);
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
