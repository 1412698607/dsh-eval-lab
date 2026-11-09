"""Structured reason coverage counts affected samples, independently of diagnostic assertion roles."""
from copy import deepcopy
import unittest

from dsh_eval.diagnostics import assertion_causes, assertion_cause_summary


def evaluation(*items):
    legacy, metadata, rules = [], [], []
    for item in items:
        item = {"type": "tool_result", **item}
        legacy.append({key: item[key] for key in ("id", "type", "outcome", "role") if key in item})
        metadata.append({key: value for key, value in item.items() if key != "role"})
        rules.append({key: item[key] for key in ("id", "type", "role", "after") if key in item})
    return {"case": {"assertions": rules}, "assertions": {"results": legacy},
            "assertionDiagnostics": {"assertionDiagnosticsFormatVersion": 1, "results": metadata}}


def chain():
    return evaluation(
        {"id": "source", "outcome": "insufficient_evidence", "reasonCode": "tool_evidence_missing"},
        {"id": "target", "outcome": "insufficient_evidence", "reasonCode": "dependency_not_passed",
         "after": "source", "blockedBy": ["source"], "observedMatches": []},
        {"id": "retry", "outcome": "insufficient_evidence", "reasonCode": "dependency_not_passed",
         "after": "target", "blockedBy": ["target"], "observedMatches": [{"resultSeq": 5}]},
        {"id": "verify", "outcome": "insufficient_evidence", "reasonCode": "dependency_not_passed",
         "after": "retry", "blockedBy": ["retry"], "observedMatches": [{"resultSeq": 7}]})


def sample(identity, value):
    return {"sampleId": identity, "source": "synthetic", "assertionCauses": assertion_causes(value)}


class AssertionCauseSummaryTests(unittest.TestCase):
    def test_one_original_issue_and_three_blocked_steps_are_not_four_root_causes(self):
        original = chain()
        before = deepcopy(original)
        result = assertion_causes(original)
        self.assertEqual((result["assertionCausesFormatVersion"], result["status"]), (1, "available"))
        required = result["byRole"]["required"]
        self.assertEqual(required["declaredAssertions"], 4)
        self.assertEqual(required["rootIssues"], [{"id": "source", "reasonCode": "tool_evidence_missing"}])
        self.assertEqual(required["blockedAssertions"], [
            {"id": "target", "blockedBy": ["source"]}, {"id": "retry", "blockedBy": ["target"]},
            {"id": "verify", "blockedBy": ["retry"]}])
        self.assertEqual(required["globalGates"], [])
        summary = assertion_cause_summary([sample("one", original)])
        stats = summary["byRole"]["required"]
        self.assertEqual((stats["declaredSamples"], stats["rootAffectedSamples"], stats["blockedAffectedSamples"],
                          stats["rootIssueCount"], stats["blockedAssertionCount"]), (1, 1, 1, 1, 3))
        self.assertEqual(stats["rootReasons"], [{"reasonCode": "tool_evidence_missing", "affectedSamples": 1, "sampleIds": ["one"]}])
        self.assertEqual(stats["blockedSampleIds"], ["one"])
        self.assertEqual(original, before)

    def test_matched_declared_roles_are_available_zero_issues_not_missing(self):
        positive = evaluation(
            {"id": "read", "outcome": "passed", "reasonCode": "matched"},
            {"id": "verify", "outcome": "passed", "reasonCode": "matched", "after": "read"},
            {"id": "format", "type": "final_text", "role": "diagnostic", "outcome": "passed", "reasonCode": "matched"})
        summary = assertion_cause_summary([sample("ok", positive)])
        self.assertEqual((summary["plannedSamples"], summary["availableSamples"], summary["missingSamples"]), (1, 1, 0))
        self.assertEqual(summary["missingReasons"], {})
        for role in ("required", "diagnostic"):
            stats = summary["byRole"][role]
            self.assertEqual(stats["declaredSamples"], 1)
            self.assertEqual((stats["rootAffectedSamples"], stats["blockedAffectedSamples"], stats["globalGateAffectedSamples"]), (0, 0, 0))
        absent = assertion_cause_summary([sample("no-diagnostic", evaluation(
            {"id": "read", "outcome": "passed", "reasonCode": "matched"}))])
        self.assertEqual(absent["byRole"]["diagnostic"]["declaredSamples"], 0)

    def test_missing_unsupported_invalid_and_unevaluated_metadata_retain_denominator(self):
        unknown = evaluation({"id": "read", "outcome": "passed", "reasonCode": "matched"})
        unknown["assertionDiagnostics"]["assertionDiagnosticsFormatVersion"] = 2
        invalid = chain()
        invalid["assertionDiagnostics"]["results"].pop()
        old = {"assertions": {"results": [{"id": "old", "type": "tool_result", "outcome": "insufficient_evidence",
                                           "reason": "Required earlier tool result assertion source did not pass"}]}}
        rows = [sample("ok", evaluation({"id": "read", "outcome": "passed", "reasonCode": "matched"})),
                sample("old", old), sample("unsupported", unknown), sample("invalid", invalid),
                {"sampleId": "unexecuted", "assertionCauses": {"assertionCausesFormatVersion": 1,
                 "status": "unavailable", "reasonCode": "not_evaluated"}}]
        summary = assertion_cause_summary(rows)
        self.assertEqual((summary["plannedSamples"], summary["availableSamples"], summary["missingSamples"]), (5, 1, 4))
        self.assertEqual(summary["missingReasons"], {"invalid_metadata": 1, "missing_metadata": 1, "not_evaluated": 1, "unsupported_version": 1})
        self.assertEqual(summary["byRole"]["required"]["rootAffectedSamples"], 0)
        self.assertEqual(assertion_causes(old)["reasonCode"], "missing_metadata")

    def test_same_reason_is_deduplicated_per_sample_while_distinct_roots_are_preserved(self):
        two = evaluation(
            {"id": "a", "outcome": "insufficient_evidence", "reasonCode": "tool_evidence_missing"},
            {"id": "b", "outcome": "insufficient_evidence", "reasonCode": "tool_evidence_missing"},
            {"id": "c", "outcome": "insufficient_evidence", "reasonCode": "dependency_not_passed", "after": "b", "blockedBy": ["b"]})
        summary = assertion_cause_summary([sample("second", two), sample("first", chain())])
        required = summary["byRole"]["required"]
        self.assertEqual((required["rootAffectedSamples"], required["rootIssueCount"], required["blockedAffectedSamples"],
                          required["blockedAssertionCount"]), (2, 3, 2, 4))
        self.assertEqual(required["rootReasons"], [{"reasonCode": "tool_evidence_missing", "affectedSamples": 2,
                                                   "sampleIds": ["second", "first"]}])

    def test_diagnostic_failures_and_failed_predecessor_are_separate_from_required_issues(self):
        value = evaluation(
            {"id": "required", "outcome": "passed", "reasonCode": "matched"},
            {"id": "diag", "role": "diagnostic", "outcome": "failed", "reasonCode": "tool_result_mismatch"},
            {"id": "blocked", "role": "diagnostic", "outcome": "failed", "reasonCode": "dependency_not_passed",
             "after": "diag", "blockedBy": ["diag"], "observedMatches": [{"resultSeq": 12}]},
            {"id": "format", "type": "final_text", "role": "diagnostic", "outcome": "failed", "reasonCode": "final_text_mismatch"})
        summary = assertion_cause_summary([sample("diagnostic-only", value)])
        self.assertEqual(summary["byRole"]["required"]["rootAffectedSamples"], 0)
        diagnostic = summary["byRole"]["diagnostic"]
        self.assertEqual((diagnostic["declaredSamples"], diagnostic["rootAffectedSamples"], diagnostic["rootIssueCount"],
                          diagnostic["blockedAffectedSamples"]), (1, 1, 2, 1))
        self.assertEqual([row["reasonCode"] for row in diagnostic["rootReasons"]], ["final_text_mismatch", "tool_result_mismatch"])

    def test_global_gates_are_deduplicated_without_creating_step_roots(self):
        for code, outcome in (("recording_not_complete", "not_run"), ("execution_not_completed", "not_run"),
                              ("evaluation_evidence_invalid", "insufficient_evidence")):
            with self.subTest(code=code):
                value = evaluation({"id": "a", "outcome": outcome, "reasonCode": code},
                                   {"id": "b", "outcome": outcome, "reasonCode": code, "after": "a"},
                                   {"id": "format", "type": "final_text", "role": "diagnostic", "outcome": outcome, "reasonCode": code})
                stats = assertion_cause_summary([sample("gated", value)])["byRole"]["required"]
                self.assertEqual((stats["rootAffectedSamples"], stats["blockedAffectedSamples"], stats["globalGateAffectedSamples"]), (0, 0, 1))
                self.assertEqual(stats["globalGateReasons"], [{"reasonCode": code, "affectedSamples": 1, "sampleIds": ["gated"]}])

    def test_reordered_metadata_uses_legacy_assertion_order_and_does_not_mutate_inputs(self):
        value = chain()
        value["assertionDiagnostics"]["results"].reverse()
        before = deepcopy(value)
        result = assertion_causes(value)
        self.assertEqual(result["status"], "available")
        self.assertEqual([row["id"] for row in result["byRole"]["required"]["blockedAssertions"]], ["target", "retry", "verify"])
        self.assertEqual(value, before)

    def test_bad_identity_type_outcome_role_reason_or_dependency_is_unavailable(self):
        variants = []
        value = chain(); value["assertionDiagnostics"]["results"][0]["id"] = "unknown"; variants.append(value)
        value = chain(); value["assertionDiagnostics"]["results"][0]["type"] = "final_text"; variants.append(value)
        value = chain(); value["assertionDiagnostics"]["results"][0]["outcome"] = "failed"; variants.append(value)
        value = chain(); value["assertionDiagnostics"]["results"][0]["role"] = "diagnostic"; variants.append(value)
        value = chain(); value["assertionDiagnostics"]["results"][0]["reasonCode"] = "unknown"; variants.append(value)
        value = chain(); value["assertionDiagnostics"]["results"][1]["blockedBy"] = ["verify"]; variants.append(value)
        value = chain(); value["assertionDiagnostics"]["results"][0] = deepcopy(value["assertionDiagnostics"]["results"][1]); variants.append(value)
        value = chain(); value["assertionDiagnostics"]["results"][0]["after"] = "verify"; variants.append(value)
        value = chain(); value["case"]["assertions"][1]["after"] = "retry"; variants.append(value)
        for value in variants:
            with self.subTest(value=value):
                self.assertEqual(assertion_causes(value), {"assertionCausesFormatVersion": 1,
                                                          "status": "unavailable", "reasonCode": "invalid_metadata"})

    def test_passed_prerequisite_and_wrong_propagated_outcome_cannot_claim_blocking(self):
        for predecessor, successor in (("passed", "insufficient_evidence"), ("failed", "insufficient_evidence"),
                                       ("insufficient_evidence", "failed")):
            code = {"passed": "matched", "failed": "tool_result_mismatch", "insufficient_evidence": "tool_evidence_missing"}[predecessor]
            value = evaluation({"id": "a", "outcome": predecessor, "reasonCode": code},
                               {"id": "b", "outcome": successor, "reasonCode": "dependency_not_passed", "after": "a", "blockedBy": ["a"]})
            with self.subTest(predecessor=predecessor, successor=successor):
                self.assertEqual(assertion_causes(value)["reasonCode"], "invalid_metadata")

    def test_malformed_derived_samples_and_duplicate_sample_ids_keep_missing_coverage(self):
        available = sample("one", chain())
        malformed = deepcopy(available)
        malformed["sampleId"] = "bad"
        malformed["assertionCauses"]["byRole"]["required"]["declaredAssertions"] = 0
        unsupported = deepcopy(available)
        unsupported["sampleId"] = "future"
        unsupported["assertionCauses"]["assertionCausesFormatVersion"] = 2
        rows = [available, deepcopy(available), malformed, unsupported, {"sampleId": "legacy"}]
        summary = assertion_cause_summary(rows)
        self.assertEqual((summary["plannedSamples"], summary["availableSamples"], summary["missingSamples"]), (5, 0, 5))
        self.assertEqual(summary["missingReasons"], {"invalid_metadata": 3, "missing_metadata": 1, "unsupported_version": 1})

    def test_boolean_format_version_is_not_supported_and_empty_input_has_zero_coverage(self):
        value = chain()
        value["assertionDiagnostics"]["assertionDiagnosticsFormatVersion"] = True
        self.assertEqual(assertion_causes(value)["reasonCode"], "unsupported_version")
        empty = assertion_cause_summary([])
        self.assertEqual((empty["plannedSamples"], empty["availableSamples"], empty["missingSamples"]), (0, 0, 0))
        self.assertEqual(empty["byRole"]["required"]["declaredSamples"], 0)

    def test_malformed_unavailable_reason_and_non_object_samples_degrade_without_crashing(self):
        rows = [None, []]
        for reason in ([], {}, True, None, "future_reason"):
            rows.append({"sampleId": "bad", "assertionCauses": {"assertionCausesFormatVersion": 1,
                         "status": "unavailable", "reasonCode": reason}})
        summary = assertion_cause_summary(rows)
        self.assertEqual((summary["plannedSamples"], summary["availableSamples"], summary["missingSamples"]), (7, 0, 7))
        self.assertEqual(summary["missingReasons"], {"invalid_metadata": 7})


if __name__ == "__main__":
    unittest.main()
