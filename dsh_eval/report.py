"""Recheck one frozen experiment and write a separate descriptive comparison report."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
from itertools import combinations
import json
import os
from pathlib import Path, PurePosixPath
import re
from urllib.parse import quote
from uuid import uuid4

from .evaluate import evaluate
from .diagnostics import diagnostic_sample, diagnostic_summary, assertion_causes, assertion_cause_summary
from .experiment import _plan_fingerprint, _order_metadata, _check_order, _sample_plan
from .formats import fields, load_json, nonempty, parse_json, require, validate_case, validate_experiment
from .metrics import METRICS, empty_metrics, number, summarize
from .runner import ROOT, save_json
from .uncertainty import LEVEL, wilson_interval, paired_binary_interval, paired_mean_interval


def _same(left, right):
    return json.dumps(left, sort_keys=True, ensure_ascii=False) == json.dumps(right, sort_keys=True, ensure_ascii=False)


def _path(directory, value):
    require(nonempty(value) and "\\" not in value and ":" not in value
            and not PurePosixPath(value).is_absolute()
            and all(part not in ("", ".", "..") for part in value.split("/")),
            "Report inputs must use contained relative POSIX paths")
    resolved = (directory / value).resolve()
    require(resolved.is_relative_to(directory), "Report input escapes the experiment directory")
    return resolved


def _summary(rows):
    result = summarize(rows)
    result["diagnosticSummary"] = diagnostic_summary(rows)
    result["assertionCauseSummary"] = assertion_cause_summary(rows)
    for key in METRICS:
        values = [(row.get("metrics") or {}).get(key) for row in rows]
        observed = [value for value in values if number(value)]
        result["metrics"][key].update(observedMin=min(observed) if observed else None,
                                      observedMax=max(observed) if observed else None)
    return result


def _interval_eligible(row):
    return (row["verification"] == "verified" and row["configurationMatch"] == "matched"
            and row["executionStatus"] == "completed" and row["recordingOutcome"] == "complete"
            and row["assertionOutcome"] in ("passed", "failed") and row["outcome"] in ("passed", "failed"))


def _repeat_distributions(rows, manifest):
    distributions = []
    for entry in manifest["cases"]:
        for config in manifest["configurations"]:
            subset = [row for row in rows if row["caseEntryId"] == entry["entryId"]
                      and row["configurationId"] == config["configurationId"]]
            for source in sorted({row["source"] or "unknown" for row in subset}):
                selected = sorted((row for row in subset if (row["source"] or "unknown") == source),
                                  key=lambda row: row["repeatIndex"])
                eligible = [row for row in selected if _interval_eligible(row)]
                counts = Counter(row["outcome"] or "missing" for row in selected)
                interval = wilson_interval(sum(row["outcome"] == "passed" for row in eligible), len(eligible))
                interval.update(plannedSamples=manifest["repetitions"], sourceSamples=len(selected),
                                excludedSamples=len(selected) - len(eligible), otherSourceSamples=manifest["repetitions"] - len(selected),
                                repeatIndices=[row["repeatIndex"] for row in eligible])
                if len(eligible) < manifest["repetitions"]:
                    interval["warnings"].append("incomplete_coverage")
                distributions.append({"caseEntryId": entry["entryId"], "configurationId": config["configurationId"],
                    "source": source, "plannedRepetitions": manifest["repetitions"], "sourceSamples": len(selected),
                    "outcomes": {key: counts[key] for key in ("passed", "failed", "unevaluable", "missing")},
                    "statusCounts": dict(Counter(row["status"] for row in selected)),
                    "eligiblePassed": sum(row["outcome"] == "passed" for row in eligible),
                    "eligibleFailed": sum(row["outcome"] == "failed" for row in eligible),
                    "excludedSamples": len(selected) - len(eligible),
                    "passRateInterval": interval,
                    "samples": [{key: row[key] for key in ("sampleId", "repeatIndex", "status", "outcome",
                                "verification", "configurationMatch")} for row in selected]})
    return distributions


def _load_plan(source):
    directory = source.parent
    saved = load_json(source)
    require(isinstance(saved, dict), "Experiment result must be an object")
    require(type(saved.get("experimentResultFormatVersion")) is int
            and saved["experimentResultFormatVersion"] == 1, "Unsupported experiment result format")
    require(saved.get("status") in ("completed", "stopped", "interrupted", "error")
            and nonempty(saved.get("finishedAt")), "Report requires a terminal experiment result")
    require(nonempty(saved.get("experimentId")) and nonempty(saved.get("batchId")), "Missing experiment/batch identity")
    manifest = validate_experiment(load_json(_path(directory, saved["manifestPath"])))
    for key in ("experimentName", "repetitions", "configurations", "failurePolicy"):
        require(_same(saved[key], manifest[key]), f"Frozen experiment/result {key} mismatch")
    _check_order(saved, manifest)
    batch_path = _path(directory, saved["batchResultPath"])
    batch = load_json(batch_path)
    require(isinstance(batch, dict), "Batch result must be an object")
    require(type(batch.get("batchResultFormatVersion")) is int and batch["batchResultFormatVersion"] == 1
            and batch["batchId"] == saved["batchId"] and batch["status"] == saved["status"],
            "Experiment/batch result mismatch")
    cases = {entry["entryId"]: validate_case(load_json(_path(directory, entry["casePath"]))) for entry in manifest["cases"]}
    count = len(manifest["cases"]) * len(manifest["configurations"]) * manifest["repetitions"]
    require(isinstance(saved["samples"], list) and isinstance(batch["entries"], list)
            and len(saved["samples"]) == len(batch["entries"]) == count, "Experiment sample count mismatch")
    positions = _sample_plan(manifest)
    seen_samples, seen_runs, seen_sessions, seen_recordings = set(), set(), set(), set()
    for sample, row, position in zip(saved["samples"], batch["entries"], positions):
        require(isinstance(sample, dict) and isinstance(row, dict), "Sample must be an object")
        require(type(sample["repeatIndex"]) is int
                and all(sample[key] == position[key] for key in ("caseEntryId", "configurationId", "repeatIndex")),
                "Experiment sample position mismatch")
        if "randomSeed" in manifest:
            require(sample["sampleId"] == position["sampleId"], "Randomized sample identity mismatch")
        require(nonempty(sample["sampleId"]) and sample["sampleId"] not in seen_samples
                and sample["sampleId"] == sample["entryId"] == row["entryId"], "Duplicate or mismatched sample identity")
        seen_samples.add(sample["sampleId"])
        config = next(item["configRef"] for item in manifest["configurations"] if item["configurationId"] == position["configurationId"])
        require(_same(sample["requestedConfiguration"], config)
                and sample["caseId"] == cases[position["caseEntryId"]]["caseId"], "Sample requested configuration/case mismatch")
        for key in ("caseId", "requestedConfiguration", "status", "caseRunId", "runId", "sessionId", "configuration", "source"):
            require(_same(sample.get(key), row.get(key)), f"Experiment/batch sample {key} mismatch")
        require(sample["status"] in ("finished", "error", "skipped"), "Nonterminal sample")
        for key in ("casePath", "caseDirectory", "evidencePath", "evaluationPath", "runtimeReport", "runDir"):
            left, right = sample.get(key), row.get(key)
            require((left is None) == (right is None), f"Experiment/batch sample {key} mismatch")
            if left is not None:
                require(_path(directory, left) == _path(batch_path.parent, right), f"Experiment/batch sample {key} mismatch")
        for key, seen in (("caseRunId", seen_runs), ("runId", seen_recordings), ("sessionId", seen_sessions)):
            value = sample[key]
            if value is not None:
                require(nonempty(value) and value not in seen, f"Duplicate or invalid experiment {key}")
                seen.add(value)
        if sample["status"] == "skipped":
            require(all(sample[key] is None for key in ("caseRunId", "runId", "sessionId", "configuration", "outcome")),
                    "Skipped sample contains execution facts")
        if sample["status"] == "finished":
            require(nonempty(sample["caseRunId"]), "Finished sample lacks caseRunId")
    return saved, manifest, cases


def _verify_plan_input(directory, saved, manifest, cases):
    fingerprint = saved.get("planFingerprint")
    if "planFingerprint" in saved:
        fields(fingerprint, ("version", "sha256"))
        require(type(fingerprint["version"]) is int and fingerprint["version"] == 1,
                "Unsupported plan fingerprint version")
        require(isinstance(fingerprint["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", fingerprint["sha256"]) is not None,
                "Invalid saved plan fingerprint")
    expected = saved.get("expectedPlanSha256")
    require(expected is None or isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected) is not None,
            "Invalid saved expected plan SHA-256")
    require(expected is None or fingerprint is not None and expected == fingerprint["sha256"],
            "Saved expected/actual plan fingerprint mismatch")
    verification = {"status": "unverified", "fingerprint": fingerprint, "expectedPlanSha256": expected,
                    "inputPath": None, "reason": "No saved plan input snapshot; original fingerprint cannot be rechecked"}
    if "planInputPath" not in saved:
        return verification
    require(fingerprint is not None, "Plan input snapshot requires a saved fingerprint")
    payload = load_json(_path(directory, saved["planInputPath"]))
    fields(payload, ("version", "manifest", "cases", "maxSamples", "order"))
    require(type(payload["version"]) is int and payload["version"] == 1, "Unsupported plan input version")
    require(payload["order"] == _order_metadata(manifest)["order"], "Unsupported plan input order")
    limit = payload["maxSamples"]
    require(limit is None or type(limit) is int and limit > 0, "Plan input maxSamples must be a positive integer")
    require("maxSamples" in saved and _same(limit, saved["maxSamples"]), "Plan input/result maxSamples mismatch")
    original = validate_experiment(payload["manifest"])
    count = len(original["cases"]) * len(original["configurations"]) * original["repetitions"]
    require(limit is None or count <= limit, "Plan input exceeds maxSamples")
    require(len(original["cases"]) == len(manifest["cases"]), "Plan input/frozen case count mismatch")
    normalized = {**original, "cases": [{**entry, "casePath": frozen["casePath"]}
                  for entry, frozen in zip(original["cases"], manifest["cases"])]}
    require(_same(normalized, manifest), "Plan input/frozen experiment mismatch")
    require(isinstance(payload["cases"], list) and len(payload["cases"]) == len(original["cases"]),
            "Plan input case snapshots must match all manifest entries")
    for entry, case in zip(original["cases"], payload["cases"]):
        validate_case(case)
        require(_same(case, cases[entry["entryId"]]), "Plan input/frozen case mismatch")
    actual = _plan_fingerprint(original, payload["cases"], limit)
    require(actual == fingerprint, "Saved plan fingerprint differs from its input snapshot")
    verification.update(status="verified", fingerprint=actual, inputPath=saved["planInputPath"], reason=None)
    return verification


def _configuration_match(result, expected):
    actual = result["configuration"]
    if actual is None:
        return "unknown", "No actual configuration was observed"
    if not _same(actual, expected):
        return "mismatched", "Observed configuration differs from the requested configuration"
    if result["recording"]["outcome"] != "complete":
        return "unknown", "Actual request routes require a complete associated recording"
    session = result["recording"]["inspection"]["sessions"][0]
    trace = Path(result["association"]["runDir"]) / session["traceFile"]
    with trace.open(encoding="utf-8") as stream:
        headers = [item["event"].get("data", {}).get("header", {}).get("config", {})
                   for line in stream if (item := parse_json(line))["event"].get("type") == "request/header"]
    if not headers or any(not isinstance(header, dict) or not all(nonempty(header.get(key)) for key in ("provider", "model"))
                          for header in headers):
        return "unknown", "No complete request route was recorded"
    if any(any(header[key] != expected[key] for key in ("provider", "model")) for header in headers):
        return "mismatched", "Recorded request routes differ from the requested configuration"
    return "matched", None


def _recheck(sample, expected, directory, batch_id):
    row = {key: sample[key] for key in ("sampleId", "caseEntryId", "caseId", "configurationId", "repeatIndex", "status",
                                       "caseRunId", "runId", "sessionId", "requestedConfiguration")}
    row.update(source=None, configuration=None, configurationMatch="unknown", configurationReason=None,
               executionStatus=None, recordingOutcome=None, assertionOutcome=None,
               outcome=None if sample["status"] == "skipped" else "unevaluable", metrics=empty_metrics(),
               verification="skipped" if sample["status"] == "skipped" else "unavailable", reasons=[],
               sourceEvidencePath=None, evaluationPath=None, diagnosticSummary=None,
               assertionCauses={"assertionCausesFormatVersion": 1, "status": "unavailable", "reasonCode": "not_evaluated"},
               saved={key: sample.get(key) for key in ("source", "configuration", "configurationMatch", "executionStatus",
                                                       "recordingOutcome", "assertionOutcome", "outcome", "metrics")})
    fresh = None
    if sample["status"] != "skipped":
        try:
            case_path = _path(directory, sample["casePath"])
            require(_same(validate_case(load_json(case_path)), expected), "Frozen sample task/environment/budget/assertions mismatch")
            if sample.get("caseDirectory"):
                require(_same(validate_case(load_json(_path(directory, sample["caseDirectory"] + "/case.json"))), expected),
                        "Executed case snapshot differs from the frozen task")
            require(sample.get("evidencePath") is not None, "No sample evidence was saved")
            evidence_path = _path(directory, sample["evidencePath"])
            row["sourceEvidencePath"] = str(evidence_path)
            evidence = load_json(evidence_path)
            for key, value in (("caseRunId", sample["caseRunId"]), ("caseId", sample["caseId"]), ("batchId", batch_id),
                               ("runId", sample["runId"]), ("sessionId", sample["sessionId"]), ("source", sample.get("source")),
                               ("configuration", sample.get("configuration"))):
                require(_same(evidence.get(key), value), f"Sample/evidence {key} mismatch")
            for key in ("runDir", "runtimeReport"):
                target = _path(directory, sample[key]) if sample.get(key) is not None else None
                # Version 2 runner evidence stores native Windows separators; result manifests use POSIX paths.
                actual = _path(evidence_path.parent, evidence[key].replace("\\", "/")) if evidence.get(key) is not None else None
                require(target == actual, f"Sample/evidence {key} mismatch")
            fresh = evaluate(case_path, evidence_path)
            match, reason = _configuration_match(fresh, expected["configRef"])
            row.update(verification="verified", source=fresh["source"], configuration=fresh["configuration"],
                       configurationMatch=match, configurationReason=reason, executionStatus=fresh["execution"]["status"],
                       recordingOutcome=fresh["recording"]["outcome"], assertionOutcome=fresh["assertions"]["outcome"],
                       outcome=fresh["outcome"], metrics=fresh["metrics"], diagnosticSummary=diagnostic_sample(fresh))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as error:
            row.update(verification="unavailable" if sample["status"] == "error" else "rejected", reasons=[str(error)])
            fresh = None
    if fresh is not None:
        row["assertionCauses"] = assertion_causes(fresh)
    row["changedFields"] = [key for key, value in row["saved"].items() if not _same(value, row[key])]
    return row, fresh


def _paired_intervals(a, b, repetitions, same):
    eligible, excluded = [], Counter()
    for index in range(1, repetitions + 1):
        if same:
            excluded["same_configuration"] += 1
        elif index not in a or index not in b:
            excluded["missing_verified_matched_pair"] += 1
        elif not (_interval_eligible(a[index]) and _interval_eligible(b[index])):
            excluded["not_jointly_evaluable"] += 1
        else:
            eligible.append(index)

    def covered(interval, indices, reasons):
        interval.update(plannedPairs=repetitions, includedPairs=len(indices), excludedPairs=repetitions - len(indices),
                        repeatIndices=indices, excludedReasons=dict(reasons))
        if len(indices) < repetitions:
            interval["warnings"].append("incomplete_coverage")
        if same:
            interval["reason"] = "same_configuration"
        return interval

    passed = [int(b[index]["outcome"] == "passed") - int(a[index]["outcome"] == "passed") for index in eligible]
    result = {"confidenceLevel": LEVEL, "direction": "right-minus-left",
              "passRateDifference": covered(paired_binary_interval(passed), eligible, excluded), "metrics": {}}
    for key in METRICS:
        indices = [index for index in eligible if number((a[index].get("metrics") or {}).get(key))
                   and number((b[index].get("metrics") or {}).get(key))]
        reasons = excluded.copy()
        if len(indices) < len(eligible):
            reasons["missing_metric"] += len(eligible) - len(indices)
        differences = [b[index]["metrics"][key] - a[index]["metrics"][key] for index in indices]
        result["metrics"][key] = covered(paired_mean_interval(differences), indices, reasons)
    return result


def _compare(left, right, case_id, source, rows, repetitions):
    def selected(config):
        return {row["repeatIndex"]: row for row in rows if row["configurationId"] == config["configurationId"]
                and row["caseEntryId"] == case_id and row["source"] == source
                and row["verification"] == "verified" and row["configurationMatch"] == "matched"}

    a, b = selected(left), selected(right)
    repeats = sorted(a.keys() & b.keys())
    same = _same(left["configRef"], right["configRef"])
    if same:
        repeats = []
    left_rows, right_rows = [a[index] for index in repeats], [b[index] for index in repeats]
    left_summary, right_summary = _summary(left_rows), _summary(right_rows)
    comparison = {"caseEntryId": case_id, "source": source,
                  "leftConfigurationId": left["configurationId"], "rightConfigurationId": right["configurationId"],
                  "status": "descriptive" if repeats else "unavailable",
                  "reason": "Configuration IDs refer to the same configRef" if same else
                            None if repeats else "No verified pairs with matching actual configurations and source",
                  "plannedPairs": repetitions, "pairedSamples": len(repeats), "excludedPairs": repetitions - len(repeats),
                  "repeatIndices": repeats, "leftSummary": left_summary, "rightSummary": right_summary,
                  "rateDifferences": {}, "metrics": {}, "uncertainty": _paired_intervals(a, b, repetitions, same)}
    for key in ("evaluablePassRate", "attemptedPassRate", "evaluableCoverage"):
        x, y = left_summary[key]["value"], right_summary[key]["value"]
        comparison["rateDifferences"][key] = y - x if x is not None and y is not None else None
    for key in METRICS:
        pairs = [(a[index], b[index]) for index in repeats
                 if number((a[index].get("metrics") or {}).get(key)) and number((b[index].get("metrics") or {}).get(key))]
        x = _summary([pair[0] for pair in pairs])["metrics"][key]
        y = _summary([pair[1] for pair in pairs])["metrics"][key]
        deltas = [pair[1]["metrics"][key] - pair[0]["metrics"][key] for pair in pairs]
        difference = y["observedMean"] - x["observedMean"] if y["observedMean"] is not None and x["observedMean"] is not None else None
        comparison["metrics"][key] = {"pairedSamples": len(pairs), "missingPairs": repetitions - len(pairs),
                                      "left": x, "right": y, "meanDifference": difference,
                                      "minDifference": min(deltas) if deltas else None,
                                      "maxDifference": max(deltas) if deltas else None}
    return comparison


def _cell(value):
    text = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\r", " ").replace("\n", " ")
    for character in "\\`*_[]|":
        text = text.replace(character, "\\" + character)
    return text


def _rate(value):
    return f"{value['numerator']}/{value['denominator']}" + (f" ({value['value']:.1%})" if value["value"] is not None else " (缺失)")


def _value(value):
    if value is None:
        return "缺失"
    return format(value, ".6g") if isinstance(value, float) else str(value)


def _metric(value):
    text = f"均值 {_value(value['observedMean'])}；范围 {_value(value['observedMin'])} .. {_value(value['observedMax'])}；观测 {value['observedSamples']} / 缺失 {value['missingSamples']}"
    return _cell(text + (f"；{value['reason']}" if value.get("reason") else ""))


def _interval_text(interval, proportion=False):
    if interval is None:
        return "未保存区间"
    if interval["status"] != "available":
        return _cell(f"不可用：{interval['reason']}；n={interval['n']}")
    value = (lambda item: f"{item:.2%}") if proportion else _value
    warnings = "；" + ", ".join(interval["warnings"]) if interval["warnings"] else ""
    return _cell(f"{value(interval['estimate'])} [{value(interval['lower'])}, {value(interval['upper'])}]；n={interval['n']}{warnings}")


def _assertion_cause_markdown(report):
    value = report.get("summary", {}).get("assertionCauseSummary")
    if not isinstance(value, dict) or value.get("assertionCauseSummaryFormatVersion") != 1:
        return []
    lines = ["", "## 结构化原因与依赖汇总", "",
             f"诊断可用 {value['availableSamples']} / 计划 {value['plannedSamples']}；缺失 {value['missingSamples']}。", "",
             "独立问题、后继阻断和全局门禁分别按受影响样本计数，同一样本可同时出现多个分类或角色，不能相加作为失败任务数。"
             "同一原因码在同一样本和角色内只计一次；一个缺证源头与三个后继不等于四个独立问题。"
             "全局门禁表示尚未完成逐项评分，原任务结论与通过率不变。", "",
             f"诊断缺失原因：{_cell(value['missingReasons'])}。", "",
             "| 角色 | 声明该角色样本 | 独立问题影响样本 | 后继阻断影响样本 | 全局门禁影响样本 | 独立断言问题 / 阻断断言数 |",
             "| --- | --- | --- | --- | --- | --- |"]
    roles = (("required", "必需项"), ("diagnostic", "诊断项"))
    for role, label in roles:
        row = value["byRole"][role]
        lines.append(f"| {label} | {row['declaredSamples']} | {row['rootAffectedSamples']} | {row['blockedAffectedSamples']} | "
                     f"{row['globalGateAffectedSamples']} | {row['rootIssueCount']} / {row['blockedAssertionCount']} |")
    lines.extend(["", "| 用例 / 配置 / 来源 | 可用 / 计划 | 缺失 | 角色 | 声明样本 | 独立问题 / 后继阻断 / 全局门禁影响样本 |",
                  "| --- | --- | --- | --- | --- | --- |"])
    for group in report.get("groups", []):
        for source, summary in group.get("bySource", {}).items():
            counts = summary.get("assertionCauseSummary")
            if counts is None:
                continue
            for role, label in roles:
                row = counts["byRole"][role]
                lines.append(f"| {_cell(group['caseEntryId'])} / {_cell(group['configurationId'])} / {_cell(source)} | "
                             f"{counts['availableSamples']} / {counts['plannedSamples']} | {counts['missingSamples']} | {label} | "
                             f"{row['declaredSamples']} | {row['rootAffectedSamples']} / {row['blockedAffectedSamples']} / {row['globalGateAffectedSamples']} |")
    samples = {row["sampleId"]: row for row in report.get("samples", [])}

    def sample_link(sample_id):
        sample = samples.get(sample_id, {})
        path = sample.get("evaluationPath")
        return f"[{_cell(sample_id)}]({quote(path, safe='/')})" if path else _cell(sample_id)

    lines.extend(["", "| 角色 | 分类 | 原因码 | 影响样本 | 逐项复验 |", "| --- | --- | --- | --- | --- |"])
    for role, label in roles:
        row = value["byRole"][role]
        for key, category in (("rootReasons", "独立问题"), ("globalGateReasons", "全局门禁")):
            for reason in row[key]:
                links = ", ".join(sample_link(sample_id) for sample_id in reason["sampleIds"])
                lines.append(f"| {label} | {category} | {_cell(reason['reasonCode'])} | {reason['affectedSamples']} | {links} |")
        if row["blockedSampleIds"]:
            links = ", ".join(sample_link(sample_id) for sample_id in row["blockedSampleIds"])
            lines.append(f"| {label} | 后继阻断 | dependency\\_not\\_passed | {row['blockedAffectedSamples']} | {links} |")
    lines.extend(["", "| 样本 / 来源 | 角色 / 诊断状态 | 独立问题断言 | 后继阻断断言 | 全局门禁断言 | 逐项复验 |",
                  "| --- | --- | --- | --- | --- | --- |"])
    for sample in report.get("samples", []):
        causes = sample.get("assertionCauses") or {}
        if causes.get("status") != "available":
            lines.append(f"| {_cell(sample['sampleId'])} / {_cell(sample.get('source'))} | 不可用：{_cell(causes.get('reasonCode'))} | — | — | — | "
                         f"{sample_link(sample['sampleId'])} |")
            continue
        for role, label in roles:
            row = causes["byRole"][role]
            if not any(row[key] for key in ("rootIssues", "blockedAssertions", "globalGates")):
                continue
            ids = lambda key: _cell(", ".join(item["id"] for item in row[key]))
            lines.append(f"| {_cell(sample['sampleId'])} / {_cell(sample.get('source'))} | {label} | {ids('rootIssues')} | "
                         f"{ids('blockedAssertions')} | {ids('globalGates')} | {sample_link(sample['sampleId'])} |")
    return lines


def render_markdown(report):
    local_time = datetime.fromisoformat(report["generatedAt"]).astimezone(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    plan = report["planVerification"]
    lines = [f"# 配置报告：{_cell(report['experimentName'])}", "", f"报告 ID：{report['reportId']}。生成于 {local_time}（Asia/Shanghai）。", "",
             "本报告重新检查保存的用例、证据和录制；历史实验与评测文件保持原样。差值均为右侧减左侧，仅描述当前可配对样本。", "",
             "## 范围与不确定性", "", *[f"- {item}" for item in report["limitations"]], "",
             f"计划指纹复核：{plan['status']}。{_cell(plan['reason'] or '输入快照、冻结用例与保存摘要一致；不表示任务通过。')}", "",
             f"样本复核：{_cell(report['verificationCounts'])}。", "", "## 按请求配置统计全部计划项", "",
             "| 配置 | 用例 | 计划 / 尝试 / 跳过 | 可评测通过 | 全尝试通过 | 可评测覆盖 | 实际匹配 / 计划 | 来源 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for group in report["groups"]:
        s = group["summary"]
        lines.append(f"| {_cell(group['configurationId'])} | {_cell(group['caseEntryId'])} | {s['planned']} / {s['attempted']} / {s['skipped']} | "
                     f"{_rate(s['evaluablePassRate'])} | {_rate(s['attemptedPassRate'])} | {_rate(s['evaluableCoverage'])} | "
                     f"{group['matchedSummary']['planned']} / {s['planned']} | {_cell(s['sourceCounts'])} |")
    lines.extend(["", "配置引用：", ""])
    for config in report["configurations"]:
        lines.append(f"- {_cell(config['configurationId'])}：{_cell(json.dumps(config['configRef'], ensure_ascii=False))}")
    if "diagnosticSummary" in report["summary"]:
        diagnostic = report["summary"]["diagnosticSummary"]
        lines.extend(["", "## 诊断项覆盖与结果", "",
                      f"已复验样本 {diagnostic['observedSamples']}，缺少复验 {diagnostic['missingSamples']}。"
                      f"含诊断项样本 {diagnostic['samplesWithDiagnostics']}；"
                      f"任务通过且存在诊断失败的样本 {diagnostic['passedSamplesWithFailures']}。", "",
                      "以下统计诊断项的逐项结果；任务通过率仍由必需项决定。", "",
                      "| 配置 / 用例 | 已复验 / 缺失 | 含诊断 / 含失败样本 | 任务通过且诊断失败 | 诊断通过 / 失败 / 证据不足 / 未执行 |",
                      "| --- | --- | --- | --- | --- |"])
        for group in report["groups"]:
            value = group["summary"]["diagnosticSummary"]
            counts = value["assertionCounts"]
            lines.append(f"| {_cell(group['configurationId'])} / {_cell(group['caseEntryId'])} | "
                         f"{value['observedSamples']} / {value['missingSamples']} | "
                         f"{value['samplesWithDiagnostics']} / {value['samplesWithFailures']} | "
                         f"{value['passedSamplesWithFailures']} | "
                         f"{counts['passed']} / {counts['failed']} / {counts['insufficient_evidence']} / {counts['not_run']} |")
        lines.extend(["", "| 样本 | 诊断失败 ID | 证据不足 ID | 未执行 ID | 逐项复验 |",
                      "| --- | --- | --- | --- | --- |"])
        for row in report["samples"]:
            value = row.get("diagnosticSummary")
            if value is not None and value["declaredAssertions"] > 0:
                link = f"[查看]({quote(row['evaluationPath'], safe='/')})" if row.get("evaluationPath") else "缺失"
                lines.append(f"| {_cell(row['sampleId'])} | {_cell(', '.join(value['failedAssertionIds']))} | "
                             f"{_cell(', '.join(value['insufficientAssertionIds']))} | "
                             f"{_cell(', '.join(value['notRunAssertionIds']))} | {link} |")
    lines.extend(_assertion_cause_markdown(report))
    if report.get("resumeVerification"):
        if report.get("resumeChain"):
            lines.extend(["", "## 连续续跑来源", "", "| 轮次 | 续跑 ID | 保存结果 |", "| --- | --- | --- |"])
            for index, item in enumerate(report["resumeChain"], 1):
                lines.append(f"| {index} | {_cell(item['resumeId'])} | {_cell(item['resultPath'])} |")
            lines.extend(["", "来源批次（原批次到本轮新增）：" + " / ".join(report["batchIds"]), ""])
        lines.extend(["", "## 历史复用与本次新增", "",
                      f"续跑关联复核：{report['resumeVerification']['status']}；逐样本证据仍分别重新检查。", "",
                      "历史复用的用量属于原执行；本次新增只统计新批次。两者合计描述原计划的样本，不能全部当作本次消耗。", "",
                      "| 执行来源 | 计划 / 尝试 / 跳过 | 可评测通过 | 来源 |", "| --- | --- | --- | --- |"])
        for label, summary in (("历史复用", report["reusedSummary"]), ("本次新增", report["newlyExecutedSummary"])):
            lines.append(f"| {label} | {summary['planned']} / {summary['attempted']} / {summary['skipped']} | "
                         f"{_rate(summary['evaluablePassRate'])} | {_cell(summary['sourceCounts'])} |")
        lines.extend(["", "| 指标 | 历史复用 | 本次新增 |", "| --- | --- | --- |"])
        for key in METRICS:
            old, new = report['reusedSummary']['metrics'][key], report['newlyExecutedSummary']['metrics'][key]
            lines.append(f"| {key} | 累计 {_value(old['observedTotal'])}；{_metric(old)} | "
                         f"累计 {_value(new['observedTotal'])}；{_metric(new)} |")
    for group in report["groups"]:
        lines.extend(["", f"### 指标：{_cell(group['caseEntryId'])} / {_cell(group['configurationId'])}", "",
                      "以下为全部计划项中可观测子集；实际匹配分布与分来源统计另存于 JSON。", "",
                      "| 指标 | 均值、范围与覆盖 |", "| --- | --- |"])
        for key in METRICS:
            lines.append(f"| {key} | {_metric(group['summary']['metrics'][key])} |")
    if report.get("executionOrder"):
        order = report["executionOrder"]
        lines.extend(["", "## 执行顺序与重复结果分布", "",
                      f"顺序规则：{_cell(order['order'])}；随机种子：{_cell(order.get('randomSeed', '未设置（固定顺序）'))}。", "",
                      "按用例、配置和来源分开；各轮保留原结论及复核状态。有效通过 / 失败仅含复验匹配且正常完成的可评测样本，排除项不补成失败。", "",
                      "| 用例 / 配置 / 来源 | 本来源 / 原计划轮次 | 通过 / 失败 / 无法评测 / 缺失 | 有效通过 / 失败 | 排除 | 每轮：结论 / 状态 / 复核 / 配置匹配 | 可评测匹配通过率 95% 区间 |",
                      "| --- | --- | --- | --- | --- | --- | --- |"])
        for distribution in report.get("repeatDistributions", []):
            counts = distribution["outcomes"]
            repeats = "; ".join(f"{row['repeatIndex']}: {row['outcome']} / {row['status']} / {row['verification']} / {row['configurationMatch']}"
                                for row in distribution["samples"])
            lines.append(f"| {_cell(distribution['caseEntryId'])} / {_cell(distribution['configurationId'])} / {_cell(distribution['source'])} | "
                         f"{distribution['sourceSamples']} / {distribution['plannedRepetitions']} | "
                         f"{counts['passed']} / {counts['failed']} / {counts['unevaluable']} / {counts['missing']} | "
                         f"{distribution['eligiblePassed']} / {distribution['eligibleFailed']} | {distribution['excludedSamples']} | {_cell(repeats)} | "
                         f"{_interval_text(distribution.get('passRateInterval'), True)} |")
    lines.extend(["", "## 同用例、同重复编号与同来源的配置差值", ""])
    if not report["comparisons"]:
        lines.append("只有一个配置，无法生成配置间差值。")
    for item in report["comparisons"]:
        lines.extend([f"### {_cell(item['caseEntryId'])}：{_cell(item['leftConfigurationId'])} → {_cell(item['rightConfigurationId'])} / {item['source']}", "",
                      f"状态：{item['status']}；可配对 {item['pairedSamples']}/{item['plannedPairs']}，排除 {item['excludedPairs']}。", ""])
        if item["reason"]:
            lines.extend([_cell(item["reason"]), ""])
        for key in ("evaluablePassRate", "attemptedPassRate", "evaluableCoverage"):
            lines.append(f"- {key}：{_rate(item['leftSummary'][key])} → {_rate(item['rightSummary'][key])}；差值 {_value(item['rateDifferences'][key])}")
        lines.extend(["", "| 指标 | 配对 / 缺失 | 左均值 | 右均值 | 均值差 | 单对差值范围 |", "| --- | --- | --- | --- | --- | --- |"])
        for key, value in item["metrics"].items():
            reason = value["left"].get("reason") or value["right"].get("reason") or ""
            lines.append(f"| {key} | {value['pairedSamples']} / {value['missingPairs']} | {_value(value['left']['observedMean'])} | "
                         f"{_value(value['right']['observedMean'])} | {_value(value['meanDifference'])} {_cell(reason)} | "
                         f"{_value(value['minDifference'])} .. {_value(value['maxDifference'])} |")
        if item.get("uncertainty"):
            lines.extend(["", "配对差值 95% 区间：只使用双方均可评测的完整配对，各指标再排除缺值；点估计采用此子集的逐对差值均值，可能不同于上方描述性差值。", "",
                          "| 区间目标 | 点估计与区间 | 纳入 / 计划 | 排除 | 排除原因 |",
                          "| --- | --- | --- | --- | --- |"])
            intervals = {"passRateDifference": item["uncertainty"]["passRateDifference"], **item["uncertainty"]["metrics"]}
            for key, interval in intervals.items():
                lines.append(f"| {key} | {_interval_text(interval, key == 'passRateDifference')} | "
                             f"{interval['includedPairs']} / {interval['plannedPairs']} | {interval['excludedPairs']} | "
                             f"{_cell(interval['excludedReasons'])} |")
        lines.append("")
    lines.extend(["## 逐样本复核与证据", "", "| 样本 | 复核 | 结论：执行 / 录制 / 断言 | 实际匹配 | 历史差异 | 证据与原因 |",
                  "| --- | --- | --- | --- | --- | --- |"])
    directory = Path(report["reportDirectory"])
    for row in report["samples"]:
        links = []
        for label, path in (("复验", row["evaluationPath"]), ("原证据", row["sourceEvidencePath"])):
            if path:
                target = directory / path if label == "复验" else Path(path)
                try:
                    relative = Path(os.path.relpath(target, directory)).as_posix()
                except ValueError:
                    relative = target.as_posix()
                links.append(f"[{label}]({quote(relative, safe='/.:')})")
        explanation = "; ".join(row["reasons"] + ([row["configurationReason"]] if row["configurationReason"] else []))
        label = row['sampleId']
        if row.get("executionOrigin"):
            label += " / " + ("历史复用" if row["executionOrigin"] == "reused" else "本次新增")
        lines.append(f"| {_cell(label)} | {row['verification']} | {row['outcome']}：{row['executionStatus']} / {row['recordingOutcome']} / "
                     f"{row['assertionOutcome']} | {row['configurationMatch']} | {_cell(', '.join(row['changedFields']))} | "
                     f"{' / '.join(links)} {_cell(explanation)} |")
    return "\n".join(lines) + "\n"


def _load_report_inputs(source):
    metadata = {}
    header = load_json(source)
    require(isinstance(header, dict), "Experiment result must be an object")
    if "experimentResumeResultFormatVersion" in header:
        from .resume_report import load_resume_report
        saved, manifest, cases, plan_verification, sample_inputs, metadata = load_resume_report(source)
    else:
        saved, manifest, cases = _load_plan(source)
        plan_verification = _verify_plan_input(source.parent, saved, manifest, cases)
        sample_inputs = ((sample, source.parent, saved["batchId"], {}) for sample in saved["samples"])
    return saved, manifest, cases, plan_verification, sample_inputs, metadata


def _relocated_metadata(metadata):
    from .archive_paths import archive_context_active, physical
    if not archive_context_active():
        return metadata
    result = dict(metadata)
    for key in ("sourceExperimentResult", "sourceResumeResult", "sourceBatchResult"):
        if key in result:
            result[key] = str(physical(result[key]))
    if "batchResultPaths" in result:
        result["batchResultPaths"] = [str(physical(path)) for path in result["batchResultPaths"]]
    if "resumeChain" in result:
        result["resumeChain"] = [{**row, "resultPath": str(physical(row["resultPath"]))} for row in result["resumeChain"]]
    if "resumeVerification" in result:
        result["resumeVerification"] = dict(result["resumeVerification"])
        if "batchResumeResult" in result["resumeVerification"]:
            result["resumeVerification"]["batchResumeResult"] = str(physical(result["resumeVerification"]["batchResumeResult"]))
    return result


def generate_report(experiment_result_path, reports_root=None, *, _archive_bundle=None):
    source = Path(os.path.abspath(experiment_result_path))
    if source.is_dir() or source.name == "archive-manifest.json":
        from .archive_bundle import load_archive, verify_archive
        from .archive_paths import archive_read_context
        manifest_path = source / "archive-manifest.json" if source.is_dir() else source
        manifest, resolver = load_archive(manifest_path)
        manifest_path = resolver.payload_root.parent / "archive-manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        require(_same(parse_json(manifest_bytes.decode("utf-8")), manifest), "Archive manifest changed while loading")
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        verify_archive(manifest_path)
        require(hashlib.sha256(manifest_path.read_bytes()).hexdigest() == manifest_digest,
                "Archive manifest changed during semantic verification")
        output = Path(reports_root or ROOT / "runs" / "reports").resolve()
        require(not output.is_relative_to(manifest_path.parent), "Archive reports must be written outside the immutable bundle")
        info = {"archiveId": manifest["archiveId"], "manifestPath": str(manifest_path),
                "manifestSha256": manifest_digest, "verifiedFiles": len(manifest["files"])}
        with archive_read_context(resolver):
            return generate_report(manifest_path.parent / manifest["entryPath"], output, _archive_bundle=info)
    source = source.resolve()
    saved, manifest, cases, plan_verification, sample_inputs, metadata = _load_report_inputs(source)
    metadata = _relocated_metadata(metadata)
    rows, evaluations = [], []
    for sample, base, batch_id, provenance in sample_inputs:
        expected = {**cases[sample["caseEntryId"]], "configRef": sample["requestedConfiguration"]}
        row, fresh = _recheck(sample, expected, base, batch_id)
        row.update(_relocated_metadata(provenance))
        if fresh is not None:
            row["evaluationPath"] = f"evaluations/{len(rows) + 1:06}.json"
            evaluations.append((row["evaluationPath"], fresh))
        rows.append(row)
    groups = []
    for entry in manifest["cases"]:
        for config in manifest["configurations"]:
            subset = [row for row in rows if row["caseEntryId"] == entry["entryId"] and row["configurationId"] == config["configurationId"]]
            groups.append({"caseEntryId": entry["entryId"], "configurationId": config["configurationId"],
                           "summary": _summary(subset),
                           "matchedSummary": _summary([row for row in subset if row["verification"] == "verified" and row["configurationMatch"] == "matched"]),
                           "bySource": {source: _summary([row for row in subset if (row["source"] or "unknown") == source])
                                        for source in sorted({row["source"] or "unknown" for row in subset})}})
            if metadata:
                groups[-1]["byExecutionOrigin"] = {origin: _summary([row for row in subset if row["executionOrigin"] == origin])
                                                    for origin in ("reused", "new")}
    comparisons = []
    for entry in manifest["cases"]:
        for left, right in combinations(manifest["configurations"], 2):
            sources = {row["source"] for row in rows if row["caseEntryId"] == entry["entryId"] and row["source"] is not None
                       and row["configurationId"] in (left["configurationId"], right["configurationId"])}
            for provenance in sorted(sources or {"unknown"}):
                comparisons.append(_compare(left, right, entry["entryId"], provenance, rows, manifest["repetitions"]))
    report_id = str(uuid4())
    directory = Path(reports_root or ROOT / "runs" / "reports").resolve() / report_id
    report = {"comparisonReportFormatVersion": 1, "reportId": report_id, "generatedAt": datetime.now(timezone.utc).isoformat(),
              "reportDirectory": str(directory), "status": "generated", "experimentId": saved["experimentId"],
              "experimentName": saved["experimentName"], "sourceExperimentResult": str(source), "batchId": saved["batchId"],
              "configurations": manifest["configurations"],
              "planVerification": plan_verification, "executionOrder": _order_metadata(manifest),
              "repeatDistributions": _repeat_distributions(rows, manifest),
              "uncertaintyPolicy": {"version": 1, "confidenceLevel": LEVEL, "smallSampleWarningBelow": 30,
                                    "independenceVerified": False, "normalityVerified": False,
                                    "multiplicityAdjusted": False, "optionalStoppingAdjusted": False},
              "cases": [{"caseEntryId": key, "caseId": case["caseId"], "taskFingerprint": hashlib.sha256(
                  json.dumps({name: value for name, value in case.items() if name != "configRef"},
                             sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()} for key, case in cases.items()],
              "savedSummary": saved.get("summary"), "summary": _summary(rows), "groups": groups, "comparisons": comparisons,
              "verificationCounts": dict(Counter(row["verification"] for row in rows)), "samples": rows,
              "limitations": ["通过比例均公开分子和分母；缺失、取消、错误与跳过不补成零或普通答案失败。",
                              "配置差值仅使用同用例、同重复编号、同来源且实际配置核对匹配的子集；排除项可能引入选择偏差。",
                              "live / synthetic 是证据中的来源声明，不是签名；合成轨迹只能验证报告流程，不能证明模型表现。",
                              "95% 置信区间按用例 / 配置 / 来源与合格配对分别计算，不合并异质任务；只针对纳入子集，不能消除缺失或排除引起的选择偏差。",
                              "区间依赖独立重复等假设；Wilson 为近似区间，配对数值 t 区间另需差值近似正态。n<30 仅为小样本提示，不是有效性判据。",
                              "没有多重比较或可选停止校正，不提供显著性 / 因果 / 总体配置优胜结论，也不改变回归退出码。",
                              ("执行顺序按保存种子确定性随机化；种子不控制模型采样，不能保证样本独立或排除时间与服务波动。"
                               if "randomSeed" in manifest else "重复按固定顺序执行，未随机化，不能保证样本独立或排除时间与服务波动。"),
                              "调用计数为已结算录制事件，token 为已报告 usage；耗时含准备与清理，费用保持缺失。"]}
    if metadata:
        report.update(metadata)
        report["reusedSummary"] = _summary([row for row in rows if row["executionOrigin"] == "reused"])
        report["newlyExecutedSummary"] = _summary([row for row in rows if row["executionOrigin"] == "new"])
        report["limitations"].append("跨批次报告只读取所选续跑结果及其显式祖先链；不合并任意实验或自动查找后续续跑。"
                                     if metadata.get("comparisonReportFormatVersion") == 3 else
                                     "跨批次报告只整合一个显式实验续跑及其原批次 / 新批次；不合并任意实验或自动跟随再次续跑。")
    if _archive_bundle is not None:
        from .archive_bundle import load_archive
        manifest_path = Path(_archive_bundle["manifestPath"])
        require(hashlib.sha256(manifest_path.read_bytes()).hexdigest() == _archive_bundle["manifestSha256"],
                "Archive manifest changed while generating the report")
        load_archive(manifest_path)
        report["archiveBundle"] = dict(_archive_bundle)
        report["limitations"].append("报告从逐文件清单核验的只读归档生成，逻辑路径仅用于历史身份与指纹校验；不支持从搬迁归档调度续跑。")
    # All input checks and fresh evaluations finish before a new output directory is created.
    (directory / "evaluations").mkdir(parents=True, exist_ok=False)
    for name, fresh in evaluations:
        save_json(directory / name, fresh)
    save_json(directory / "report.json", report)
    with (directory / "report.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(render_markdown(report))
    return report
