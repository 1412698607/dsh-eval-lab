"""Summarize diagnostic assertions from freshly evaluated report samples."""
from collections import Counter

from .formats import require

OUTCOMES = ("passed", "failed", "insufficient_evidence", "not_run")


def diagnostic_sample(evaluation):
    rows = [row for row in evaluation["assertions"]["results"] if row.get("role") == "diagnostic"]
    return {"declaredAssertions": len(rows),
            "outcomes": {outcome: sum(row["outcome"] == outcome for row in rows) for outcome in OUTCOMES},
            "failedAssertionIds": [row["id"] for row in rows if row["outcome"] == "failed"],
            "insufficientAssertionIds": [row["id"] for row in rows if row["outcome"] == "insufficient_evidence"],
            "notRunAssertionIds": [row["id"] for row in rows if row["outcome"] == "not_run"]}


def diagnostic_summary(samples):
    observed = [row for row in samples if row.get("diagnosticSummary") is not None]
    failed = [row for row in observed if row["diagnosticSummary"]["outcomes"]["failed"] > 0]
    return {"observedSamples": len(observed), "missingSamples": len(samples) - len(observed),
            "samplesWithDiagnostics": sum(row["diagnosticSummary"]["declaredAssertions"] > 0 for row in observed),
            "samplesWithFailures": len(failed),
            "passedSamplesWithFailures": sum(row["outcome"] == "passed" for row in failed),
            "assertionCounts": {outcome: sum(row["diagnosticSummary"]["outcomes"][outcome] for row in observed)
                                for outcome in OUTCOMES}}


ROLES = ("required", "diagnostic")
GLOBAL_GATE_CODES = frozenset(("recording_not_complete", "execution_not_completed", "evaluation_evidence_invalid"))
ROOT_REASON_CODES = frozenset(("environment_snapshot_missing", "environment_files_mismatch", "final_text_mismatch",
                               "turn_end_mismatch", "forbidden_tool_observed", "tool_call_count_out_of_bounds",
                               "tool_evidence_missing", "tool_result_mismatch", "tool_order_mismatch",
                               "tool_result_and_order_mismatch"))
REASON_CODES = ROOT_REASON_CODES | GLOBAL_GATE_CODES | {"matched", "dependency_not_passed"}
MISSING_CAUSE_CODES = frozenset(("missing_metadata", "unsupported_version", "invalid_metadata", "not_evaluated"))
REASON_TYPES = {"environment_snapshot_missing": "environment_files", "environment_files_mismatch": "environment_files",
                "final_text_mismatch": "final_text", "turn_end_mismatch": "turn_end",
                "forbidden_tool_observed": "tool_forbidden", "tool_call_count_out_of_bounds": "tool_call_count",
                **{code: "tool_result" for code in ("tool_evidence_missing", "tool_result_mismatch", "tool_order_mismatch",
                                                   "tool_result_and_order_mismatch", "dependency_not_passed")}}


def _unavailable_causes(reason):
    return {"assertionCausesFormatVersion": 1, "status": "unavailable", "reasonCode": reason}


def assertion_causes(evaluation):
    """Classify saved scoring branches, without deriving causes from reason prose."""
    if not isinstance(evaluation, dict):
        return _unavailable_causes("invalid_metadata")
    saved = evaluation.get("assertionDiagnostics")
    if saved is None:
        return _unavailable_causes("missing_metadata")
    if not isinstance(saved, dict):
        return _unavailable_causes("invalid_metadata")
    if type(saved.get("assertionDiagnosticsFormatVersion")) is not int or saved["assertionDiagnosticsFormatVersion"] != 1:
        return _unavailable_causes("unsupported_version")
    try:
        legacy, metadata = evaluation["assertions"]["results"], saved["results"]
        require(isinstance(legacy, list) and bool(legacy) and isinstance(metadata, list)
                and len(legacy) == len(metadata), "Incomplete assertion diagnostics")
        for rows in (legacy, metadata):
            require(all(isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"]
                        and isinstance(row.get("type"), str) and row["type"]
                        and row.get("outcome") in OUTCOMES for row in rows), "Invalid diagnostic identity")
            require(len({row["id"] for row in rows}) == len(rows), "Duplicate diagnostic identity")
        definitions = None
        if "case" in evaluation:
            declared = evaluation["case"]["assertions"]
            require(isinstance(declared, list) and len(declared) == len(legacy), "Invalid frozen assertions")
            definitions = {row["id"]: row for row in declared}
            require(len(definitions) == len(legacy), "Duplicate frozen assertions")
        by_id = {row["id"]: row for row in metadata}
        positions = {row["id"]: index for index, row in enumerate(legacy)}
        require(by_id.keys() == positions.keys(), "Unmatched diagnostic identities")
        classified = {role: {"declaredAssertions": 0, "rootIssues": [], "blockedAssertions": [], "globalGates": []}
                      for role in ROLES}
        for row in legacy:
            item = by_id[row["id"]]
            role = row.get("role", "required")
            require(role in ROLES and item.get("role", role) == role
                    and item["type"] == row["type"] and item["outcome"] == row["outcome"], "Mismatched diagnostic row")
            code = item.get("reasonCode")
            require(code in REASON_CODES, "Unsupported reason code")
            require(code not in REASON_TYPES or REASON_TYPES[code] == row["type"], "Reason conflicts with assertion type")
            require("observedMatches" not in item or isinstance(item["observedMatches"], list), "Invalid observed matches")
            after, blockers = item.get("after"), item.get("blockedBy", [])
            require(isinstance(blockers, list) and all(isinstance(value, str) for value in blockers), "Invalid blockers")
            if definitions is not None:
                rule = definitions[row["id"]]
                require(rule["type"] == row["type"] and rule.get("role", "required") == role
                        and rule.get("after") == after, "Diagnostic differs from frozen assertion")
            predecessor = None
            if "after" in item:
                require(row["type"] == "tool_result" and isinstance(after, str) and after in positions
                        and positions[after] < positions[row["id"]] and by_id[after]["type"] == "tool_result",
                        "Invalid dependency reference or cycle")
                predecessor = by_id[after]
            if code == "dependency_not_passed":
                require(predecessor is not None and blockers == [after] and predecessor["outcome"] != "passed"
                        and row["outcome"] == ("failed" if predecessor["outcome"] == "failed" else "insufficient_evidence"),
                        "Contradictory dependency result")
            else:
                require(not blockers and (code in GLOBAL_GATE_CODES or predecessor is None
                                         or predecessor["outcome"] == "passed"), "Unreported dependency block")
                expected = ("passed" if code == "matched" else "not_run" if code in
                            ("recording_not_complete", "execution_not_completed") else "insufficient_evidence" if code in
                            ("environment_snapshot_missing", "tool_evidence_missing", "evaluation_evidence_invalid") else "failed")
                require(row["outcome"] == expected, "Reason conflicts with scoring outcome")
            target = classified[role]
            target["declaredAssertions"] += 1
            if code in ROOT_REASON_CODES:
                target["rootIssues"].append({"id": row["id"], "reasonCode": code})
            elif code == "dependency_not_passed":
                target["blockedAssertions"].append({"id": row["id"], "blockedBy": list(blockers)})
            elif code in GLOBAL_GATE_CODES:
                target["globalGates"].append({"id": row["id"], "reasonCode": code})
        return {"assertionCausesFormatVersion": 1, "status": "available", "byRole": classified}
    except (KeyError, TypeError, ValueError):
        return _unavailable_causes("invalid_metadata")


def _cause_availability(value):
    if value is None:
        return "missing_metadata"
    if not isinstance(value, dict):
        return "invalid_metadata"
    if type(value.get("assertionCausesFormatVersion")) is not int or value["assertionCausesFormatVersion"] != 1:
        return "unsupported_version"
    if value.get("status") == "unavailable":
        reason = value.get("reasonCode")
        return reason if isinstance(reason, str) and reason in MISSING_CAUSE_CODES else "invalid_metadata"
    try:
        require(value.get("status") == "available" and isinstance(value["byRole"], dict), "Invalid cause sample")
        identities = []
        for role in ROLES:
            data = value["byRole"][role]
            require(type(data["declaredAssertions"]) is int and data["declaredAssertions"] >= 0, "Invalid declared count")
            for key, reasons in (("rootIssues", ROOT_REASON_CODES), ("globalGates", GLOBAL_GATE_CODES),
                                 ("blockedAssertions", None)):
                require(isinstance(data[key], list), "Invalid cause rows")
                for item in data[key]:
                    require(isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"], "Invalid cause ID")
                    identities.append(item["id"])
                    if reasons is not None:
                        require(item.get("reasonCode") in reasons, "Invalid cause reason")
                    else:
                        require(isinstance(item.get("blockedBy"), list) and len(item["blockedBy"]) == 1
                                and isinstance(item["blockedBy"][0], str) and item["blockedBy"][0], "Invalid direct blocker")
            require(sum(len(data[key]) for key in ("rootIssues", "globalGates", "blockedAssertions"))
                    <= data["declaredAssertions"], "Cause rows exceed declared assertions")
        require(len(set(identities)) == len(identities), "Repeated cause identity")
    except (KeyError, TypeError, ValueError):
        return "invalid_metadata"
    return None


def assertion_cause_summary(samples):
    """Count affected samples once per reason and role; keep coverage separate from zero issues."""
    missing, available = Counter(), []
    identities = Counter(row.get("sampleId") for row in samples if isinstance(row, dict) and isinstance(row.get("sampleId"), str))
    for row in samples:
        if not isinstance(row, dict):
            missing["invalid_metadata"] += 1
            continue
        reason = _cause_availability(row.get("assertionCauses"))
        if reason is None and (not isinstance(row.get("sampleId"), str) or not row["sampleId"]
                               or identities[row["sampleId"]] != 1):
            reason = "invalid_metadata"
        if reason is None:
            available.append(row)
        else:
            missing[reason] += 1
    roles = {}
    for role in ROLES:
        rows = [(row["sampleId"], row["assertionCauses"]["byRole"][role]) for row in available]
        root_reasons, gate_reasons = {}, {}
        for sample_id, data in rows:
            for key, reasons in (("rootIssues", root_reasons), ("globalGates", gate_reasons)):
                for code in sorted({item["reasonCode"] for item in data[key]}):
                    reasons.setdefault(code, []).append(sample_id)
        def grouped(reasons):
            return [{"reasonCode": code, "affectedSamples": len(ids), "sampleIds": ids}
                    for code, ids in sorted(reasons.items())]
        roles[role] = {"declaredSamples": sum(data["declaredAssertions"] > 0 for _, data in rows),
                       "rootAffectedSamples": sum(bool(data["rootIssues"]) for _, data in rows),
                       "blockedAffectedSamples": sum(bool(data["blockedAssertions"]) for _, data in rows),
                       "globalGateAffectedSamples": sum(bool(data["globalGates"]) for _, data in rows),
                       "rootIssueCount": sum(len(data["rootIssues"]) for _, data in rows),
                       "blockedAssertionCount": sum(len(data["blockedAssertions"]) for _, data in rows),
                       "rootReasons": grouped(root_reasons), "globalGateReasons": grouped(gate_reasons),
                       "blockedSampleIds": [sample_id for sample_id, data in rows if data["blockedAssertions"]]}
    return {"assertionCauseSummaryFormatVersion": 1, "plannedSamples": len(samples), "availableSamples": len(available),
            "missingSamples": len(samples) - len(available), "missingReasons": dict(sorted(missing.items())), "byRole": roles}
