"""Verify an experiment and continue only its provably unstarted samples."""
import hashlib
from contextlib import ExitStack
from pathlib import Path
import re
from uuid import UUID, uuid4

from .batch import _now
from .batch_lock import batch_lock
from .experiment import ORDER, _expand_samples
from .formats import fields, load_json, require, validate_batch, validate_case, validate_experiment
from .report import _load_plan as load_terminal_experiment, _verify_plan_input
from .resume import _check_resume_output_root, _digest, _execute_resume, _load_plan as load_batch_resume_plan, _path
from .runner import ROOT, save_json


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


def _load_inputs(source, batch_source):
    """Check archived identities and inputs without requiring the installed runner version."""
    directory = source.parent
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
    return saved, manifest, cases, batch_saved, identities, files, plan_verification


def _load_plan(source, batch_source, max_samples):
    directory = source.parent
    saved, _manifest, _original_cases, batch_saved, identities, files, plan_verification = _load_inputs(source, batch_source)
    batch_plan, saved_batch, cases = load_batch_resume_plan(batch_source, max_samples)
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
    plan = {"experimentResumePlanFormatVersion": 1, "valid": True, "modelCalled": False, "executionSupported": True,
            "sourceExperimentResult": str(source), "sourceExperimentId": saved["experimentId"],
            "sourceBatchResult": str(batch_source), "sourceBatchId": batch_saved["batchId"],
            "maxSamples": max_samples, "planVerification": plan_verification,
            "eligibleForResume": batch_plan["canResume"], "counts": batch_plan["counts"],
            "planFingerprint": {"version": 1, "sha256": _digest(payload)},
            "batchPlanFingerprint": batch_plan["planFingerprint"], "samples": samples,
            "reasons": batch_plan["reasons"], "sourceFilesSha256": hashes}
    return plan, batch_plan, saved_batch, cases


def plan_experiment_resume(result_path, *, max_samples=None):
    require(max_samples is None or type(max_samples) is int and max_samples > 0, "max_samples must be a positive integer")
    source = Path(result_path).resolve()
    if "experimentResumeResultFormatVersion" in load_json(source):
        from .experiment_resume_chain import plan_chain
        return plan_chain(source, max_samples=max_samples)
    batch_source = _binding(load_json(source), source.parent)
    # An uncreated batch cannot be assumed unstarted; never create a lock here.
    with batch_lock(batch_source.parent):
        return _load_plan(source, batch_source, max_samples)[0]


def resume_experiment(result_path, runs_root=None, modules_dir=None, cancel_after_stream=False, *, max_samples=None,
                      expected_plan_sha256=None, stop_after=None, stop_after_tokens=None):
    require(stop_after is None or type(stop_after) is int and stop_after > 0, "stop_after must be a positive integer")
    require(stop_after_tokens is None or type(stop_after_tokens) is int and stop_after_tokens > 0,
            "stop_after_tokens must be a positive integer")
    require(isinstance(expected_plan_sha256, str) and re.fullmatch(r"[0-9a-fA-F]{64}", expected_plan_sha256) is not None,
            "Resume requires the expected plan SHA-256 from a fresh preview")
    require(max_samples is None or type(max_samples) is int and max_samples > 0, "max_samples must be a positive integer")
    source = Path(result_path).resolve()
    if "experimentResumeResultFormatVersion" in load_json(source):
        from .experiment_resume_chain import execute_chain
        return execute_chain(source, runs_root, modules_dir, cancel_after_stream, max_samples=max_samples,
                             expected_plan_sha256=expected_plan_sha256, stop_after=stop_after, stop_after_tokens=stop_after_tokens)
    batch_source = _binding(load_json(source), source.parent)
    with ExitStack() as locks:
        locks.enter_context(batch_lock(batch_source.parent))
        plan, batch_plan, saved_batch, cases = _load_plan(source, batch_source, max_samples)
        require(plan["eligibleForResume"], "Experiment cannot resume: " + "; ".join(plan["reasons"] +
                [row["reason"] for row in plan["samples"] if row["disposition"] == "blocked"]))
        require(plan["planFingerprint"]["sha256"] == expected_plan_sha256.lower(), "Experiment resume plan fingerprint mismatch")
        _check_resume_output_root(runs_root, experiment=True)
        resume_id, batch_resume_id = str(uuid4()), str(uuid4())
        directory = Path(runs_root or ROOT / "runs" / "experiment-resumes").resolve() / resume_id
        directory.mkdir(parents=True, exist_ok=False)
        save_json(directory / "resume-plan.json", plan)
        # Reserve the downstream result path before it can claim or execute anything.
        report = {"experimentResumeResultFormatVersion": 1, "resumeId": resume_id, "resumeDirectory": str(directory),
                  "sourceExperimentResult": str(source), "sourceExperimentId": plan["sourceExperimentId"],
                  "sourceBatchResult": str(batch_source), "sourceBatchId": plan["sourceBatchId"],
                  "planFingerprint": plan["planFingerprint"], "batchPlanFingerprint": plan["batchPlanFingerprint"],
                  "maxSamples": max_samples, "stopAfter": stop_after, "counts": plan["counts"], "samplePlan": plan["samples"],
                  "stopAfterTokens": stop_after_tokens, "tokenUsage": None,
                  "startedAt": _now(), "finishedAt": None, "status": "running", "outcome": None,
                  "batchResumeResultPath": f"continuations/{batch_resume_id}/resume-result.json",
                  "newlyExecutedSummary": None}
        save_json(directory / "experiment-resume-result.json", report)
        result = _execute_resume(batch_source, batch_plan, saved_batch, cases, directory / "continuations",
                                 modules_dir, cancel_after_stream, resume_id=batch_resume_id, _lock_stack=locks,
                                 stop_after=stop_after, stop_after_tokens=stop_after_tokens)
        report.update(finishedAt=_now(), status=result["status"], stopReason=result["stopReason"], outcome=result["outcome"],
                      newlyExecutedSummary=result["newlyExecutedSummary"], tokenUsage=result["tokenUsage"])
        temporary = directory / f".experiment-resume-result-{uuid4()}.tmp"
        save_json(temporary, report)
        temporary.replace(directory / "experiment-resume-result.json")
        return report
