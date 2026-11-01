"""Compare freshly rechecked samples from two independently recorded experiments."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .formats import require
from .report import _load_report_inputs, _recheck, _same


CONFIG_FIELDS = ("provider", "model", "profile", "pluginVersion")


def _load_side(path, configuration_id):
    source = Path(path).resolve()
    saved, manifest, cases, plan, inputs, _ = _load_report_inputs(source)
    configurations = manifest["configurations"]
    require(configuration_id is not None or len(configurations) == 1,
            "Select a configuration explicitly when an experiment has multiple configurations")
    selected = next((item for item in configurations if configuration_id is None
                     or item["configurationId"] == configuration_id), None)
    require(selected is not None, f"Unknown configuration: {configuration_id}")
    rows = {}
    for sample, directory, batch_id, provenance in inputs:
        if sample["configurationId"] != selected["configurationId"]:
            continue
        key = (sample["caseEntryId"], sample["repeatIndex"])
        require(key not in rows, "Duplicate regression sample key")
        expected = {**cases[sample["caseEntryId"]], "configRef": sample["requestedConfiguration"]}
        row, _ = _recheck(sample, expected, directory, batch_id)
        row.update(provenance)
        rows[key] = row
    return {"sourceResult": str(source), "experimentId": saved["experimentId"],
            "configuration": selected, "planVerification": plan, "plannedSamples": len(rows)}, cases, rows


def _evaluable(row):
    return (row["status"] == "finished" and row["verification"] == "verified"
            and row["configurationMatch"] == "matched" and row["executionStatus"] == "completed"
            and row["recordingOutcome"] == "complete" and row["assertionOutcome"] in ("passed", "failed")
            and row["outcome"] in ("passed", "failed") and row["source"] in ("live", "synthetic"))


def compare_baseline(baseline_path, candidate_path, *, baseline_config=None, candidate_config=None,
                     allow_config_changes=()):
    require(isinstance(allow_config_changes, (list, tuple))
            and all(isinstance(key, str) and key in CONFIG_FIELDS for key in allow_config_changes),
            "Unsupported allowed configuration change")
    allowed = sorted(set(allow_config_changes))
    baseline, old_cases, old = _load_side(baseline_path, baseline_config)
    candidate, new_cases, new = _load_side(candidate_path, candidate_config)
    changes = [{"field": key, "baseline": baseline["configuration"]["configRef"][key],
                "candidate": candidate["configuration"]["configRef"][key], "allowed": key in allowed}
               for key in CONFIG_FIELDS if not _same(baseline["configuration"]["configRef"][key],
                                                     candidate["configuration"]["configRef"][key])]
    issues = []
    if baseline["experimentId"] == candidate["experimentId"]:
        issues.append("same_experiment")
    for label, side in (("baseline", baseline), ("candidate", candidate)):
        if side["planVerification"]["status"] != "verified":
            issues.append(label + "_plan_unverified")
    if any(not change["allowed"] for change in changes):
        issues.append("configuration_changed_without_permission")
    for identity in ("caseRunId", "runId", "sessionId"):
        left_ids = {row[identity] for row in old.values() if row[identity] is not None}
        right_ids = {row[identity] for row in new.values() if row[identity] is not None}
        if left_ids & right_ids:
            issues.append("shared_" + identity)
    rows = []
    for case_id, repeat in sorted(old.keys() | new.keys()):
        left, right = old.get((case_id, repeat)), new.get((case_id, repeat))
        reasons, task_changes = [], []
        if left is None:
            change = "missing_in_baseline"
        elif right is None:
            change = "missing_in_candidate"
        else:
            old_task = {key: value for key, value in old_cases[case_id].items() if key != "configRef"}
            new_task = {key: value for key, value in new_cases[case_id].items() if key != "configRef"}
            reasons.extend(issues)
            task_changes = [key for key in sorted(old_task.keys() | new_task.keys())
                            if (key in old_task) != (key in new_task) or not _same(old_task.get(key), new_task.get(key))]
            if task_changes:
                reasons.append("task_input_changed")
            if left["source"] is not None and right["source"] is not None and left["source"] != right["source"]:
                reasons.append("source_mismatch")
            if reasons:
                change = "incompatible"
            else:
                for label, row in (("baseline", left), ("candidate", right)):
                    if not _evaluable(row):
                        reasons.append(label + "_evidence_unavailable")
                if reasons:
                    change = "unavailable"
                elif left["outcome"] == right["outcome"]:
                    change = "unchanged_" + left["outcome"]
                else:
                    change = "regression" if left["outcome"] == "passed" else "improvement"
        rows.append({"caseEntryId": case_id, "repeatIndex": repeat, "change": change,
                     "reasons": reasons, "taskChanges": task_changes, "baseline": left, "candidate": right})
    counts = {name: 0 for name in ("regression", "improvement", "unchanged_passed", "unchanged_failed",
                                   "missing_in_baseline", "missing_in_candidate", "incompatible", "unavailable")}
    counts.update(Counter(row["change"] for row in rows))
    compared = sum(counts[name] for name in ("regression", "improvement", "unchanged_passed", "unchanged_failed"))
    complete = not issues and compared == len(rows) and compared > 0
    code = 2 if not complete else 1 if counts["regression"] else 0
    return {"regressionComparisonFormatVersion": 1, "generatedAt": datetime.now(timezone.utc).isoformat(),
            "status": "compared", "modelCalled": False, "baseline": baseline, "candidate": candidate,
            "allowedConfigurationChanges": allowed, "configurationChanges": changes,
            "comparability": {"status": "comparable" if complete else "incomplete", "issues": issues},
            "counts": {**counts, "compared": compared, "total": len(rows)}, "samples": rows,
            "hasRegressions": counts["regression"] > 0,
            "outcome": {0: "passed", 1: "failed", 2: "unevaluable"}[code], "exitCode": code,
            "limitations": ["Comparisons describe rechecked samples, not statistical significance or causal improvement.",
                            "Keys are caseEntryId and repeatIndex; sample IDs are not aligned across experiments.",
                            "Missing or incompatible samples prevent a successful gate; confirmed regressions remain listed.",
                            "Source declarations are not signatures. Use stable archives; this is not an atomic snapshot."]}
