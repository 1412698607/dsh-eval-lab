"""Measure assertion-only rule changes across one frozen, completed experiment."""
from collections import Counter
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .assertion_comparison import _NotAnInputFile, _file_digest, _read_input, _source_state, compare_assertions
from .environment import snapshot_digest
from .experiment import _sample_plan
from .formats import fields, require, validate_case
from .report import _load_report_inputs, _path, _recheck


def _sample_state(directory, sample):
    """Track just the expected cases, evidence, runtime and recording, including missing files."""
    errors = []

    def file_digest(path):
        try:
            return _file_digest(path)
        except (OSError, _NotAnInputFile) as error:
            # Keep the rest of this archive in the snapshot and remember the unreadable input.
            reason = f"Cannot hash {path}: {error}"
            errors.append(reason)
            return reason

    paths = [_path(directory, sample["casePath"])] if sample.get("casePath") is not None else []
    if sample.get("caseDirectory") is not None:
        paths.append(_path(directory, sample["caseDirectory"] + "/case.json"))
    if sample.get("evidencePath") is None:
        state = {str(path): file_digest(path) for path in paths}
        return state, sorted(errors)
    evidence_path = _path(directory, sample["evidencePath"])
    expected_paths = {"runDir": _path(directory, sample["runDir"]) if sample.get("runDir") is not None else None}
    if sample.get("runtimeReport") is not None:
        expected_paths["runtimeReport"] = _path(directory, sample["runtimeReport"])
    try:
        state = _source_state(evidence_path, paths, expected_paths, file_digest=file_digest)
    except OSError as error:  # Directory enumeration failure; containment violations still raise.
        errors.append(f"Cannot inspect sample inputs: {error}")
        state = {}
    return state, sorted(errors)


def _preview_sample(sample, expected, directory, batch_id, candidate_path, errors):
    row = {key: sample[key] for key in ("sampleId", "caseEntryId", "caseId", "configurationId", "repeatIndex",
                                       "status", "caseRunId", "runId", "sessionId")}
    row.update(evidencePath=None, transition="inconclusive", baselineOutcome=None, candidateOutcome=None,
               changedAssertionIds=[], changes=[], source=None, verification="unavailable",
               configurationMatch="unknown", reasons=list(errors))
    if errors:
        return row
    checked, fresh = _recheck(sample, expected, directory, batch_id)
    row.update({key: checked[key] for key in ("source", "verification", "configurationMatch", "reasons")})
    row.update(evidencePath=checked["sourceEvidencePath"], baselineOutcome=fresh["outcome"] if fresh else None)
    if sample["status"] != "finished" or fresh is None or checked["configurationMatch"] != "matched":
        if fresh is not None:
            row["reasons"].extend(fresh["recording"].get("reasons", []))
        if checked["configurationReason"]:
            row["reasons"].append(checked["configurationReason"])
        if not row["reasons"]:
            row["reasons"].append(f"Sample status: {sample['status']}")
        return row

    evidence_path = Path(checked["sourceEvidencePath"])
    if not sample.get("caseDirectory") or _path(directory, sample["caseDirectory"]) != evidence_path.parent:
        row["reasons"].append("Evidence is not in the bound case directory")
        return row
    comparison = compare_assertions(evidence_path, candidate_path)
    require(comparison.get("batchId") == batch_id and comparison["baseline"]["caseSha256"] == snapshot_digest(expected)
            and all(comparison[key] == checked[key] for key in ("caseRunId", "runId", "sessionId", "source")),
            "Sample comparison no longer matches frozen case or evidence")
    require(comparison["baseline"]["outcome"] == fresh["outcome"] and
            [item["baseline"]["result"] for item in comparison["assertions"] if item["baseline"]] == fresh["assertions"]["results"],
            "Fresh baseline scoring changed during comparison")
    row["candidateOutcome"] = comparison["candidate"]["outcome"]
    row["changedAssertionIds"] = comparison["summary"]["changedAssertionIds"]
    changed = set(row["changedAssertionIds"])
    row["changes"] = [item for item in comparison["assertions"] if item["id"] in changed]
    if comparison["status"] == "compared":
        row["transition"] = {("passed", "passed"): "unchangedPassed", ("failed", "failed"): "unchangedFailed",
                             ("passed", "failed"): "passToFail", ("failed", "passed"): "failToPass"}[
                                 row["baselineOutcome"], row["candidateOutcome"]]
    else:
        for side in ("baseline", "candidate"):
            state = comparison[side]
            if state["outcome"] != "unevaluable":
                continue
            reasons = list(state["recordingReasons"])
            if state["assertionReason"]:
                reasons.append(state["assertionReason"])
            for item in comparison["assertions"]:
                rule = item[side]
                if rule and rule["definition"].get("role", "required") == "required":
                    result = rule["result"]
                    if result["outcome"] in ("not_run", "insufficient_evidence"):
                        reasons.append(f"{item['id']}: {result.get('reason', result['outcome'])}")
            for reason in reasons or [f"Execution {state['executionStatus']}, assertions {state['assertionOutcome']}"]:
                row["reasons"].append(f"{side}: {reason}")
    return row


def preview_experiment_assertions(experiment_path, rule_map_path):
    """Apply per-case assertion lists to archived samples; never run a model or write to the archive."""
    source = Path(experiment_path).resolve()
    directory = source.parent
    rule_map_path = Path(rule_map_path).resolve()
    hashes = {}
    header = _read_input(source, hashes)
    require(isinstance(header, dict) and "experimentResumeResultFormatVersion" not in header
            and type(header.get("experimentResultFormatVersion")) is int and header["experimentResultFormatVersion"] == 1
            and header.get("status") == "completed", "Preview requires a completed ordinary experiment result")
    for key in ("manifestPath", "batchResultPath", "planInputPath"):
        path = _path(directory, header.get(key))
        hashes[str(path)] = _file_digest(path)
    rule_map = _read_input(rule_map_path, hashes)
    fields(rule_map, ("assertionRuleMapFormatVersion", "cases"))
    require(type(rule_map["assertionRuleMapFormatVersion"]) is int and rule_map["assertionRuleMapFormatVersion"] == 1,
            "Unsupported assertion rule map version")
    saved, manifest, cases, verified, inputs, _ = _load_report_inputs(source)
    require(verified["status"] == "verified", "Preview requires a verified frozen plan")
    if "batchBinding" in saved or "resumeSupportVersion" in saved:
        from .experiment_resume import _binding
        require(_binding(saved, directory) == _path(directory, saved["batchResultPath"])
                and saved["batchBinding"]["batchId"] == saved["batchId"], "Frozen experiment batch binding mismatch")
    require([row["sampleId"] for row in saved["samples"]] == [row["sampleId"] for row in _sample_plan(manifest)],
            "Frozen experiment sample identity/order mismatch")
    rules = rule_map["cases"]
    require(isinstance(rules, dict) and rules.keys() == cases.keys(), "Rule map must cover exactly the frozen case entry IDs")
    for entry in manifest["cases"]:
        key = entry["entryId"]
        frozen = _read_input(_path(directory, entry["casePath"]), hashes)
        require(snapshot_digest(frozen) == snapshot_digest(cases[key]), "Frozen case changed during plan verification")
        validate_case({**frozen, "assertions": rules[key]})

    inputs = list(inputs)
    before = [_sample_state(base, sample) for sample, base, _, _ in inputs]
    rows = []
    with TemporaryDirectory(prefix="dsh-rules-") as temp:
        candidate_path = Path(temp) / "candidate.json"
        for (sample, base, batch_id, _), (_, errors) in zip(inputs, before):
            key = sample["caseEntryId"]
            expected = {**cases[key], "configRef": sample["requestedConfiguration"]}
            candidate = {**expected, "assertions": rules[key]}
            candidate_path.write_text(json.dumps(candidate, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            rows.append(_preview_sample(sample, expected, base, batch_id, candidate_path, errors))

    require(all(_file_digest(Path(path)) == digest for path, digest in hashes.items())
            and before == [_sample_state(base, sample) for sample, base, _, _ in inputs], "Preview source files changed")
    totals = Counter(row["transition"] for row in rows)
    inconclusive = totals["inconclusive"]
    summary = {"plannedSamples": len(rows), "comparedSamples": len(rows) - inconclusive,
               **{key: totals[key] for key in ("passToFail", "failToPass", "unchangedPassed", "unchangedFailed", "inconclusive")}}
    return {"experimentAssertionPreviewFormatVersion": 1, "modelCalled": False,
            "status": "inconclusive" if inconclusive else "compared", "exitCode": 2 if inconclusive else 0,
            "experimentId": saved["experimentId"], "experimentPath": str(source), "ruleMapPath": str(rule_map_path),
            "ruleMapSha256": snapshot_digest(rule_map), "planFingerprint": verified["fingerprint"],
            "summary": summary, "samples": rows}
