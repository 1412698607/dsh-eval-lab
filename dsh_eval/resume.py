"""Verify a stopped scheduler and execute only its provably unstarted cases."""
from copy import deepcopy
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from uuid import UUID, uuid4

from .batch import _cleanup_confirmed, _now, input_fingerprint, run_batch
from .batch_lock import batch_lock
from .evaluate import evaluate
from .formats import load_json, nonempty, require, validate_batch
from .metrics import summarize
from .runner import ROOT, save_json, validate_live_case

CLAIM_NAME = ".batch-resume-claim.json"


def _check_resume_output_root(runs_root, *, experiment=False):
    """Reject the known Windows installer path limit before allocating or claiming."""
    if sys.platform != "win32":
        return
    root = Path(runs_root or ROOT / "runs" / ("experiment-resumes" if experiment else "resumes")).resolve()
    reserved = str(UUID(int=0))
    directory = root / reserved
    if experiment:
        directory = directory / "continuations" / reserved
    operation = (directory / "batches" / reserved / "cases" / reserved / "home" / "profiles" / "headless"
                 / ".plugin-manager" / "logs" / "operation-XXXXXX")
    length = len(str(operation).encode("utf-16-le")) // 2
    require(length < 248, f"Windows Harness preparation path requires {length} UTF-16 code units (limit 247); "
            "choose a shorter --runs-root; no continuation was claimed")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _path(directory, value):
    require(nonempty(value) and "\\" not in value and ":" not in value
            and not PurePosixPath(value).is_absolute()
            and all(part not in ("", ".", "..") for part in value.split("/")), "Resume paths must be contained relative POSIX paths")
    path = (directory / value).resolve()
    require(path.is_relative_to(directory), "Resume input escapes the batch directory")
    return path


def _verify_finished(directory, saved, row, case, files):
    case_run_id = row.get("caseRunId")
    require(nonempty(case_run_id) and str(UUID(case_run_id)) == case_run_id, "Unknown execution identity")
    require(row.get("caseDirectory") == f"cases/{case_run_id}", "Case directory/identity mismatch")
    case_directory = _path(directory, row["caseDirectory"])
    paths = {name: _path(directory, f"{row['caseDirectory']}/{name}")
             for name in ("case.json", "evidence.json", "evaluation.json", "runtime.json")}
    require(load_json(paths["case.json"]) == case, "Executed case differs from frozen input")
    evidence = load_json(paths["evidence.json"])
    require(evidence.get("runtimeReport") == "runtime.json", "Unexpected runtime report path")
    require(nonempty(evidence.get("runDir")), "Missing original recording path")
    recorded_path = Path(evidence["runDir"])
    # Evidence v2 retains the runner's native path spelling on Windows.
    run_directory = (case_directory / recorded_path).resolve()
    require(run_directory.is_relative_to(case_directory), "Original recording escapes its execution directory")
    require(run_directory.is_dir(), "Missing original recording")
    runtime = load_json(paths["runtime.json"])
    require(type(runtime.get("runtimeFormatVersion")) is int and runtime["runtimeFormatVersion"] == 1
            and runtime.get("caseRunId") == case_run_id and _cleanup_confirmed(runtime), "Execution cleanup is unconfirmed")
    host = runtime["host"]
    require(host.get("childClosed") is True and host.get("exitCode") == 0
            and host.get("forceStopped") is False, "Normal child exit is unconfirmed")
    fresh = evaluate(paths["case.json"], paths["evidence.json"])
    require(fresh.get("batchId") == saved["batchId"] and fresh["caseRunId"] == case_run_id
            and fresh["caseId"] == case["caseId"], "Case/batch association mismatch")
    require(fresh["recording"]["outcome"] == "complete" and fresh["execution"]["status"] == "completed"
            and fresh["outcome"] in ("passed", "failed"), "Original execution cannot be reused")
    previous = load_json(paths["evaluation.json"])
    require(previous.get("recording", {}).get("outcome") == fresh["recording"]["outcome"],
            "Saved recording result differs from fresh inspection")
    for key in ("caseRunId", "caseId", "case", "batchId", "source", "configuration", "budgetEnforcement",
                "execution", "assertions", "metrics", "outcome", "association"):
        require(_digest(previous.get(key)) == _digest(fresh.get(key)), f"Fresh evaluation differs in {key}")
    expected = {"runId": fresh["association"]["runId"], "sessionId": fresh["association"]["sessionId"],
                "configuration": fresh["configuration"], "source": fresh["source"], "metrics": fresh["metrics"],
                "executionStatus": fresh["execution"]["status"], "recordingOutcome": fresh["recording"]["outcome"],
                "assertionOutcome": fresh["assertions"]["outcome"], "outcome": fresh["outcome"]}
    if row["status"] == "finished":
        for key, value in expected.items():
            require(_digest(row.get(key)) == _digest(value), f"Batch/evaluation {key} mismatch")
        for key, filename in (("evaluationPath", "evaluation.json"), ("evidencePath", "evidence.json"),
                              ("runtimeReport", "runtime.json")):
            require(_path(directory, row[key]) == paths[filename], f"Unexpected {key}")
        require(_path(directory, row["runDir"]) == run_directory, "Recording path mismatch")
    files.update(paths.values())
    for path in run_directory.iterdir():
        require(path.is_file() and path.resolve().is_relative_to(directory), "Unexpected recording member")
        files.add(path)
    return {**deepcopy(row), **expected, "status": "finished", "verification": "verified",
            "recoveredCheckpoint": row["status"] == "running"}


def _load_plan(source, max_samples):
    require(max_samples is None or type(max_samples) is int and max_samples > 0, "max_samples must be a positive integer")
    directory = source.parent
    saved = load_json(source)
    require(type(saved.get("batchResultFormatVersion")) is int and saved["batchResultFormatVersion"] == 1,
            "Unsupported batch result format")
    require(type(saved.get("resumeSupportVersion")) is int and saved["resumeSupportVersion"] == 1,
            "Batch lacks resume coordination metadata; legacy batches cannot be resumed")
    require(str(UUID(saved["batchId"])) == saved["batchId"] and Path(saved["batchDirectory"]).resolve() == directory,
            "Batch identity/directory mismatch")
    require(saved["mode"] == "sequential" and saved["status"] in ("running", "completed", "interrupted", "error", "stopped"),
            "Unsupported batch scheduling state")
    manifest_path = _path(directory, saved["manifestPath"])
    manifest = validate_batch(load_json(manifest_path))
    require(saved["batchName"] == manifest["batchName"] and saved["failurePolicy"] == manifest["failurePolicy"],
            "Frozen batch/result mismatch")
    require(isinstance(saved["entries"], list) and len(saved["entries"]) == len(manifest["cases"]), "Batch entry count mismatch")
    files = {source, manifest_path}
    cases, reused, pending, blocked = {}, [], [], []
    seen_runs = set()
    for row, entry in zip(saved["entries"], manifest["cases"]):
        require(row["entryId"] == entry["entryId"] and row["casePath"] == entry["casePath"], "Batch entry position/path mismatch")
        case_path = _path(directory, entry["casePath"])
        case = validate_live_case(load_json(case_path))
        files.add(case_path)
        require(row["caseId"] == case["caseId"] and row["requestedConfiguration"] == case["configRef"],
                "Frozen case/requested configuration mismatch")
        cases[entry["entryId"]] = case
        require(row["status"] in ("pending", "skipped", "finished", "running", "error"), "Unsupported entry state")
        if row["status"] in ("pending", "skipped"):
            require(all(row.get(key) is None for key in ("caseRunId", "caseDirectory", "runId", "sessionId", "configuration",
                    "evaluationPath", "evidencePath", "runtimeReport", "runDir", "outcome", "source", "metrics",
                    "executionStatus", "recordingOutcome", "assertionOutcome")), "Unstarted entry contains execution facts")
            pending.append(entry["entryId"])
        elif row["status"] in ("finished", "running"):
            try:
                require(row.get("caseRunId") not in seen_runs, "Duplicate case execution identity")
                verified = _verify_finished(directory, saved, row, case, files)
                seen_runs.add(row["caseRunId"])
                reused.append(verified)
            except (OSError, ValueError, KeyError, TypeError) as error:
                blocked.append({"entryId": entry["entryId"], "reason": str(error)})
        else:
            blocked.append({"entryId": entry["entryId"], "reason": "Previous execution state is unknown"})
    reasons = []
    if (directory / CLAIM_NAME).exists():
        reasons.append("Source batch already has a continuation claim")
    if saved.get("stopReason") == "cleanup_unconfirmed":
        reasons.append("Previous scheduler could not confirm cleanup")
    if manifest["failurePolicy"] == "stop" and (saved.get("stopReason") == "failure_policy"
            or any(row["outcome"] != "passed" for row in reused)):
        reasons.append("Original failure policy prohibits further execution")
    if not pending:
        reasons.append("No unstarted entries remain")
    require(saved.get("inputFingerprint") == input_fingerprint(manifest, list(cases.values())),
            "Frozen batch input fingerprint mismatch")
    require(max_samples is None or len(pending) <= max_samples, "Remaining task count exceeds max_samples")
    hashes = {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)}
    payload = {"version": 1, "sourceBatchResult": str(source), "sourceFilesSha256": hashes,
               "pendingEntryIds": pending, "reusedEntryIds": [row["entryId"] for row in reused], "maxSamples": max_samples}
    plan = {"batchResumePlanFormatVersion": 1, "valid": True, "modelCalled": False,
            "sourceBatchResult": str(source), "sourceBatchId": saved["batchId"], "maxSamples": max_samples,
            "planFingerprint": {"version": 1, "sha256": _digest(payload)}, "canResume": bool(pending) and not blocked and not reasons,
            "counts": {"original": len(cases), "reused": len(reused), "newSamples": len(pending), "blocked": len(blocked)},
            "pendingEntryIds": pending, "reusedEntries": reused, "blockedEntries": blocked, "reasons": reasons,
            "sourceFilesSha256": hashes}
    return plan, saved, cases


def plan_batch_resume(result_path, *, max_samples=None):
    source = Path(result_path).resolve()
    with batch_lock(source.parent):
        return _load_plan(source, max_samples)[0]


def resume_batch(result_path, runs_root=None, modules_dir=None, cancel_after_stream=False, *, max_samples=None,
                 expected_plan_sha256=None, stop_after=None, stop_after_tokens=None):
    require(stop_after is None or type(stop_after) is int and stop_after > 0, "stop_after must be a positive integer")
    require(stop_after_tokens is None or type(stop_after_tokens) is int and stop_after_tokens > 0,
            "stop_after_tokens must be a positive integer")
    require(isinstance(expected_plan_sha256, str) and re.fullmatch(r"[0-9a-fA-F]{64}", expected_plan_sha256) is not None,
            "Resume requires the expected plan SHA-256 from a fresh preview")
    source = Path(result_path).resolve()
    with batch_lock(source.parent):
        plan, saved, cases = _load_plan(source, max_samples)
        require(plan["canResume"], "Batch cannot resume: " + "; ".join(plan["reasons"] + [row["reason"] for row in plan["blockedEntries"]]))
        require(plan["planFingerprint"]["sha256"] == expected_plan_sha256.lower(), "Resume plan fingerprint mismatch")
        return _execute_resume(source, plan, saved, cases, runs_root, modules_dir, cancel_after_stream,
                               stop_after=stop_after, stop_after_tokens=stop_after_tokens)


def _execute_resume(source, plan, saved, cases, runs_root, modules_dir, cancel_after_stream, *, resume_id=None, _lock_stack=None,
                    stop_after=None, stop_after_tokens=None):
    """Execute a verified plan while the caller retains the source batch lock."""
    _check_resume_output_root(runs_root)
    resume_id = resume_id or str(uuid4())
    directory = Path(runs_root or ROOT / "runs" / "resumes").resolve() / resume_id
    require(not directory.exists(), "Resume directory already exists")
    # Creation is exclusive, and happens before any remaining task can start.
    # A crash leaves a claim requiring inspection, rather than automatic reuse.
    save_json(source.parent / CLAIM_NAME, {"resumeClaimFormatVersion": 1, "resumeId": resume_id,
                                         "resumeDirectory": str(directory), "claimedAt": _now()})
    (directory / "inputs").mkdir(parents=True, exist_ok=False)
    save_json(directory / "resume-plan.json", plan)
    remaining = {"batchFormatVersion": 1, "batchName": saved["batchName"] + " continuation",
                 "failurePolicy": saved["failurePolicy"], "cases": []}
    for index, entry_id in enumerate(plan["pendingEntryIds"], 1):
        path = f"inputs/{index:04}.case.json"
        save_json(directory / path, cases[entry_id])
        remaining["cases"].append({"entryId": entry_id, "casePath": path})
    save_json(directory / "remaining.batch.json", remaining)
    batch_id = str(uuid4())
    report = {"batchResumeResultFormatVersion": 1, "resumeId": resume_id, "resumeDirectory": str(directory),
              "sourceBatchResult": str(source), "sourceBatchId": saved["batchId"],
              "planFingerprint": plan["planFingerprint"], "startedAt": _now(), "finishedAt": None,
              "status": "running", "outcome": None, "stopAfter": stop_after,
              "stopAfterTokens": stop_after_tokens, "tokenUsage": None,
              "reusedEntries": plan["reusedEntries"], "batchResultPath": None,
              "batchBinding": {"batchId": batch_id, "resultPath": f"batches/{batch_id}/batch-result.json"}}
    save_json(directory / "resume-result.json", report)
    with ExitStack() as local_locks:
        lock_owner = _lock_stack if _lock_stack is not None else local_locks
        result = run_batch(directory / "remaining.batch.json", directory / "batches", modules_dir, cancel_after_stream,
                           batch_id=batch_id, _lock_stack=lock_owner, stop_after=stop_after, stop_after_tokens=stop_after_tokens)
        return _finish_resume(directory, report, result, plan, saved)


def _finish_resume(directory, report, result, plan, saved):
    rows = {row["entryId"]: row for row in [*plan["reusedEntries"], *result["entries"]]}
    combined = [rows[row["entryId"]] for row in saved["entries"]]
    outcomes = {row["outcome"] for row in combined}
    outcome = ("unevaluable" if result["status"] in ("error", "interrupted") or "unevaluable" in outcomes
               else "failed" if "failed" in outcomes else "passed" if outcomes == {"passed"} else "unevaluable")
    report.update(finishedAt=_now(), status=result["status"], stopReason=result["stopReason"], outcome=outcome, tokenUsage=result["tokenUsage"],
                  batchResultPath=(Path(result["batchDirectory"]).relative_to(directory) / "batch-result.json").as_posix(),
                  newlyExecutedSummary=summarize(result["entries"]), combinedSummary=summarize(combined))
    temporary = directory / f".resume-result-{uuid4()}.tmp"
    save_json(temporary, report)
    temporary.replace(directory / "resume-result.json")
    return report
