import copy
from pathlib import Path
import unittest

from dsh_eval.formats import load_json, validate_case, validate_evidence


ROOT = Path(__file__).resolve().parents[1]


class ToolBudgetFormatTests(unittest.TestCase):
    def case(self):
        return load_json(ROOT / "fixtures/evaluation/retry-read.case.json")

    def evidence(self):
        return {"evidenceFormatVersion": 2, "caseRunId": "889b18ad-08e8-4ba7-a290-b76a047cd4fe",
                "caseId": self.case()["caseId"], "runId": None, "sessionId": None, "runDir": None,
                "source": "synthetic", "configuration": None, "budgetEnforcement": {"timeoutSeconds": False},
                "execution": {"status": "runtime_error"}, "runtimeReport": "runtime.json"}

    def test_nonnegative_safe_integer_limits_are_preserved(self):
        for limit in (0, 1, 9007199254740991):
            with self.subTest(limit=limit):
                case = self.case()
                case["budget"]["maxToolCalls"] = limit
                before = copy.deepcopy(case)
                self.assertEqual(validate_case(case), before)

    def test_invalid_limits_are_rejected(self):
        for limit in (None, True, False, -1, 1.0, 1.5, "1", {}, [], 9007199254740992):
            with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, "nonnegative safe integer"):
                case = self.case()
                case["budget"]["maxToolCalls"] = limit
                validate_case(case)

    def test_limit_requires_version_two_and_controlled_environment(self):
        for version, stateful in ((1, False), (1, True), (2, False)):
            with self.subTest(version=version, stateful=stateful), self.assertRaises(ValueError):
                case = self.case()
                case["caseFormatVersion"] = version
                case["budget"]["maxToolCalls"] = 1
                if not stateful:
                    case["environment"].pop("stateful")
                validate_case(case)

    def test_omitted_case_and_evidence_fields_are_not_backfilled(self):
        case = self.case()
        evidence = self.evidence()
        original = copy.deepcopy((case, evidence))
        validate_case(case)
        validate_evidence(evidence, case)
        self.assertEqual((case, evidence), original)
        self.assertNotIn("maxToolCalls", case["budget"])
        self.assertNotIn("maxToolCalls", evidence["budgetEnforcement"])

    def test_budget_enforcement_accepts_only_boolean(self):
        for enabled in (False, True):
            evidence = self.evidence()
            evidence["budgetEnforcement"]["maxToolCalls"] = enabled
            self.assertIs(validate_evidence(evidence, self.case()), evidence)
        for enabled in (None, 0, 1, "true", {}, []):
            with self.subTest(enabled=enabled), self.assertRaisesRegex(ValueError, "must be boolean"):
                evidence = self.evidence()
                evidence["budgetEnforcement"]["maxToolCalls"] = enabled
                validate_evidence(evidence, self.case())

    def test_budget_exceeded_execution_is_recognized_and_unknown_fields_stay_strict(self):
        evidence = self.evidence()
        evidence["execution"] = {"status": "budget_exceeded", "reason": "tool_budget"}
        self.assertIs(validate_evidence(evidence, self.case()), evidence)
        for section in ("budgetEnforcement", "execution"):
            invalid = copy.deepcopy(evidence)
            invalid[section]["unknown"] = True
            with self.subTest(section=section), self.assertRaisesRegex(ValueError, "Unknown fields"):
                validate_evidence(invalid, self.case())
        case = self.case()
        case["budget"].update(maxToolCalls=1, maxTools=1)
        with self.assertRaisesRegex(ValueError, "Unknown fields"):
            validate_case(case)


if __name__ == "__main__":
    unittest.main()
