"""Sequential live cases, immutable input snapshots, and one active batch checkpoint."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

from .batch_lock import batch_lock
from .formats import load_json, require, validate_batch
from .runner import ROOT, run_case, save_json, validate_live_case


def _now():
    return datetime.now(timezone.utc).isoformat()


def input_fingerprint(manifest, cases):
    payload = {"version": 1, "manifest": manifest, "cases": cases}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return {"version": 1, "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def _checkpoint(directory, report):
    temporary = directory / f".batch-result-{uuid4()}.tmp"
    save_json(temporary, report)
    temporary.replace(directory / "batch-result.json")


def _cleanup_confirmed(runtime):
    if runtime["stage"] in ("workspace", "prepare"):
        return runtime["preparation"]["processExited"] is True
    if runtime.get("adapterProcessStarted") is False:
        return True
    supervisor, host = runtime["supervisor"], runtime["host"]
    return (supervisor.get("adapterExitCode") is not None and supervisor.get("stdinWriterStopped") is True
            and (host.get("childClosed") is True or "childPid" in host and host["childPid"] is None
                 or supervisor.get("forceStopAttempted") is True))


def _outcome(report):
    outcomes = {entry["outcome"] for entry in report["entries"]}
    if report["status"] in ("error", "interrupted") or "unevaluable" in outcomes:
        return "unevaluable"
    if "failed" in outcomes:
        return "failed"
    if report["status"] == "completed" and outcomes == {"passed"}:
        return "passed"
    return "unevaluable"


def run_batch(batch_path, runs_root=None, modules_dir=None, cancel_after_stream=False, *, batch_id=None):
    require(batch_id is None or isinstance(batch_id, str), "Reserved batch_id must be a UUID string")
    source = Path(batch_path).resolve()
    manifest = validate_batch(load_json(source))
    # Validate all cases before creating a run or calling a model, then freeze inputs.
    inputs = [(entry, (source.parent / entry["casePath"]).resolve(),
               validate_live_case(load_json(source.parent / entry["casePath"]))) for entry in manifest["cases"]]
    batch_id = str(UUID(batch_id)) if batch_id is not None else str(uuid4())
    directory = Path(runs_root or ROOT / "runs" / "batches").resolve() / batch_id
    (directory / "inputs").mkdir(parents=True, exist_ok=False)
    (directory / "cases").mkdir()
    report = {"batchResultFormatVersion": 1, "batchId": batch_id, "batchName": manifest["batchName"],
              "failurePolicy": manifest["failurePolicy"], "mode": "sequential", "batchDirectory": str(directory),
              "sourceManifest": str(source), "manifestPath": "batch.json", "status": "running",
              "startedAt": _now(), "finishedAt": None, "stopReason": None, "outcome": None, "entries": []}
    frozen = {**manifest, "cases": []}
    for index, (entry, case_source, case) in enumerate(inputs):
        path = f"inputs/{index + 1:04}.case.json"
        save_json(directory / path, case)
        frozen["cases"].append({"entryId": entry["entryId"], "casePath": path})
        report["entries"].append({"entryId": entry["entryId"], "caseId": case["caseId"], "sourceCasePath": str(case_source),
            "casePath": path, "requestedConfiguration": case["configRef"], "status": "pending", "caseRunId": None,
            "caseDirectory": None, "evaluationPath": None, "evidencePath": None, "runtimeReport": None,
            "runId": None, "sessionId": None, "runDir": None, "configuration": None,
            "executionStatus": None, "recordingOutcome": None, "assertionOutcome": None, "outcome": None,
            "source": None, "metrics": None})
    save_json(directory / "batch.json", frozen)
    with batch_lock(directory, create=True):
        report["resumeSupportVersion"] = 1
        report["inputFingerprint"] = input_fingerprint(frozen, [case for _entry, _path, case in inputs])
        _checkpoint(directory, report)
        return _execute_batch(directory, report, manifest, modules_dir, cancel_after_stream)


def _execute_batch(directory, report, manifest, modules_dir, cancel_after_stream):
    batch_id = report["batchId"]
    active = None
    try:
        for index, active in enumerate(report["entries"]):
            active.update(status="running", caseRunId=str(uuid4()))
            active["caseDirectory"] = f"cases/{active['caseRunId']}"
            _checkpoint(directory, report)
            case_directory = directory / active["caseDirectory"]
            try:
                returned = run_case(directory / active["casePath"], directory / "cases", modules_dir, cancel_after_stream,
                                    batch_id=batch_id, case_run_id=active["caseRunId"])
                result = load_json(case_directory / "evaluation.json")
                require(returned == result, "Runner result differs from saved evaluation")
                evidence = load_json(case_directory / "evidence.json")
                for record in (result, evidence):
                    require(record["caseRunId"] == active["caseRunId"] and record["caseId"] == active["caseId"]
                            and record["batchId"] == batch_id, "Batch/case association mismatch")
                runtime = load_json(case_directory / "runtime.json")
                active.update(status="finished", evaluationPath=f"{active['caseDirectory']}/evaluation.json",
                    evidencePath=f"{active['caseDirectory']}/evidence.json", runtimeReport=f"{active['caseDirectory']}/runtime.json",
                    runId=result["association"]["runId"], sessionId=result["association"]["sessionId"],
                    runDir=str(Path(result["association"]["runDir"]).relative_to(directory)).replace("\\", "/")
                        if result["association"]["runDir"] else None,
                    configuration=result["configuration"], executionStatus=result["execution"]["status"],
                    recordingOutcome=result["recording"]["outcome"], assertionOutcome=result["assertions"]["outcome"],
                    outcome=result["outcome"], source=result["source"], metrics=result.get("metrics"))
                if runtime.get("userInterrupted"):
                    report.update(status="interrupted", stopReason="user_interrupt")
                elif not _cleanup_confirmed(runtime):
                    report.update(status="error", stopReason="cleanup_unconfirmed")
                elif result["outcome"] != "passed" and manifest["failurePolicy"] == "stop" and index + 1 < len(report["entries"]):
                    report.update(status="stopped", stopReason="failure_policy")
            except Exception as error:
                # An unexpected runner/result failure cannot establish isolation for the next case.
                active.update(status="error", outcome="unevaluable", error={"type": type(error).__name__, "message": str(error)})
                report.update(status="error", stopReason="runner_error")
            _checkpoint(directory, report)
            if report["status"] != "running":
                break
    except KeyboardInterrupt:
        report.update(status="interrupted", stopReason="user_interrupt")
        if active is not None and active["status"] == "running":
            active.update(status="error", outcome="unevaluable", error={"type": "KeyboardInterrupt", "message": "Runner interrupted"})
    if report["status"] == "running":
        report["status"] = "completed"
    for entry in report["entries"]:
        if entry["status"] == "pending":
            entry.update(status="skipped", skipReason=report["stopReason"])
    report.update(finishedAt=_now(), outcome=_outcome(report))
    _checkpoint(directory, report)
    return report
