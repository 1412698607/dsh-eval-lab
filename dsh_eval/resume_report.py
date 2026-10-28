"""Validate explicit experiment continuation bindings before offline sample rechecks."""
import hashlib
from pathlib import Path
import re
from uuid import UUID

from .batch import input_fingerprint
from .experiment_resume import _binding, _load_inputs
from .formats import load_json, nonempty, require, validate_batch, validate_case
from .report import _path
from .resume import CLAIM_NAME, _digest


def _terminal(saved, version, *, allow_unfinished=False, expected_version=1):
    require(isinstance(saved, dict) and type(saved.get(version)) is int and saved[version] == expected_version,
            "Unsupported continuation result format")
    if allow_unfinished and saved.get("status") == "running":
        require(saved.get("finishedAt") is None and saved.get("outcome") is None, "Running continuation contains terminal facts")
        return
    require(saved.get("status") in ("completed", "stopped", "interrupted", "error") and nonempty(saved.get("finishedAt")),
            "Report requires terminal continuation results")


def _identity(saved, directory):
    value = saved["resumeId"]
    require(isinstance(value, str) and str(UUID(value)) == value
            and Path(saved["resumeDirectory"]).resolve() == directory, "Continuation identity/directory mismatch")


def _check_files(directory, hashes, required):
    require(isinstance(hashes, dict), "Missing continuation source file hashes")
    for name, digest in hashes.items():
        _path(directory, name)
        require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None, "Invalid source file hash")
    for path in required:
        name = path.relative_to(directory).as_posix()
        require(hashes.get(name) == hashlib.sha256(path.read_bytes()).hexdigest(), "Continuation frozen source changed")


def load_resume_report(source):
    if load_json(source).get("experimentResumeResultFormatVersion") == 2:
        from .experiment_resume_chain import load_chain_inputs
        return load_chain_inputs(source)
    return load_resume_inputs(source)


def load_resume_inputs(source, *, allow_unfinished=False):
    directory = source.parent
    resumed = load_json(source)
    _terminal(resumed, "experimentResumeResultFormatVersion", allow_unfinished=allow_unfinished)
    _identity(resumed, directory)
    plan = load_json(directory / "resume-plan.json")
    require(isinstance(plan, dict) and type(plan.get("experimentResumePlanFormatVersion")) is int and plan["experimentResumePlanFormatVersion"] == 1
            and plan.get("valid") is True and plan.get("eligibleForResume") is True, "Invalid saved experiment resume plan")
    for key in ("sourceExperimentResult", "sourceExperimentId", "sourceBatchResult", "sourceBatchId", "maxSamples",
                "counts", "planFingerprint", "batchPlanFingerprint"):
        require(_digest(resumed[key]) == _digest(plan[key]), f"Continuation/plan {key} mismatch")
    require(_digest(resumed["samplePlan"]) == _digest(plan["samples"]), "Continuation sample plan mismatch")
    original_path = Path(plan["sourceExperimentResult"])
    require(original_path.is_absolute(), "Source experiment must have an explicit absolute path")
    original_path = original_path.resolve()
    batch_path = _binding(load_json(original_path), original_path.parent)
    require(str(batch_path) == plan["sourceBatchResult"], "Continuation source batch binding mismatch")
    original, manifest, cases, batch, identities, files, verification = _load_inputs(original_path, batch_path)
    require(plan["sourceExperimentId"] == original["experimentId"] and plan["sourceBatchId"] == batch["batchId"],
            "Continuation source identity mismatch")
    _check_files(original_path.parent, plan["sourceFilesSha256"], files)
    payload = {"version": 1, "sourceExperimentResult": str(original_path), "sourceFilesSha256": plan["sourceFilesSha256"],
               "batchPlanFingerprint": plan["batchPlanFingerprint"], "maxSamples": plan["maxSamples"], "samples": plan["samples"]}
    require(_digest(plan["planFingerprint"]) == _digest({"version": 1, "sha256": _digest(payload)}), "Saved experiment resume fingerprint mismatch")

    child_path = _path(directory, resumed["batchResumeResultPath"])
    child = load_json(child_path)
    _terminal(child, "batchResumeResultFormatVersion", allow_unfinished=allow_unfinished)
    _identity(child, child_path.parent)
    require(resumed["batchResumeResultPath"] == f"continuations/{child['resumeId']}/resume-result.json",
            "Unexpected batch continuation result path")
    for key in ("sourceBatchResult", "sourceBatchId", *(("status", "outcome", "newlyExecutedSummary") if resumed["status"] != "running" else ())):
        require(_digest(resumed[key]) == _digest(child[key]), f"Experiment/batch continuation {key} mismatch")
    claim = load_json(batch_path.parent / CLAIM_NAME)
    require(isinstance(claim, dict) and type(claim.get("resumeClaimFormatVersion")) is int and claim["resumeClaimFormatVersion"] == 1
            and claim["resumeId"] == child["resumeId"]
            and Path(claim["resumeDirectory"]).resolve() == child_path.parent, "Continuation claim binding mismatch")
    batch_plan = load_json(child_path.parent / "resume-plan.json")
    require(isinstance(batch_plan, dict) and type(batch_plan.get("batchResumePlanFormatVersion")) is int and batch_plan["batchResumePlanFormatVersion"] == 1
            and batch_plan.get("canResume") is True, "Invalid saved batch resume plan")
    for key in ("sourceBatchResult", "sourceBatchId", "maxSamples", "counts"):
        require(_digest(batch_plan[key]) == _digest(plan[key]), f"Experiment/batch resume plan {key} mismatch")
    require(child["planFingerprint"] == batch_plan["planFingerprint"] == plan["batchPlanFingerprint"],
            "Batch continuation fingerprint binding mismatch")
    require(_digest(child["reusedEntries"]) == _digest(batch_plan["reusedEntries"]), "Reused entries changed")
    pending, reused = batch_plan["pendingEntryIds"], batch_plan["reusedEntries"]
    require(isinstance(pending, list) and isinstance(reused, list) and isinstance(plan["samples"], list) and len(plan["samples"]) == len(identities)
            and len(pending) + len(reused) == len(identities), "Continuation sample count mismatch")
    require(_digest(plan["counts"]) == _digest({"original": len(identities), "reused": len(reused), "newSamples": len(pending), "blocked": 0}),
            "Continuation counts mismatch")
    batch_payload = {"version": 1, "sourceBatchResult": str(batch_path), "sourceFilesSha256": batch_plan["sourceFilesSha256"],
                     "pendingEntryIds": pending, "reusedEntryIds": [row["entryId"] for row in reused], "maxSamples": plan["maxSamples"]}
    require(_digest(batch_plan["planFingerprint"]) == _digest({"version": 1, "sha256": _digest(batch_payload)}), "Saved batch resume fingerprint mismatch")
    # Evidence bytes may have changed: recheck those per sample, retaining their denominators.
    _check_files(batch_path.parent, batch_plan["sourceFilesSha256"],
                 {batch_path, _path(batch_path.parent, batch["manifestPath"]),
                  *(_path(batch_path.parent, row["casePath"]) for row in batch["entries"])})

    if child.get("batchBinding") is not None:
        binding = child["batchBinding"]
        require(isinstance(binding, dict) and set(binding) == {"batchId", "resultPath"}
                and isinstance(binding["batchId"], str) and str(UUID(binding["batchId"])) == binding["batchId"]
                and binding["resultPath"] == f"batches/{binding['batchId']}/batch-result.json", "Invalid continuation batch binding")
        require(child.get("batchResultPath") == binding["resultPath"] or child["status"] == "running" and child.get("batchResultPath") is None,
                "Continuation observed/reserved batch mismatch")
        new_path = _path(child_path.parent, binding["resultPath"])
    else:
        require(child["status"] != "running", "Unfinished legacy continuation lacks an explicit batch binding")
        new_path = _path(child_path.parent, child["batchResultPath"])
    new_batch = load_json(new_path)
    _terminal(new_batch, "batchResultFormatVersion", allow_unfinished=allow_unfinished)
    new_id = new_batch["batchId"]
    require(isinstance(new_id, str) and str(UUID(new_id)) == new_id and new_id != batch["batchId"]
            and new_path == _path(child_path.parent, f"batches/{new_id}/batch-result.json")
            and Path(new_batch["batchDirectory"]).resolve() == new_path.parent, "New batch identity/path mismatch")
    require((child["status"] == "running" or new_batch["status"] == child["status"]) and new_batch["failurePolicy"] == manifest["failurePolicy"]
            and new_batch["mode"] == "sequential" and new_batch["sourceManifest"] == str(child_path.parent / "remaining.batch.json"),
            "New batch source or scheduling mismatch")
    remaining = validate_batch(load_json(child_path.parent / "remaining.batch.json"))
    frozen = validate_batch(load_json(_path(new_path.parent, new_batch["manifestPath"])))
    require(isinstance(new_batch["entries"], list) and len(new_batch["entries"]) == len(frozen["cases"]) == len(remaining["cases"]) == len(pending),
            "New batch sample count mismatch")
    require(frozen["failurePolicy"] == remaining["failurePolicy"] == manifest["failurePolicy"]
            and frozen["batchName"] == remaining["batchName"] == batch["batchName"] + " continuation", "Remaining batch manifest mismatch")
    reused_by_id = {row["entryId"]: row for row in reused}
    require(len(reused_by_id) == len(reused) and len(set(pending)) == len(pending), "Duplicate continuation sample identity")
    require([row["entryId"] for row in new_batch["entries"]] == pending, "New batch sample order mismatch")
    pending_index, observed_reused = 0, []
    sample_inputs, new_cases = [], []
    seen = {key: set() for key in ("caseRunId", "runId", "sessionId")}
    for sample, identity, source_row in zip(plan["samples"], identities, batch["entries"]):
        require(isinstance(sample, dict), "Resume sample must be an object")
        require(all(_digest(sample.get(key)) == _digest(value) for key, value in identity.items()), "Resume sample position mismatch")
        sample_id = identity["sampleId"]
        expected = {**cases[identity["caseEntryId"]], "configRef": identity["requestedConfiguration"]}
        if sample["disposition"] == "reuse":
            require(sample_id in reused_by_id and sample_id not in pending, "Invalid reused sample binding")
            row = dict(reused_by_id[sample_id])
            require(row["status"] == "finished" and row.get("verification") == "verified"
                    and row.get("recoveredCheckpoint") is (source_row["status"] == "running"), "Invalid reused checkpoint state")
            for key, value in source_row.items():
                if value is not None and key != "status":
                    require(_digest(row.get(key)) == _digest(value), f"Reused source {key} mismatch")
            for key in ("caseRunId", "source", "outcome", "verification", "recoveredCheckpoint"):
                require(_digest(row[key]) == _digest(sample[key]), f"Reused sample {key} mismatch")
            observed_reused.append(sample_id)
            base, selected_batch, origin = batch_path.parent, batch, "reused"
            if row["recoveredCheckpoint"]:
                for key, name in (("evidencePath", "evidence.json"), ("evaluationPath", "evaluation.json"), ("runtimeReport", "runtime.json")):
                    row[key] = f"{row['caseDirectory']}/{name}"
                try:
                    evidence = load_json(_path(base, row["evidencePath"]))
                    row["runDir"] = _path(_path(base, row["caseDirectory"]), evidence["runDir"].replace("\\", "/")).relative_to(base).as_posix()
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    row["runDir"] = None
        else:
            require(sample["disposition"] == "pending" and source_row["status"] in ("pending", "skipped")
                    and all(sample.get(key) is None for key in ("caseRunId", "source", "outcome")), "Invalid new sample binding")
            require(pending_index < len(pending) and pending[pending_index] == sample_id, "Pending sample order mismatch")
            row = dict(new_batch["entries"][pending_index])
            frozen_entry, remaining_entry = frozen["cases"][pending_index], remaining["cases"][pending_index]
            require(row["entryId"] == frozen_entry["entryId"] == remaining_entry["entryId"] == sample_id
                    and row["casePath"] == frozen_entry["casePath"]
                    and row["sourceCasePath"] == str(_path(child_path.parent, remaining_entry["casePath"])), "Remaining input association mismatch")
            for base_path, entry in ((new_path.parent, frozen_entry), (child_path.parent, remaining_entry)):
                require(_digest(validate_case(load_json(_path(base_path, entry["casePath"])))) == _digest(expected), "New frozen input differs from original experiment")
            new_cases.append(expected)
            pending_index += 1
            base, selected_batch, origin = new_path.parent, new_batch, "new"
        require(row["caseId"] == identity["caseId"] and _digest(row["requestedConfiguration"]) == _digest(identity["requestedConfiguration"])
                and row["status"] in (("finished", "error", "skipped", "pending", "running") if allow_unfinished else ("finished", "error", "skipped")), "Continuation sample metadata mismatch")
        for key, values in seen.items():
            value = row[key]
            require(value is None or nonempty(value) and value not in values, f"Duplicate or invalid continuation {key}")
            if value is not None:
                values.add(value)
        if row["status"] in ("skipped", "pending"):
            require(all(row.get(key) is None for key in ("caseRunId", "runId", "sessionId", "source", "configuration", "outcome", "metrics",
                    "executionStatus", "recordingOutcome", "assertionOutcome", "caseDirectory", "evidencePath", "evaluationPath", "runtimeReport", "runDir")),
                    "Skipped continuation sample contains execution facts")
        else:
            require(nonempty(row["caseRunId"]) and row["caseDirectory"] == f"cases/{row['caseRunId']}", "Invalid case execution directory")
            for key, name in (("evidencePath", "evidence.json"), ("evaluationPath", "evaluation.json"), ("runtimeReport", "runtime.json")):
                require(row.get(key) is None and row["status"] in ("error", "running") or row.get(key) == f"{row['caseDirectory']}/{name}",
                        "Unexpected case artifact path")
        for key in ("casePath", "caseDirectory", "evidencePath", "evaluationPath", "runtimeReport", "runDir"):
            if row.get(key) is not None:
                _path(base, row[key])
        sample_inputs.append(({**row, **identity}, base, selected_batch["batchId"],
                              {"executionOrigin": origin, "sourceBatchId": selected_batch["batchId"],
                               "sourceBatchResult": str(batch_path if origin == "reused" else new_path)}))
    require(observed_reused == [row["entryId"] for row in reused] and pending_index == len(pending), "Incomplete continuation mapping")
    require(_digest(new_batch["inputFingerprint"]) == _digest(input_fingerprint(frozen, new_cases)), "New batch input fingerprint mismatch")
    metadata = {"comparisonReportFormatVersion": 2, "sourceResumeResult": str(source), "resumeId": resumed["resumeId"],
                "sourceExperimentResult": str(original_path), "batchId": None, "batchIds": [batch["batchId"], new_id],
                "resumeVerification": {"status": "verified", "planFingerprint": plan["planFingerprint"],
                                       "batchPlanFingerprint": plan["batchPlanFingerprint"], "batchResumeResult": str(child_path)}}
    return {**original, "summary": child.get("combinedSummary")}, manifest, cases, verification, sample_inputs, metadata
