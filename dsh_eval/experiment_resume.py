"""Read-only experiment continuation preflight; never schedules remaining tasks."""
import hashlib
from pathlib import Path
from uuid import UUID

from .batch_lock import batch_lock
from .experiment import ORDER, _expand_samples
from .formats import fields, load_json, require, validate_batch, validate_case, validate_experiment
from .report import _load_plan as load_terminal_experiment, _verify_plan_input
from .resume import _digest, _load_plan as load_batch_resume_plan, _path
from .runner import validate_live_case


def _binding(saved, directory):
    require(isinstance(saved, dict) and type(saved.get("resumeSupportVersion")) is int
            and saved["resumeSupportVersion"] == 1,
            "Experiment lacks an explicit batch binding; legacy experiments cannot be resumed")
    binding = saved.get("batchBinding")
    fields(binding, ("batchId", "resultPath"))
    require(isinstance(binding["batchId"], str) and str(UUID(binding["batchId"])) == binding["batchId"],
            "Invalid reserved experiment batch identity")
    require(binding["resultPath"] == f"batches/{binding['batchId']}/batch-result.json", "Invalid experiment batch binding path")
    return _path(directory, binding["resultPath"])


def plan_experiment_resume(result_path, *, max_samples=None):
    require(max_samples is None or type(max_samples) is int and max_samples > 0, "max_samples must be a positive integer")
    source = Path(result_path).resolve()
    directory = source.parent
    batch_source = _binding(load_json(source), directory)
    # An uncreated batch cannot be assumed unstarted; never create a lock here.
    with batch_lock(batch_source.parent):
        saved = load_json(source)
        require(_binding(saved, directory) == batch_source, "Experiment batch binding changed during preflight")
        require(type(saved.get("experimentResultFormatVersion")) is int and saved["experimentResultFormatVersion"] == 1,
                "Unsupported experiment result format")
        require(isinstance(saved.get("experimentId"), str) and str(UUID(saved["experimentId"])) == saved["experimentId"]
                and Path(saved["experimentDirectory"]).resolve() == directory, "Experiment identity/directory mismatch")
        require(saved["order"] == ORDER and saved["status"] in ("running", "completed", "stopped", "error", "interrupted"),
                "Unsupported experiment scheduling state")
        manifest_path = _path(directory, saved["manifestPath"])
        manifest = validate_experiment(load_json(manifest_path))
        for key in ("experimentName", "repetitions", "configurations", "failurePolicy"):
            require(_digest(saved[key]) == _digest(manifest[key]), f"Frozen experiment/result {key} mismatch")
        count = len(manifest["cases"]) * len(manifest["configurations"]) * manifest["repetitions"]
        require(isinstance(saved["samples"], list) and len(saved["samples"]) == count, "Experiment sample count mismatch")
        case_paths = [_path(directory, entry["casePath"]) for entry in manifest["cases"]]
        inputs = [validate_case(load_json(path)) for path in case_paths]
        cases = {entry["entryId"]: case for entry, case in zip(manifest["cases"], inputs)}
        plan_verification = _verify_plan_input(directory, saved, manifest, cases)
        require(plan_verification["status"] == "verified", "Experiment resume requires a verified saved plan input")
        batch_saved = load_json(batch_source)
        require(batch_saved["batchId"] == saved["batchBinding"]["batchId"], "Reserved/observed batch identity mismatch")
        require(_digest(batch_saved["sourceManifest"]) == _digest(str(directory / "expanded.batch.json")),
                "Batch does not originate from the experiment's expansion")
        require(isinstance(batch_saved["entries"], list) and len(batch_saved["entries"]) == count, "Experiment/batch sample count mismatch")
        expanded_path = directory / "expanded.batch.json"
        expanded = validate_batch(load_json(expanded_path))
        require(expanded["batchName"] == manifest["experimentName"] and expanded["failurePolicy"] == manifest["failurePolicy"]
                and len(expanded["cases"]) == count, "Expanded experiment batch mismatch")
        if saved["status"] != "running":
            load_terminal_experiment(source)
        else:
            require(saved.get("batchId") in (None, batch_saved["batchId"]), "Active experiment batch identity mismatch")
            require(saved.get("batchResultPath") in (None, saved["batchBinding"]["resultPath"]),
                    "Active experiment batch path mismatch")
        files = {source, manifest_path, expanded_path, _path(directory, saved["planInputPath"]), *case_paths}
        identities = []
        for sample, row, entry, (identity, case) in zip(saved["samples"], batch_saved["entries"], expanded["cases"],
                                                      _expand_samples(manifest, inputs)):
            validate_live_case(case)
            require(isinstance(sample, dict) and isinstance(row, dict), "Experiment/batch sample must be an object")
            require(all(type(sample.get(key)) is type(value) and sample.get(key) == value for key, value in identity.items()),
                    "Experiment sample position/identity mismatch")
            require(row["entryId"] == entry["entryId"] == identity["sampleId"]
                    and row["caseId"] == identity["caseId"] and row["requestedConfiguration"] == case["configRef"],
                    "Expanded sample/batch identity or configuration mismatch")
            expanded_case_path = _path(directory, entry["casePath"])
            frozen_case_path = _path(batch_source.parent, row["casePath"])
            require(Path(row["sourceCasePath"]).resolve() == expanded_case_path, "Sample expansion source path mismatch")
            require(_digest(load_json(expanded_case_path)) == _digest(case)
                    and _digest(load_json(frozen_case_path)) == _digest(case),
                    "Expanded/frozen sample differs from original plan")
            if "requestedConfiguration" in sample:
                require(sample["requestedConfiguration"] == case["configRef"], "Saved sample requested configuration mismatch")
            if "status" in sample:
                for key in ("status", "caseRunId", "runId", "sessionId", "configuration", "source", "metrics", "outcome",
                            "executionStatus", "recordingOutcome", "assertionOutcome"):
                    require(_digest(sample.get(key)) == _digest(row.get(key)), f"Experiment/batch sample {key} mismatch")
            files.update((expanded_case_path, frozen_case_path))
            identities.append({**identity, "requestedConfiguration": case["configRef"], "sourceStatus": row["status"]})
        batch_plan, _saved_batch, _cases = load_batch_resume_plan(batch_source, max_samples)
        reused = {row["entryId"]: row for row in batch_plan["reusedEntries"]}
        blocked = {row["entryId"]: row["reason"] for row in batch_plan["blockedEntries"]}
        pending = set(batch_plan["pendingEntryIds"])
        samples = []
        for identity in identities:
            sample_id = identity["sampleId"]
            if sample_id in reused:
                row = reused[sample_id]
                samples.append({**identity, "disposition": "reuse", "verification": row["verification"],
                                "caseRunId": row["caseRunId"], "source": row["source"], "outcome": row["outcome"],
                                "recoveredCheckpoint": row["recoveredCheckpoint"]})
            elif sample_id in pending:
                samples.append({**identity, "disposition": "pending", "caseRunId": None, "source": None, "outcome": None})
            else:
                require(sample_id in blocked, "Unclassified experiment sample")
                samples.append({**identity, "disposition": "blocked", "reason": blocked[sample_id]})
        hashes = {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)}
        payload = {"version": 1, "sourceExperimentResult": str(source), "sourceFilesSha256": hashes,
                   "batchPlanFingerprint": batch_plan["planFingerprint"], "maxSamples": max_samples,
                   "samples": samples}
        return {"experimentResumePlanFormatVersion": 1, "valid": True, "modelCalled": False, "executionSupported": False,
                "sourceExperimentResult": str(source), "sourceExperimentId": saved["experimentId"],
                "sourceBatchResult": str(batch_source), "sourceBatchId": batch_saved["batchId"],
                "maxSamples": max_samples, "planVerification": plan_verification,
                "eligibleForResume": batch_plan["canResume"], "counts": batch_plan["counts"],
                "planFingerprint": {"version": 1, "sha256": _digest(payload)},
                "batchPlanFingerprint": batch_plan["planFingerprint"], "samples": samples,
                "reasons": batch_plan["reasons"], "sourceFilesSha256": hashes}
