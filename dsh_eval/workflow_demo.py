"""Rebuild a fixed synthetic workflow with the normal recorder, scorer and reports."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

from .evaluate import evaluate
from .experiment import plan_experiment, run_experiment
from .experiment_assertion_preview import preview_experiment_assertions
from .formats import load_json, require
from .report import generate_report
from .runner import ROOT, run_synthetic_case, save_json


FIXTURES = ROOT / "fixtures/evaluation"
NAMES = ("rename-confirmation", "rename-timeout-retry")


def _digests(directory):
    return {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob("*")) if path.is_file()}


def _check_task(result, *, skipped=False):
    require((result["source"], result["execution"]["status"], result["recording"]["outcome"], result["outcome"])
            == ("synthetic", "completed", "complete", "unevaluable" if skipped else "passed"),
            "Synthetic workflow did not produce the expected task classification")
    diagnostic = result.get("assertionDiagnostics", {})
    require(diagnostic.get("assertionDiagnosticsFormatVersion") == 1,
            "Synthetic workflow is missing structured assertion diagnostics")
    diagnostics = {row["id"]: row for row in diagnostic["results"]}
    if skipped:
        missing = [row["id"] for row in result["assertions"]["results"] if row["outcome"] == "insufficient_evidence"]
        require(missing == ["source-still-present", "target-still-missing", "retry", "verify"]
                and sum(row["outcome"] == "passed" for row in result["assertions"]["results"]) == 6,
                "Skipped-readback example did not retain the expected six passes and four missing steps")
        require(diagnostics["source-still-present"]["reasonCode"] == "tool_evidence_missing",
                "Skipped-readback example did not identify its first missing step")
        for key, predecessor in (("target-still-missing", "source-still-present"),
                                 ("retry", "target-still-missing"), ("verify", "retry")):
            require(diagnostics[key]["reasonCode"] == "dependency_not_passed"
                    and diagnostics[key]["blockedBy"] == [predecessor],
                    "Skipped-readback example did not retain its direct dependency chain")
        require(all(diagnostics[key].get("observedMatches") for key in ("retry", "verify")),
                "Skipped-readback example lost the observed successful retry or final readback")
    else:
        require(all(row["reasonCode"] == "matched" for row in diagnostic["results"]),
                "Complete workflow did not retain a fully matched evidence chain")


def generate_workflow(output_dir=None):
    """Create one new archive; expected negative examples are a successful demo run."""
    directory = Path(output_dir if output_dir is not None else ROOT / "runs/workflow" / str(uuid4())).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    inputs = directory / "inputs"
    inputs.mkdir()
    config = {"provider": "synthetic", "model": "scripted", "profile": "headless",
              "pluginVersion": load_json(ROOT / "package.json")["version"]}
    cases = {}
    for name in NAMES:
        case = load_json(FIXTURES / (name + ".case.json"))
        case["configRef"] = config.copy()
        cases[name] = case
        save_json(inputs / (name + ".case.json"), case)
    skipped_case = deepcopy(cases["rename-timeout-retry"])
    skipped_case["caseId"] = "rename-timeout-skip-readbacks"
    save_json(inputs / "skip-readbacks.case.json", skipped_case)

    # Script and replies are fixed before execution; scoring never supplies the behavior.
    complete = run_synthetic_case(inputs / "rename-timeout-retry.case.json", directory / "tasks", final_text="done")
    _check_task(complete)
    skipped = run_synthetic_case(inputs / "skip-readbacks.case.json", directory / "tasks", final_text="done")
    _check_task(skipped, skipped=True)
    manifest = load_json(FIXTURES / "rename-confirmation.experiment.json")
    manifest["configurations"] = [{"configurationId": "scripted", "configRef": config}]
    manifest_path = inputs / "workflow.experiment.json"
    save_json(manifest_path, manifest)
    plan = plan_experiment(manifest_path, max_samples=4)
    replies = {row["sampleId"]: ("**done**" if row["sampleId"] == "sample-000002" else "done")
               for row in plan["samples"]}
    save_json(inputs / "scripted-replies.json", replies)
    experiment = run_experiment(manifest_path, directory / "experiments", max_samples=4,
                                expected_plan_sha256=plan["planFingerprint"]["sha256"], _synthetic_replies=replies)
    require(experiment["status"] == "completed" and experiment["summary"]["outcomes"]
            == {"passed": 4, "failed": 0, "unevaluable": 0}, "Synthetic matrix did not complete with four passes")
    experiment_path = Path(experiment["experimentDirectory"]) / "experiment-result.json"
    rules = {}
    for entry in manifest["cases"]:
        rules[entry["entryId"]] = deepcopy(cases[Path(entry["casePath"]).name.removesuffix(".case.json")]["assertions"])
        next(row for row in rules[entry["entryId"]] if row["id"] == "answer").pop("match")
    rule_map_path = inputs / "strict-rule-map.json"
    save_json(rule_map_path, {"assertionRuleMapFormatVersion": 1, "cases": rules})

    archive_roots = (directory / "tasks", directory / "experiments", inputs)
    before = {root.name: _digests(root) for root in archive_roots}
    for saved, is_skipped in ((complete, False), (skipped, True)):
        association = saved["association"]
        fresh = evaluate(association["casePath"], association["evidencePath"])
        _check_task(fresh, skipped=is_skipped)
        require(fresh["assertions"] == saved["assertions"], "Independent task recheck changed assertion results")
    report = generate_report(experiment_path, directory / "reports")
    require(report["verificationCounts"] == {"verified": 4}
            and all(row["source"] == "synthetic" and row["configurationMatch"] == "matched"
                    and row["outcome"] == "passed" for row in report["samples"]),
            "Independent experiment report did not verify all four scripted samples")
    causes = report["summary"]["assertionCauseSummary"]
    require((causes["plannedSamples"], causes["availableSamples"], causes["missingSamples"]) == (4, 4, 0)
            and causes["byRole"]["required"]["rootAffectedSamples"] == 0
            and causes["byRole"]["required"]["blockedAffectedSamples"] == 0
            and causes["byRole"]["diagnostic"]["rootReasons"] == [
                {"reasonCode": "final_text_mismatch", "affectedSamples": 1, "sampleIds": ["sample-000002"]}],
            "Experiment cause summary did not preserve the one diagnostic format deviation")
    preview = preview_experiment_assertions(experiment_path, rule_map_path)
    require(preview["summary"] == {"plannedSamples": 4, "comparedSamples": 4, "passToFail": 1,
                                  "failToPass": 0, "unchangedPassed": 3, "unchangedFailed": 0, "inconclusive": 0},
            "Candidate rules did not flip exactly one of four samples")
    require([row["sampleId"] for row in preview["samples"] if row["transition"] == "passToFail"] == ["sample-000002"],
            "Candidate rules changed the wrong sample")
    preview_path = directory / "experiment-assertion-preview.json"
    save_json(preview_path, preview)
    require(before == {root.name: _digests(root) for root in archive_roots}, "Offline rechecks modified a source archive")
    save_json(directory / "archive-sha256.json", before)

    index = {"workflowDemoFormatVersion": 1, "workflowId": str(uuid4()), "workflowName": "可重复合成工作流演示",
             "generatedAt": datetime.now(timezone.utc).isoformat(), "source": "synthetic", "modelCalled": False,
             "status": "completed", "outputDirectory": str(directory), "experimentPath": str(experiment_path),
             "reportPath": str(Path(report["reportDirectory"]) / "report.json"),
             "sourceArchivesUnchanged": True, "archiveFilesChecked": sum(len(files) for files in before.values()),
             "scenarios": [
                 {"id": "complete", "title": "1. 完整重试步骤", "outcome": complete["outcome"],
                  "description": "超时后读源、确认目标缺失，再重试并读回；全部断言通过。",
                  "evaluationPath": str(Path(complete["association"]["evidencePath"]).with_name("evaluation.json"))},
                 {"id": "skip-readbacks", "title": "2. 跳过中间读回", "outcome": skipped["outcome"],
                  "description": "最终文件与回复正确；6 项通过、4 项缺证，首项为 source-still-present。",
                  "evaluationPath": str(Path(skipped["association"]["evidencePath"]).with_name("evaluation.json"))},
                 {"id": "rule-impact", "title": "3. 四样本规则影响", "outcome": preview["status"],
                  "description": "原规则四项通过；必需精确 done 使唯一加粗样本翻转，其余三项仍通过。",
                  "previewPath": str(preview_path)}]}
    lines = ["# 合成工作流演示", "", "source=synthetic；modelCalled=false。先在浏览页选择“工作流演示”。", ""]
    for row in index["scenarios"]:
        target = Path(row.get("evaluationPath", row.get("previewPath"))).relative_to(directory).as_posix()
        lines.extend([f"- [{row['title']}]({target})：{row['outcome']}。{row['description']}", ""])
    lines.extend(["归档复验与规则预览前后 SHA-256 保持一致，完整摘要见 archive-sha256.json。", "",
                  "浏览服务在前台运行，按 Ctrl+C 停止；关闭页面不会停止服务。", ""])
    (directory / "index.md").write_text("\n".join(lines), encoding="utf-8")
    save_json(directory / "workflow-index.json", index)
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate and browse a fixed synthetic workflow; never calls a model")
    parser.add_argument("--generate-only", action="store_true", help="Generate, independently recheck and exit without serving")
    parser.add_argument("--output-dir", help="New output directory; an existing path is never overwritten")
    parser.add_argument("--port", type=int, default=0, help="Loopback viewer port; default selects a free port")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    try:
        index = generate_workflow(args.output_dir)
        if not args.generate_only:
            from .browser import create_server
            with create_server(Path(index["outputDirectory"]) / "inputs", index["outputDirectory"], args.port) as server:
                print(json.dumps({**index, "url": server.browser_url, "readOnly": True, "stop": "Ctrl+C"}, ensure_ascii=False), flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
        else:
            print(json.dumps(index, ensure_ascii=False), flush=True)
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"workflowDemoFormatVersion": 1, "source": "synthetic", "modelCalled": False,
                          "status": "error", "error": str(error)}, ensure_ascii=False), flush=True)
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
