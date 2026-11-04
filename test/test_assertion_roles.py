import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from dsh_eval.evaluate import assertion_outcome, evaluate
from dsh_eval.formats import load_json, validate_case


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "evaluation"


def sample_case():
    case = load_json(FIXTURES / "read-project.case.json")
    case["caseFormatVersion"] = 2
    return case


class AssertionRoleTests(unittest.TestCase):
    def test_all_assertion_types_support_explicit_roles_without_changing_input(self):
        case = sample_case()
        case["environment"]["stateful"] = {"transientReadFailures": {}}
        case["assertions"].extend([
            {"id": "files", "type": "environment_files", "equals": {}},
            {"id": "guard", "type": "tool_forbidden", "tool": "write"},
            {"id": "count", "type": "tool_call_count", "tool": "read", "min": 1},
        ])
        for row in case["assertions"]:
            row["role"] = "diagnostic"
        with self.assertRaisesRegex(ValueError, "required role"):
            validate_case(case)
        case["assertions"][-1]["role"] = "required"
        original = copy.deepcopy(case)
        self.assertEqual(validate_case(case), original)

    def test_role_rejects_misspellings_and_cannot_be_used_in_version_one(self):
        case = sample_case()
        for role in ("optional", "REQUIRED", None, False, [], {}):
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, "role"):
                case["assertions"][0]["role"] = role
                validate_case(case)
        case["caseFormatVersion"] = 1
        for role in ("required", "diagnostic"):
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, "Unknown fields"):
                case["assertions"][0]["role"] = role
                validate_case(case)

    def test_required_order_dependency_must_have_required_predecessor(self):
        case = sample_case()
        first = case["assertions"][1]
        second = dict(first, id="second", after=first["id"], role="diagnostic")
        case["assertions"].append(second)
        validate_case(case)
        first["role"] = "diagnostic"
        validate_case(case)
        del second["role"]
        with self.assertRaisesRegex(ValueError, "cannot depend on a diagnostic"):
            validate_case(case)
        second["role"] = "required"
        with self.assertRaisesRegex(ValueError, "cannot depend on a diagnostic"):
            validate_case(case)

    def test_only_required_outcomes_determine_score(self):
        for required in ("passed", "failed", "insufficient_evidence"):
            for diagnostic in ("passed", "failed", "insufficient_evidence"):
                with self.subTest(required=required, diagnostic=diagnostic):
                    rows = [{"outcome": required}, {"outcome": diagnostic, "role": "diagnostic"}]
                    self.assertEqual(assertion_outcome(rows), required)
        self.assertEqual(assertion_outcome([{"outcome": "failed"}, {"outcome": "insufficient_evidence"}]),
                         "insufficient_evidence")

    def test_offline_scoring_role_metadata_and_evidence_gates(self):
        case = sample_case()
        case["assertions"][0]["equals"] = "wrong"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            case_path = root / "case.json"
            case_path.write_text(json.dumps(case), encoding="utf-8")
            script = """
                import { readFileSync } from 'node:fs';
                import { recordExample } from './scripts/demo-eval.js';
                const [casePath, eventsPath, output] = process.argv.slice(1);
                const events = JSON.parse(readFileSync(eventsPath, 'utf8'));
                console.log((await recordExample(casePath, events, output)).evidencePath);
            """
            proc = subprocess.run(["node", "--input-type=module", "-e", script, str(case_path),
                                   str(FIXTURES / "read-project.events.json"), str(root)],
                                  cwd=ROOT, check=True, capture_output=True, text=True)
            evidence_path = Path(proc.stdout.strip())
            baseline = evaluate(case_path, evidence_path)
            self.assertEqual(baseline["outcome"], "failed")
            self.assertTrue(all("role" not in row for row in baseline["assertions"]["results"]))

            case["assertions"][0]["role"] = "diagnostic"
            case["assertions"][1]["role"] = "required"
            case_path.write_text(json.dumps(case), encoding="utf-8")
            result = evaluate(case_path, evidence_path)
            self.assertEqual((result["outcome"], result["assertions"]["outcome"]), ("passed", "passed"))
            rows = result["assertions"]["results"]
            for index, role in enumerate(("diagnostic", "required")):
                self.assertEqual(rows[index], {**baseline["assertions"]["results"][index], "role": role})
            self.assertEqual(rows[2], baseline["assertions"]["results"][2])

            case["input"] = "unrelated task"
            case_path.write_text(json.dumps(case), encoding="utf-8")
            result = evaluate(case_path, evidence_path)
            self.assertEqual(result["outcome"], "unevaluable")
            self.assertEqual(result["assertions"]["outcome"], "insufficient_evidence")
            self.assertEqual(result["assertions"]["results"][0]["role"], "diagnostic")

            evidence = load_json(evidence_path)
            evidence["execution"] = {"status": "runtime_error"}
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            result = evaluate(case_path, evidence_path)
            self.assertEqual(result["outcome"], "unevaluable")
            self.assertEqual(result["assertions"]["results"][0],
                             {"id": "answer", "type": "final_text", "role": "diagnostic", "outcome": "not_run"})
