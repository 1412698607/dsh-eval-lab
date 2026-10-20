"""Expand explicit repeated trials into the existing isolated sequential batch runner."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .batch import run_batch
from .formats import load_json, require, validate_case, validate_experiment
from .metrics import summarize
from .runner import ROOT, save_json, validate_live_case


def _checkpoint(directory, report):
    temporary = directory / f".experiment-result-{uuid4()}.tmp"
    save_json(temporary, report)
    temporary.replace(directory / "experiment-result.json")


def run_experiment(experiment_path, runs_root=None, modules_dir=None, cancel_after_stream=False):
    source = Path(experiment_path).resolve()
    manifest = validate_experiment(load_json(source))
    inputs = [validate_case(load_json(source.parent / entry["casePath"])) for entry in manifest["cases"]]
    # Check every case/configuration combination before creating output or starting a model.
    for case in inputs:
        for config in manifest["configurations"]:
            validate_live_case({**case, "configRef": config["configRef"]})
    experiment_id = str(uuid4())
    directory = Path(runs_root or ROOT / "runs" / "experiments").resolve() / experiment_id
    (directory / "inputs").mkdir(parents=True, exist_ok=False)
    (directory / "expanded").mkdir()
    frozen = deepcopy(manifest)
    for index, (entry, case) in enumerate(zip(frozen["cases"], inputs), 1):
        entry["casePath"] = f"inputs/{index:04}.case.json"
        save_json(directory / entry["casePath"], case)
    save_json(directory / "experiment.json", frozen)
    batch = {"batchFormatVersion": 1, "batchName": manifest["experimentName"],
             "failurePolicy": manifest["failurePolicy"], "cases": []}
    samples = []
    # Repeat blocks keep different configurations close in time; no randomization claim.
    for repeat in range(1, manifest["repetitions"] + 1):
        for entry, case in zip(manifest["cases"], inputs):
            for config in manifest["configurations"]:
                sample_id = f"sample-{len(samples) + 1:06}"
                path = f"expanded/{sample_id}.case.json"
                save_json(directory / path, {**case, "configRef": config["configRef"]})
                batch["cases"].append({"entryId": sample_id, "casePath": path})
                samples.append({"sampleId": sample_id, "caseEntryId": entry["entryId"], "caseId": case["caseId"],
                                "configurationId": config["configurationId"], "repeatIndex": repeat})
    save_json(directory / "expanded.batch.json", batch)
    report = {"experimentResultFormatVersion": 1, "experimentId": experiment_id,
              "experimentName": manifest["experimentName"], "experimentDirectory": str(directory),
              "sourceManifest": str(source), "manifestPath": "experiment.json", "repetitions": manifest["repetitions"],
              "configurations": manifest["configurations"], "failurePolicy": manifest["failurePolicy"],
              "order": "repeat-case-configuration", "startedAt": datetime.now(timezone.utc).isoformat(),
              "finishedAt": None, "status": "running", "outcome": None, "batchId": None, "batchResultPath": None,
              "samples": samples, "summary": None, "groups": []}
    _checkpoint(directory, report)
    result = run_batch(directory / "expanded.batch.json", directory / "batches", modules_dir, cancel_after_stream)
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
                  status=result["status"], stopReason=result["stopReason"], outcome=result["outcome"],
                  finishedAt=datetime.now(timezone.utc).isoformat(), summary=summarize(samples))
    for entry in manifest["cases"]:
        for config in manifest["configurations"]:
            rows = [sample for sample in samples if sample["caseEntryId"] == entry["entryId"]
                    and sample["configurationId"] == config["configurationId"]]
            report["groups"].append({"caseEntryId": entry["entryId"], "configurationId": config["configurationId"],
                                     "requestedConfiguration": config["configRef"], "summary": summarize(rows)})
    _checkpoint(directory, report)
    return report
