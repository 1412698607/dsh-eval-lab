"""Exercise the public regression CLI with independent, fully synthetic experiments."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from .experiment import plan_experiment, run_experiment
from .formats import load_json, parse_json, require
from .runner import ROOT, _process_options, save_json, stop_process_tree


SCENARIOS = (("no-regression", 0), ("regression", 1), ("incomplete", 2))
ARTIFACT_NAMES = frozenset(("no-regression.json", "regression.json", "incomplete.json", "summary.md", "index.json"))
COUNT_NAMES = ("regression", "improvement", "unchanged_passed", "unchanged_failed",
               "missing_in_baseline", "missing_in_candidate", "incompatible", "unavailable", "compared", "total")
COMPARISON_TIMEOUT = 60


def _digests(directory):
    return {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob("*")) if path.is_file()}


def _check_comparison(result, scenario, actual_code):
    expected_code = dict(SCENARIOS)[scenario]
    expected = dict.fromkeys(COUNT_NAMES, 0)
    expected.update(total=2, compared=1 if scenario == "incomplete" else 2)
    if scenario == "no-regression":
        expected["unchanged_passed"] = 2
    else:
        expected.update(regression=1, **{"unavailable" if scenario == "incomplete" else "unchanged_passed": 1})
    require(isinstance(result, dict) and result.get("regressionComparisonFormatVersion") == 1
            and result.get("status") == "compared" and result.get("modelCalled") is False,
            "Regression demo requires a normal, model-free comparison, not an input error")
    require(type(result.get("exitCode")) is int and actual_code == result["exitCode"] == expected_code,
            f"Unexpected regression CLI exit code for {scenario}")
    require(result.get("outcome") == ("passed", "failed", "unevaluable")[expected_code]
            and result.get("counts") == expected
            and result.get("hasRegressions") is (expected_code != 0)
            and result.get("comparability") == {"status": "incomplete" if expected_code == 2 else "comparable", "issues": []},
            f"Unexpected regression coverage or verdict for {scenario}")
    require(result["baseline"]["experimentId"] != result["candidate"]["experimentId"]
            and all(result[side]["planVerification"]["status"] == "verified" for side in ("baseline", "candidate")),
            "Regression demo requires independently recorded, verified experiment inputs")
    rows = result["samples"]
    require(isinstance(rows, list) and len(rows) == 2, "Regression demo lost its two planned pairs")
    for row in rows:
        for side in ("baseline", "candidate"):
            sample = row[side]
            if sample["status"] == "finished":
                require(sample["source"] == "synthetic" and sample["verification"] == "verified"
                        and sample["configurationMatch"] == "matched"
                        and sample["executionStatus"] == "completed" and sample["recordingOutcome"] == "complete",
                        "Regression demo lost its verified synthetic recording")
            else:
                require(scenario == "incomplete" and side == "candidate" and sample["status"] == "skipped",
                        "Unexpected unavailable regression demo input")
    for identity in ("caseRunId", "runId", "sessionId"):
        left = {row["baseline"][identity] for row in rows}
        right = {row["candidate"][identity] for row in rows if row["candidate"][identity] is not None}
        require(not left & right, "Regression demo inputs share an execution identity")


def _compare(baseline, candidate, output, scenario):
    command = [sys.executable, "-m", "dsh_eval", "--compare-baseline", str(baseline),
               "--candidate", str(candidate), "--output", str(output)]
    with subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", **_process_options()) as process:
        try:
            stdout, stderr = process.communicate(timeout=COMPARISON_TIMEOUT)
        finally:
            stop_process_tree(process)
    completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    try:
        result = parse_json(completed.stdout)
        _check_comparison(result, scenario, completed.returncode)
        require(load_json(output) == result, "Regression CLI output file differs from stdout")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as error:
        detail = completed.stderr[-2000:] or "(empty)"
        raise ValueError(f"Regression demo {scenario} comparison failed (exit {completed.returncode}): "
                         f"{error}; stderr tail: {detail}") from error
    return completed.returncode, result


def generate_regression_demo(output_dir=None):
    """Return zero-worthy demo results only when all three expected CLI outcomes match."""
    directory = Path(output_dir if output_dir is not None else ROOT / "runs/regression-demo" / str(uuid4()))
    directory.mkdir(parents=True, exist_ok=False)
    directory = directory.resolve()
    inputs, artifacts = directory / "inputs", directory / "artifacts"
    inputs.mkdir()
    artifacts.mkdir()
    config = {"provider": "synthetic", "model": "scripted", "profile": "headless",
              "pluginVersion": load_json(ROOT / "package.json")["version"]}
    case = load_json(ROOT / "fixtures/evaluation/rename-confirmation.case.json")
    case["configRef"] = config.copy()
    save_json(inputs / "rename-confirmation.case.json", case)
    manifest = {"experimentFormatVersion": 1, "experimentName": "synthetic-regression-gates", "repetitions": 2,
                "failurePolicy": "continue", "cases": [{"entryId": "confirmation", "casePath": "rename-confirmation.case.json"}],
                "configurations": [{"configurationId": "scripted", "configRef": config}]}
    manifest_path = inputs / "regression.experiment.json"
    save_json(manifest_path, manifest)
    plan = plan_experiment(manifest_path, max_samples=2)
    replies = {row["sampleId"]: "done" for row in plan["samples"]}
    scripted = {"baseline": replies.copy(), "no-regression": replies.copy(),
                "regression": {**replies, "sample-000001": "WRONG"},
                "incomplete": {**replies, "sample-000001": "WRONG"}}
    save_json(inputs / "scripted-replies.json", scripted)
    paths = {}
    for name, answers in scripted.items():
        experiment = run_experiment(manifest_path, directory / "experiments", max_samples=2,
                                    expected_plan_sha256=plan["planFingerprint"]["sha256"],
                                    stop_after=1 if name == "incomplete" else None, _synthetic_replies=answers)
        require(experiment.get("modelCalled") is False and experiment["executionMode"] == "synthetic",
                "Regression demo must not execute live models")
        require(experiment["status"] == ("stopped" if name == "incomplete" else "completed"),
                "Synthetic experiment did not reach its expected terminal state")
        paths[name] = Path(experiment["experimentDirectory"]) / "experiment-result.json"

    source_roots = (inputs, directory / "experiments")
    before = {root.name: _digests(root) for root in source_roots}
    scenarios = []
    for name, code in SCENARIOS:
        output = artifacts / (name + ".json")
        actual_code, result = _compare(paths["baseline"], paths[name], output, name)
        scenarios.append({"id": name, "expectedExitCode": code, "actualExitCode": actual_code,
                          "outcome": result["outcome"], "counts": result["counts"],
                          "comparisonPath": str(output), "candidatePath": str(paths[name])})
    require(before == {root.name: _digests(root) for root in source_roots}, "Regression comparison modified its source archives")
    index = {"regressionDemoFormatVersion": 1, "demoId": str(uuid4()), "generatedAt": datetime.now(timezone.utc).isoformat(),
             "status": "completed", "source": "synthetic", "modelCalled": False, "outputDirectory": str(directory),
             "artifactsDirectory": str(artifacts), "baselinePath": str(paths["baseline"]),
             "sourceArchivesUnchanged": True, "archiveFilesChecked": sum(len(value) for value in before.values()),
             "archiveSha256": before, "scenarios": scenarios}
    lines = ["# Synthetic regression gate examples", "", "source=synthetic; modelCalled=false.", "",
             "| Scenario | Expected / actual exit | Outcome | Compared / planned | Regressions | Unavailable |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in scenarios:
        counts = row["counts"]
        lines.append(f"| `{row['id']}.json` | {row['expectedExitCode']} / {row['actualExitCode']} | "
                     f"{row['outcome']} | {counts['compared']} / {counts['total']} | {counts['regression']} | {counts['unavailable']} |")
    lines.extend(["", "Demo success means all expected exit codes and evidence checks matched, not that all tasks passed.",
                  "The incomplete example retains one confirmed regression and one unstarted sample; exit 2 takes priority.",
                  "Real gates must propagate the comparison CLI's original exit code; this demo only checks fixed examples.",
                  "These synthetic observations do not measure model performance. Source archive SHA-256 values stayed unchanged.",
                  "Only these five generated comparison/summary files are CI artifacts. Source archives are not included.", ""])
    with (artifacts / "summary.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines))
    save_json(artifacts / "index.json", index)
    require({path.name for path in artifacts.iterdir()} == ARTIFACT_NAMES, "Unexpected regression demo artifact member")
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check fixed synthetic examples of the public regression gate; never calls a model")
    parser.add_argument("--output-dir", help="New output directory; an existing path is never overwritten")
    args = parser.parse_args(argv)
    try:
        index = generate_regression_demo(args.output_dir)
        print(json.dumps(index, ensure_ascii=False), flush=True)
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, subprocess.SubprocessError) as error:
        print(json.dumps({"regressionDemoFormatVersion": 1, "source": "synthetic", "modelCalled": False,
                          "status": "error", "error": str(error)}, ensure_ascii=False), flush=True)
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
