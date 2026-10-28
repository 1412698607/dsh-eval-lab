"""Explicit continuation chains; never infer a batch by scanning directories."""
from contextlib import ExitStack, contextmanager
import hashlib
from pathlib import Path
from uuid import UUID, uuid4

from .batch import _now, input_fingerprint
from .batch_lock import batch_lock
from .formats import load_json, nonempty, require, validate_batch, validate_case
from .metrics import summarize
from .resume import CLAIM_NAME, _digest, _execute_resume, _load_plan as load_batch_plan, _path
from .resume_report import _check_files, _identity, _terminal, load_resume_inputs
from .runner import ROOT, save_json

MAX_CONTINUATIONS = 32
IDENTITY = ("sampleId", "caseEntryId", "configurationId", "repeatIndex", "caseId", "requestedConfiguration")


def _absolute(value):
    require(nonempty(value) and Path(value).is_absolute(), "Continuation source requires an explicit absolute path")
    return Path(value).resolve()


def _archive_files(paths, batches):
    files = {path for source in paths for path in (source, source.parent / "resume-plan.json")}
    for path in batches:
        saved = load_json(path)
        files.update((path, _path(path.parent, saved["manifestPath"])))
        files.update(_path(path.parent, row["casePath"]) for row in saved["entries"])
    return files


def _hashes(files):
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)}


def _fingerprint(plan):
    return {"version": 2, "sha256": _digest({key: plan[key] for key in (
        "sourceResumeResult", "sourceResumeId", "sourceExperimentResult", "sourceExperimentId", "sourceBatchResult",
        "sourceBatchId", "maxSamples", "sourceFilesSha256", "batchPlans", "samples", "counts")})}


def _classify(context, batches, plans):
    lookups = {str(path): ({row["entryId"]: row for row in plan["reusedEntries"]},
                          {row["entryId"]: row["reason"] for row in plan["blockedEntries"]}, set(plan["pendingEntryIds"]))
               for path, plan in zip(batches, plans)}
    samples, reused_rows = [], {}
    for row, _base, batch_id, provenance in context[4]:
        source = provenance["sourceBatchResult"]
        reused, blocked, pending = lookups[source]
        identity = {key: row[key] for key in IDENTITY}
        item = {**identity, "sourceStatus": row["status"], "sourceBatchId": batch_id, "sourceBatchResult": source}
        sample_id = row["sampleId"]
        if sample_id in reused:
            verified = reused[sample_id]
            item.update(disposition="reuse", verification=verified["verification"], caseRunId=verified["caseRunId"],
                        source=verified["source"], outcome=verified["outcome"], recoveredCheckpoint=verified["recoveredCheckpoint"])
            reused_rows[sample_id] = verified
        elif sample_id in pending and source == str(batches[-1]):
            item.update(disposition="pending", caseRunId=None, source=None, outcome=None)
        else:
            item.update(disposition="blocked", reason=blocked.get(sample_id, "Historical sample cannot become unstarted"))
        samples.append(item)
    return samples, reused_rows


def _plan_counts(samples):
    return {"original": len(samples), "reused": sum(row["disposition"] == "reuse" for row in samples),
            "newSamples": sum(row["disposition"] == "pending" for row in samples),
            "blocked": sum(row["disposition"] == "blocked" for row in samples)}


def _initial_batches(source, context):
    from .experiment_resume import _binding
    original = _absolute(context[5]["sourceExperimentResult"])
    child_path = _path(source.parent, load_json(source)["batchResumeResultPath"])
    child = load_json(child_path)
    binding = child.get("batchBinding")
    new_path = _path(child_path.parent, binding["resultPath"] if binding is not None else child["batchResultPath"])
    return [_binding(load_json(original), original.parent), new_path]


def _validate_batch_plans(plan, batches):
    plans = plan["batchPlans"]
    require(isinstance(plans, list) and len(plans) == len(batches), "Continuation batch plan count mismatch")
    for path, saved in zip(batches, plans):
        require(isinstance(saved, dict) and type(saved.get("batchResumePlanFormatVersion")) is int
                and saved["batchResumePlanFormatVersion"] == 1 and saved.get("valid") is True
                and saved["sourceBatchResult"] == str(path), "Invalid continuation batch plan")
        batch = load_json(path)
        require(saved["sourceBatchId"] == batch["batchId"], "Continuation batch plan identity mismatch")
        payload = {"version": 1, "sourceBatchResult": str(path), "sourceFilesSha256": saved["sourceFilesSha256"],
                   "pendingEntryIds": saved["pendingEntryIds"], "reusedEntryIds": [row["entryId"] for row in saved["reusedEntries"]],
                   "maxSamples": saved["maxSamples"]}
        require(_digest(saved["planFingerprint"]) == _digest({"version": 1, "sha256": _digest(payload)}), "Saved chain batch fingerprint mismatch")
        _check_files(path.parent, saved["sourceFilesSha256"], {path, _path(path.parent, batch["manifestPath"]),
                     *(_path(path.parent, row["casePath"]) for row in batch["entries"])})
        reused = {row["entryId"]: row for row in saved["reusedEntries"]}
        pending = saved["pendingEntryIds"]
        require(len(reused) == len(saved["reusedEntries"]) and len(set(pending)) == len(pending)
                and not saved["blockedEntries"] and len(reused) + len(pending) == len(batch["entries"]), "Invalid saved chain classifications")
        observed_pending = []
        for row in batch["entries"]:
            if row["entryId"] in reused:
                verified = reused[row["entryId"]]
                require(row["status"] in ("finished", "running") and verified["status"] == "finished"
                        and verified["verification"] == "verified" and verified["recoveredCheckpoint"] is (row["status"] == "running"),
                        "Invalid saved chain reuse state")
                for key, value in row.items():
                    if value is not None and key != "status":
                        require(_digest(verified.get(key)) == _digest(value), f"Saved chain reuse {key} mismatch")
            else:
                require(row["entryId"] in pending and row["status"] in ("pending", "skipped"), "Invalid saved chain pending sample")
                observed_pending.append(row["entryId"])
        require(observed_pending == pending and _digest(saved["counts"]) == _digest({"original": len(batch["entries"]),
                "reused": len(reused), "newSamples": len(pending), "blocked": 0}), "Saved chain batch counts/order mismatch")
    require(plans[-1].get("canResume") is True, "Latest saved batch plan cannot resume")
    return plans


def _overlay(source, resumed, context, paths, batches, *, allow_unfinished):
    _terminal(resumed, "experimentResumeResultFormatVersion", allow_unfinished=allow_unfinished, expected_version=2)
    _identity(resumed, source.parent)
    plan = load_json(source.parent / "resume-plan.json")
    require(isinstance(plan, dict) and type(plan.get("experimentResumePlanFormatVersion")) is int
            and plan["experimentResumePlanFormatVersion"] == 2 and plan.get("valid") is True
            and plan.get("eligibleForResume") is True and plan.get("executionSupported") is True, "Invalid saved chain plan")
    require(plan.get("maxSamples") is None or type(plan["maxSamples"]) is int and plan["maxSamples"] > 0, "Invalid saved chain task cap")
    require(plan["sourceResumeResult"] == str(paths[-1]) and plan["sourceResumeId"] == load_json(paths[-1])["resumeId"]
            and plan["sourceExperimentResult"] == context[5]["sourceExperimentResult"]
            and plan["sourceExperimentId"] == context[0]["experimentId"]
            and plan["sourceBatchResult"] == str(batches[-1])
            and plan["sourceBatchId"] == load_json(batches[-1])["batchId"], "Continuation chain source mismatch")
    for key in ("sourceResumeResult", "sourceResumeId", "sourceExperimentResult", "sourceExperimentId", "sourceBatchResult",
                "sourceBatchId", "maxSamples", "counts", "planFingerprint"):
        require(_digest(resumed[key]) == _digest(plan[key]), f"Chained result/plan {key} mismatch")
    require(_digest(resumed["samplePlan"]) == _digest(plan["samples"]), "Chained sample plan mismatch")
    require(plan["sourceFilesSha256"] == _hashes(_archive_files(paths, batches)), "Continuation chain source archive changed")
    plans = _validate_batch_plans(plan, batches)
    samples, reused_rows = _classify(context, batches, plans)
    require(_digest(samples) == _digest(plan["samples"]) and _digest(_plan_counts(samples)) == _digest(plan["counts"])
            and plan["counts"]["blocked"] == 0, "Chained sample classification mismatch")
    require(plan["planFingerprint"] == _fingerprint(plan), "Saved chain plan fingerprint mismatch")
    require(resumed["batchPlanFingerprint"] == plans[-1]["planFingerprint"], "Chained batch fingerprint mismatch")
    child_path = _path(source.parent, resumed["batchResumeResultPath"])
    child = load_json(child_path)
    _terminal(child, "batchResumeResultFormatVersion", allow_unfinished=allow_unfinished)
    _identity(child, child_path.parent)
    require(resumed["batchResumeResultPath"] == f"continuations/{child['resumeId']}/resume-result.json", "Unexpected chain child path")
    require(child["sourceBatchResult"] == str(batches[-1]) and child["sourceBatchId"] == plan["sourceBatchId"]
            and child["planFingerprint"] == plans[-1]["planFingerprint"]
            and _digest(child["reusedEntries"]) == _digest(plans[-1]["reusedEntries"])
            and _digest(load_json(child_path.parent / "resume-plan.json")) == _digest(plans[-1]), "Chained batch plan binding mismatch")
    claim = load_json(batches[-1].parent / CLAIM_NAME)
    require(type(claim.get("resumeClaimFormatVersion")) is int and claim["resumeClaimFormatVersion"] == 1
            and claim["resumeId"] == child["resumeId"] and _absolute(claim["resumeDirectory"]) == child_path.parent,
            "Chained continuation claim mismatch")
    if resumed["status"] != "running":
        require(resumed["status"] == child["status"]
                and _digest(resumed["newlyExecutedSummary"]) == _digest(child["newlyExecutedSummary"]), "Chained terminal state mismatch")
    binding = child.get("batchBinding")
    require(isinstance(binding, dict) and set(binding) == {"batchId", "resultPath"}
            and isinstance(binding["batchId"], str) and str(UUID(binding["batchId"])) == binding["batchId"]
            and binding["resultPath"] == f"batches/{binding['batchId']}/batch-result.json", "Missing or invalid chained batch binding")
    require(child.get("batchResultPath") == binding["resultPath"] or child["status"] == "running" and child.get("batchResultPath") is None,
            "Chained observed/reserved batch mismatch")
    new_path = _path(child_path.parent, binding["resultPath"])
    require(new_path not in batches, "Repeated continuation batch")
    batch = load_json(new_path)
    _terminal(batch, "batchResultFormatVersion", allow_unfinished=allow_unfinished)
    require(batch["batchId"] == binding["batchId"] and _absolute(batch["batchDirectory"]) == new_path.parent
            and batch["mode"] == "sequential" and (child["status"] == "running" or batch["status"] == child["status"])
            and batch["sourceManifest"] == str(child_path.parent / "remaining.batch.json"), "Chained batch association mismatch")
    remaining = validate_batch(load_json(child_path.parent / "remaining.batch.json"))
    frozen = validate_batch(load_json(_path(new_path.parent, batch["manifestPath"])))
    pending = plans[-1]["pendingEntryIds"]
    require([row["entryId"] for row in batch["entries"]] == pending and len(pending) == len(remaining["cases"]) == len(frozen["cases"]),
            "Chained remaining sample order/count mismatch")
    parent_batch = load_json(batches[-1])
    require(batch["failurePolicy"] == frozen["failurePolicy"] == remaining["failurePolicy"] == context[1]["failurePolicy"]
            and batch["batchName"] == frozen["batchName"] == remaining["batchName"] == parent_batch["batchName"] + " continuation",
            "Chained remaining manifest mismatch")
    new_rows, new_cases = {}, []
    prior_by_id = {row[0]["sampleId"]: row for row in context[4]}
    identities = {key: value[0] for key, value in prior_by_id.items()}
    for row, entry, original in zip(batch["entries"], frozen["cases"], remaining["cases"]):
        sample_id = row["entryId"]
        identity = identities[sample_id]
        expected = {**context[2][identity["caseEntryId"]], "configRef": identity["requestedConfiguration"]}
        require(entry["entryId"] == original["entryId"] == sample_id and row["casePath"] == entry["casePath"]
                and row["sourceCasePath"] == str(_path(child_path.parent, original["casePath"]))
                and row["caseId"] == identity["caseId"] and _digest(row["requestedConfiguration"]) == _digest(expected["configRef"]),
                "Chained case identity/input association mismatch")
        for base, item in ((new_path.parent, entry), (child_path.parent, original)):
            require(_digest(validate_case(load_json(_path(base, item["casePath"])))) == _digest(expected), "Chained frozen input mismatch")
        new_cases.append(expected)
        new_rows[sample_id] = row
    require(batch["inputFingerprint"] == input_fingerprint(frozen, new_cases), "Chained batch input fingerprint mismatch")
    selected = []
    for item in samples:
        sample_id = item["sampleId"]
        identity = {key: item[key] for key in IDENTITY}
        if item["disposition"] == "pending":
            row, base, batch_id, origin = new_rows[sample_id], new_path.parent, batch["batchId"], "new"
            provenance = {"executionOrigin": origin, "sourceBatchId": batch_id, "sourceBatchResult": str(new_path)}
        else:
            prior = prior_by_id[sample_id]
            row, base, batch_id, previous = reused_rows[sample_id], prior[1], prior[2], prior[3]
            provenance = {**previous, "executionOrigin": "reused"}
            if row.get("recoveredCheckpoint"):
                row = {**row, **{key: f"{row['caseDirectory']}/{name}" for key, name in
                       (("evidencePath", "evidence.json"), ("evaluationPath", "evaluation.json"), ("runtimeReport", "runtime.json"))}}
                try:
                    evidence = load_json(_path(base, row["evidencePath"]))
                    row["runDir"] = _path(_path(base, row["caseDirectory"]), evidence["runDir"].replace("\\", "/")).relative_to(base).as_posix()
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    row["runDir"] = None
        selected.append(({**row, **identity}, base, batch_id, provenance))
    _check_selected(selected, allow_unfinished)
    chain = [*context[5].get("resumeChain", [{"resumeId": load_json(paths[0])["resumeId"], "resultPath": str(paths[0])}]),
             {"resumeId": resumed["resumeId"], "resultPath": str(source)}]
    metadata = {"comparisonReportFormatVersion": 3, "sourceResumeResult": str(source), "resumeId": resumed["resumeId"],
                "sourceExperimentResult": context[5]["sourceExperimentResult"], "batchId": None,
                "batchIds": [*context[5]["batchIds"], batch["batchId"]], "batchResultPaths": [str(path) for path in [*batches, new_path]],
                "resumeChain": chain, "resumeVerification": {"status": "verified", "planFingerprint": plan["planFingerprint"],
                    "batchPlanFingerprint": plans[-1]["planFingerprint"], "batchResumeResult": str(child_path), "chainLength": len(chain)}}
    return ({**context[0], "summary": resumed.get("combinedSummary")}, context[1], context[2], context[3], selected, metadata), new_path


def _check_selected(selected, allow_unfinished):
    seen = {key: set() for key in ("caseRunId", "runId", "sessionId")}
    for row, base, _batch, _origin in selected:
        require(row["status"] in (("pending", "running", "finished", "skipped", "error") if allow_unfinished else ("finished", "skipped", "error")),
                "Unsupported chained sample state")
        for key, values in seen.items():
            value = row[key]
            require(value is None or nonempty(value) and value not in values, f"Duplicate or invalid chained {key}")
            if value is not None:
                values.add(value)
        if row["status"] in ("pending", "skipped"):
            require(all(row.get(key) is None for key in ("caseRunId", "runId", "sessionId", "source", "configuration", "outcome", "metrics",
                    "executionStatus", "recordingOutcome", "assertionOutcome", "caseDirectory", "evidencePath", "evaluationPath", "runtimeReport", "runDir")),
                    "Unstarted chained sample contains execution facts")
        else:
            require(nonempty(row["caseRunId"]) and row["caseDirectory"] == f"cases/{row['caseRunId']}", "Invalid chained case directory")
            for key, name in (("evidencePath", "evidence.json"), ("evaluationPath", "evaluation.json"), ("runtimeReport", "runtime.json")):
                require(row.get(key) == f"{row['caseDirectory']}/{name}" or row.get(key) is None and row["status"] in ("error", "running"),
                        "Unexpected chained case artifact path")
        for key in ("casePath", "caseDirectory", "evidencePath", "evaluationPath", "runtimeReport", "runDir"):
            if row.get(key) is not None:
                _path(base, row[key])


def _load_chain(source, *, allow_unfinished=False):
    pending, seen, identities = [], set(), set()
    current = source
    while True:
        require(current not in seen and len(seen) < MAX_CONTINUATIONS, "Continuation chain is cyclic or exceeds 32 results")
        seen.add(current)
        saved = load_json(current)
        version = saved.get("experimentResumeResultFormatVersion")
        require(type(version) is int and version in (1, 2), "Unsupported continuation result format")
        require(saved["resumeId"] not in identities, "Duplicate continuation identity")
        identities.add(saved["resumeId"])
        if version == 1:
            context = load_resume_inputs(current, allow_unfinished=bool(pending) or allow_unfinished)
            paths, batches = [current], _initial_batches(current, context)
            break
        pending.append((current, saved))
        current = _absolute(saved["sourceResumeResult"])
    for path, saved in reversed(pending):
        context, new_batch = _overlay(path, saved, context, paths, batches,
                                      allow_unfinished=path != source or allow_unfinished)
        paths.append(path)
        batches.append(new_batch)
    require(len(set(context[5]["batchIds"])) == len(batches), "Duplicate continuation batch identity")
    return context, paths, batches


def load_chain_inputs(source):
    return _load_chain(source)[0]


@contextmanager
def _locked_chain(source):
    _context, paths, batches = _load_chain(source, allow_unfinished=True)
    with ExitStack() as locks:
        for path in batches:
            locks.enter_context(batch_lock(path.parent))
        context, checked_paths, checked_batches = _load_chain(source, allow_unfinished=True)
        require(paths == checked_paths and batches == checked_batches, "Continuation chain changed while acquiring locks")
        yield context, paths, batches, locks


def _load_plan(source, context, paths, batches, max_samples):
    plans, saved_batches, cases = [], [], []
    for index, path in enumerate(batches):
        plan, saved, inputs = load_batch_plan(path, max_samples if index == len(batches) - 1 else None)
        plans.append(plan)
        saved_batches.append(saved)
        cases.append(inputs)
    samples, reused = _classify(context, batches, plans)
    counts = _plan_counts(samples)
    reasons = list(plans[-1]["reasons"])
    if len(paths) >= MAX_CONTINUATIONS:
        reasons.append("Continuation chain already contains 32 results")
    for plan in plans[:-1]:
        reasons.extend(reason for reason in plan["reasons"] if reason not in
                       ("Source batch already has a continuation claim", "No unstarted entries remain"))
    result = {"experimentResumePlanFormatVersion": 2, "valid": True, "modelCalled": False, "executionSupported": True,
              "sourceResumeResult": str(source), "sourceResumeId": load_json(source)["resumeId"],
              "sourceExperimentResult": context[5]["sourceExperimentResult"], "sourceExperimentId": context[0]["experimentId"],
              "sourceBatchResult": str(batches[-1]), "sourceBatchId": saved_batches[-1]["batchId"],
              "maxSamples": max_samples, "planVerification": context[3], "counts": counts, "samples": samples,
              "eligibleForResume": counts["newSamples"] > 0 and not counts["blocked"] and not reasons,
              "reasons": list(dict.fromkeys(reasons)), "batchPlans": plans, "sourceFilesSha256": _hashes(_archive_files(paths, batches))}
    result["planFingerprint"] = _fingerprint(result)
    return result, plans[-1], saved_batches[-1], cases[-1], reused


def plan_chain(source, *, max_samples=None):
    with _locked_chain(source) as (context, paths, batches, _locks):
        return _load_plan(source, context, paths, batches, max_samples)[0]


def execute_chain(source, runs_root, modules_dir, cancel_after_stream, *, max_samples, expected_plan_sha256):
    with _locked_chain(source) as (context, paths, batches, locks):
        plan, batch_plan, saved, cases, reused = _load_plan(source, context, paths, batches, max_samples)
        require(plan["eligibleForResume"], "Experiment cannot resume: " + "; ".join(plan["reasons"] +
                [row["reason"] for row in plan["samples"] if row["disposition"] == "blocked"]))
        require(plan["planFingerprint"]["sha256"] == expected_plan_sha256.lower(), "Experiment resume plan fingerprint mismatch")
        require(len(paths) < MAX_CONTINUATIONS, "Continuation chain exceeds 32 results")
        resume_id, batch_resume_id = str(uuid4()), str(uuid4())
        directory = Path(runs_root or ROOT / "runs" / "experiment-resumes").resolve() / resume_id
        directory.mkdir(parents=True, exist_ok=False)
        save_json(directory / "resume-plan.json", plan)
        report = {"experimentResumeResultFormatVersion": 2, "resumeId": resume_id, "resumeDirectory": str(directory),
                  **{key: plan[key] for key in ("sourceResumeResult", "sourceResumeId", "sourceExperimentResult", "sourceExperimentId",
                      "sourceBatchResult", "sourceBatchId", "maxSamples", "counts", "planFingerprint")},
                  "batchPlanFingerprint": batch_plan["planFingerprint"], "samplePlan": plan["samples"],
                  "batchResumeResultPath": f"continuations/{batch_resume_id}/resume-result.json",
                  "startedAt": _now(), "finishedAt": None, "status": "running", "outcome": None,
                  "newlyExecutedSummary": None, "combinedSummary": None}
        save_json(directory / "experiment-resume-result.json", report)
        result = _execute_resume(batches[-1], batch_plan, saved, cases, directory / "continuations", modules_dir,
                                 cancel_after_stream, resume_id=batch_resume_id, _lock_stack=locks)
        child_batch = load_json(_path(_path(directory, report["batchResumeResultPath"]).parent, result["batchResultPath"]))
        rows = {**reused, **{row["entryId"]: row for row in child_batch["entries"]}}
        combined = [rows[row["sampleId"]] for row in plan["samples"]]
        outcomes = {row["outcome"] for row in combined}
        outcome = ("unevaluable" if result["status"] in ("error", "interrupted") or "unevaluable" in outcomes else
                   "failed" if "failed" in outcomes else "passed" if outcomes == {"passed"} else "unevaluable")
        report.update(finishedAt=_now(), status=result["status"], outcome=outcome,
                      newlyExecutedSummary=result["newlyExecutedSummary"], combinedSummary=summarize(combined))
        temporary = directory / f".experiment-resume-result-{uuid4()}.tmp"
        save_json(temporary, report)
        temporary.replace(directory / "experiment-resume-result.json")
        return report
