"""Expand explicit repeated trials into the existing isolated sequential batch runner."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from .batch import run_batch
from .formats import load_json, require, validate_case, validate_experiment
from .metrics import summarize
from .runner import ROOT, save_json, validate_live_case

ORDER = "repeat-case-configuration"


def _checkpoint(directory, report):
    temporary = directory / f".experiment-result-{uuid4()}.tmp"
    save_json(temporary, report)
    temporary.replace(directory / "experiment-result.json")


def _load_experiment(experiment_path, max_samples=None):
    require(max_samples is None or type(max_samples) is int and max_samples > 0,
            "max_samples must be a positive integer")
    source = Path(experiment_path).resolve()
    manifest = validate_experiment(load_json(source))
    count = len(manifest["cases"]) * len(manifest["configurations"]) * manifest["repetitions"]
    require(max_samples is None or count <= max_samples,
            f"Planned sample count {count} exceeds max_samples {max_samples}")
    inputs = [validate_case(load_json(source.parent / entry["casePath"])) for entry in manifest["cases"]]
    # Check every case/configuration combination before creating output or starting a model.
    for case in inputs:
        for config in manifest["configurations"]:
            validate_live_case({**case, "configRef": config["configRef"]})
    return source, manifest, inputs


def _expand_samples(manifest, inputs):
    # Repeat blocks keep different configurations close in time; no randomization claim.
    index = 0
    for repeat in range(1, manifest["repetitions"] + 1):
        for entry, case in zip(manifest["cases"], inputs):
            for config in manifest["configurations"]:
                index += 1
                yield ({"sampleId": f"sample-{index:06}", "caseEntryId": entry["entryId"], "caseId": case["caseId"],
                        "configurationId": config["configurationId"], "repeatIndex": repeat},
                       {**case, "configRef": config["configRef"]})


def _plan_input(manifest, inputs, max_samples):
    return {"version": 1, "manifest": manifest, "cases": inputs, "maxSamples": max_samples, "order": ORDER}


def _plan_fingerprint(manifest, inputs, max_samples):
    payload = _plan_input(manifest, inputs, max_samples)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {"version": 1, "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def plan_experiment(experiment_path, *, max_samples=None):
    source, manifest, inputs = _load_experiment(experiment_path, max_samples)
    samples = [deepcopy({**sample, "requestedConfiguration": case["configRef"], "budget": case["budget"],
                         "recorderOverrides": case.get("recorder"),
                         **({"modelProviders": case["modelProviders"]} if "modelProviders" in case else {})})
               for sample, case in _expand_samples(manifest, inputs)]
    return {"experimentPlanFormatVersion": 1, "valid": True, "modelCalled": False,
            "experimentName": manifest["experimentName"], "sourceManifest": str(source), "maxSamples": max_samples,
            "planFingerprint": _plan_fingerprint(manifest, inputs, max_samples),
            "repetitions": manifest["repetitions"], "failurePolicy": manifest["failurePolicy"], "order": ORDER,
            "configurations": deepcopy(manifest["configurations"]),
            "counts": {"cases": len(inputs), "configurations": len(manifest["configurations"]), "samples": len(samples)},
            "estimates": {"modelCalls": None, "totalTokens": None, "cost": None}, "samples": samples}


def run_experiment(experiment_path, runs_root=None, modules_dir=None, cancel_after_stream=False, *, max_samples=None,
                   expected_plan_sha256=None, stop_after=None, stop_after_tokens=None):
    require(stop_after is None or type(stop_after) is int and stop_after > 0, "stop_after must be a positive integer")
    require(stop_after_tokens is None or type(stop_after_tokens) is int and stop_after_tokens > 0,
            "stop_after_tokens must be a positive integer")
    require(expected_plan_sha256 is None or isinstance(expected_plan_sha256, str)
            and re.fullmatch(r"[0-9a-fA-F]{64}", expected_plan_sha256) is not None,
            "expected_plan_sha256 must contain exactly 64 hexadecimal characters")
    expected = expected_plan_sha256.lower() if expected_plan_sha256 is not None else None
    source, manifest, inputs = _load_experiment(experiment_path, max_samples)
    fingerprint = _plan_fingerprint(manifest, inputs, max_samples)
    require(expected is None or expected == fingerprint["sha256"],
            f"Experiment plan fingerprint mismatch: expected {expected}, actual {fingerprint['sha256']}")
    experiment_id = str(uuid4())
    reserved_batch_id = str(uuid4())
    directory = Path(runs_root or ROOT / "runs" / "experiments").resolve() / experiment_id
    (directory / "inputs").mkdir(parents=True, exist_ok=False)
    (directory / "expanded").mkdir()
    save_json(directory / "plan-input.json", _plan_input(manifest, inputs, max_samples))
    frozen = deepcopy(manifest)
    for index, (entry, case) in enumerate(zip(frozen["cases"], inputs), 1):
        entry["casePath"] = f"inputs/{index:04}.case.json"
        save_json(directory / entry["casePath"], case)
    save_json(directory / "experiment.json", frozen)
    batch = {"batchFormatVersion": 1, "batchName": manifest["experimentName"],
             "failurePolicy": manifest["failurePolicy"], "cases": []}
    samples = []
    for sample, case in _expand_samples(manifest, inputs):
        path = f"expanded/{sample['sampleId']}.case.json"
        save_json(directory / path, case)
        batch["cases"].append({"entryId": sample["sampleId"], "casePath": path})
        samples.append(sample)
    save_json(directory / "expanded.batch.json", batch)
    report = {"experimentResultFormatVersion": 1, "experimentId": experiment_id,
              "experimentName": manifest["experimentName"], "experimentDirectory": str(directory),
              "sourceManifest": str(source), "manifestPath": "experiment.json", "repetitions": manifest["repetitions"],
              "maxSamples": max_samples, "stopAfter": stop_after, "stopAfterTokens": stop_after_tokens, "tokenUsage": None,
              "planFingerprint": fingerprint, "expectedPlanSha256": expected,
              "planInputPath": "plan-input.json",
              "resumeSupportVersion": 1,
              "batchBinding": {"batchId": reserved_batch_id,
                               "resultPath": f"batches/{reserved_batch_id}/batch-result.json"},
              "configurations": manifest["configurations"], "failurePolicy": manifest["failurePolicy"],
              "order": ORDER, "startedAt": datetime.now(timezone.utc).isoformat(),
              "finishedAt": None, "status": "running", "outcome": None, "batchId": None, "batchResultPath": None,
              "samples": samples, "summary": None, "groups": []}
    _checkpoint(directory, report)
    with ExitStack() as execution_locks:
        result = run_batch(directory / "expanded.batch.json", directory / "batches", modules_dir, cancel_after_stream,
                           batch_id=reserved_batch_id, _lock_stack=execution_locks,
                           stop_after=stop_after, stop_after_tokens=stop_after_tokens)
        require(result["batchId"] == reserved_batch_id, "Experiment/reserved batch identity mismatch")
        batch_directory = Path(result["batchDirectory"])
        prefix = batch_directory.relative_to(directory)
        require(len(result["entries"]) == len(samples), "Experiment/batch sample count mismatch")
        seen = set()
        for sample, row in zip(samples, result["entries"]):
            require(row["entryId"] == sample["sampleId"] and row["caseId"] == sample["caseId"],
                    "Experiment/batch sample association mismatch")
            expected = next(config["configRef"] for config in manifest["configurations"]
                            if config["configurationId"] == sample["configurationId"])
            require(row["requestedConfiguration"] == expected, "Experiment requested configuration mismatch")
            require(row["caseRunId"] is None or row["caseRunId"] not in seen, "Duplicate experiment caseRunId")
            if row["caseRunId"] is not None:
                seen.add(row["caseRunId"])
            sample.update(row)
            sample["configurationMatch"] = ("unknown" if row["configuration"] is None else
                                            "matched" if row["configuration"] == expected else "mismatched")
            for key in ("casePath", "caseDirectory", "evaluationPath", "evidencePath", "runtimeReport", "runDir"):
                if sample[key] is not None:
                    sample[key] = (prefix / sample[key]).as_posix()
        report.update(batchId=result["batchId"], batchResultPath=(prefix / "batch-result.json").as_posix(),
                      status=result["status"], stopReason=result["stopReason"], outcome=result["outcome"], tokenUsage=result["tokenUsage"],
                      finishedAt=datetime.now(timezone.utc).isoformat(), summary=summarize(samples))
        for entry in manifest["cases"]:
            for config in manifest["configurations"]:
                rows = [sample for sample in samples if sample["caseEntryId"] == entry["entryId"]
                        and sample["configurationId"] == config["configurationId"]]
                report["groups"].append({"caseEntryId": entry["entryId"], "configurationId": config["configurationId"],
                                         "requestedConfiguration": config["configRef"], "summary": summarize(rows)})
        _checkpoint(directory, report)
    return report
