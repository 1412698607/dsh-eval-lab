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
from .experiment import ORDER, _plan_fingerprint
from .formats import fields, load_json, nonempty, parse_json, require, validate_case, validate_experiment
from .metrics import METRICS, empty_metrics, number, summarize
from .runner import ROOT, save_json


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
    for key in METRICS:
        values = [(row.get("metrics") or {}).get(key) for row in rows]
        observed = [value for value in values if number(value)]
        result["metrics"][key].update(observedMin=min(observed) if observed else None,
                                      observedMax=max(observed) if observed else None)
    return result


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
    require(saved["order"] == "repeat-case-configuration", "Unsupported experiment sample order")
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
    positions = ((entry["entryId"], config["configurationId"], repeat)
                 for repeat in range(1, manifest["repetitions"] + 1)
                 for entry in manifest["cases"] for config in manifest["configurations"])
    seen_samples, seen_runs, seen_sessions, seen_recordings = set(), set(), set(), set()
    for sample, row, position in zip(saved["samples"], batch["entries"], positions):
        require(isinstance(sample, dict) and isinstance(row, dict), "Sample must be an object")
        require(type(sample["repeatIndex"]) is int
                and (sample["caseEntryId"], sample["configurationId"], sample["repeatIndex"]) == position,
                "Experiment sample position mismatch")
        require(nonempty(sample["sampleId"]) and sample["sampleId"] not in seen_samples
                and sample["sampleId"] == sample["entryId"] == row["entryId"], "Duplicate or mismatched sample identity")
        seen_samples.add(sample["sampleId"])
        config = next(item["configRef"] for item in manifest["configurations"] if item["configurationId"] == position[1])
        require(_same(sample["requestedConfiguration"], config)
                and sample["caseId"] == cases[position[0]]["caseId"], "Sample requested configuration/case mismatch")
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
    require(payload["order"] == ORDER, "Unsupported plan input order")
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
               sourceEvidencePath=None, evaluationPath=None,
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
                       outcome=fresh["outcome"], metrics=fresh["metrics"])
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as error:
            row.update(verification="unavailable" if sample["status"] == "error" else "rejected", reasons=[str(error)])
            fresh = None
    row["changedFields"] = [key for key, value in row["saved"].items() if not _same(value, row[key])]
    return row, fresh


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
                  "rateDifferences": {}, "metrics": {}}
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


def generate_report(experiment_result_path, reports_root=None):
    source = Path(experiment_result_path).resolve()
    metadata = {}
    if "experimentResumeResultFormatVersion" in load_json(source):
        from .resume_report import load_resume_report
        saved, manifest, cases, plan_verification, sample_inputs, metadata = load_resume_report(source)
    else:
        saved, manifest, cases = _load_plan(source)
        plan_verification = _verify_plan_input(source.parent, saved, manifest, cases)
        sample_inputs = ((sample, source.parent, saved["batchId"], {}) for sample in saved["samples"])
    rows, evaluations = [], []
    for sample, base, batch_id, provenance in sample_inputs:
        expected = {**cases[sample["caseEntryId"]], "configRef": sample["requestedConfiguration"]}
        row, fresh = _recheck(sample, expected, base, batch_id)
        row.update(provenance)
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
              "planVerification": plan_verification,
              "cases": [{"caseEntryId": key, "caseId": case["caseId"], "taskFingerprint": hashlib.sha256(
                  json.dumps({name: value for name, value in case.items() if name != "configRef"},
                             sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()} for key, case in cases.items()],
              "savedSummary": saved.get("summary"), "summary": _summary(rows), "groups": groups, "comparisons": comparisons,
              "verificationCounts": dict(Counter(row["verification"] for row in rows)), "samples": rows,
              "limitations": ["通过比例均公开分子和分母；缺失、取消、错误与跳过不补成零或普通答案失败。",
                              "配置差值仅使用同用例、同重复编号、同来源且实际配置核对匹配的子集；排除项可能引入选择偏差。",
                              "live / synthetic 是证据中的来源声明，不是签名；合成轨迹只能验证报告流程，不能证明模型表现。",
                              "样本量、观测范围与指标覆盖只描述本次实验；未计算置信区间、显著性或配置优胜结论。",
                              "重复按固定顺序执行，未随机化，不能保证样本独立或排除时间与服务波动。",
                              "调用计数为已结算录制事件，token 为已报告 usage；耗时含准备与清理，费用保持缺失。"]}
    if metadata:
        report.update(metadata)
        report["reusedSummary"] = _summary([row for row in rows if row["executionOrigin"] == "reused"])
        report["newlyExecutedSummary"] = _summary([row for row in rows if row["executionOrigin"] == "new"])
        report["limitations"].append("跨批次报告只读取所选续跑结果及其显式祖先链；不合并任意实验或自动查找后续续跑。"
                                     if metadata.get("comparisonReportFormatVersion") == 3 else
                                     "跨批次报告只整合一个显式实验续跑及其原批次 / 新批次；不合并任意实验或自动跟随再次续跑。")
    # All input checks and fresh evaluations finish before a new output directory is created.
    (directory / "evaluations").mkdir(parents=True, exist_ok=False)
    for name, fresh in evaluations:
        save_json(directory / name, fresh)
    save_json(directory / "report.json", report)
    with (directory / "report.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(render_markdown(report))
    return report
