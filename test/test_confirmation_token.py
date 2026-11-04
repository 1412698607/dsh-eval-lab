import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from dsh_eval.evaluate import check_assertion, evaluate
from dsh_eval.formats import load_json, validate_case


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/evaluation/read-project.case.json"


class ConfirmationTokenTests(unittest.TestCase):
    def setUp(self):
        self.case = load_json(FIXTURE)
        self.case["caseFormatVersion"] = 2
        self.answer = self.case["assertions"][0]
        self.answer.update(equals="Done", match="confirmation_token")

    def score(self, actual):
        view = {"final": {"seq": 4, "data": {"message": {"content": [{"type": "text", "text": actual}]}}}}
        return check_assertion(self.answer, view)

    def test_accepts_only_declared_confirmations_and_preserves_actual(self):
        validate_case(self.case)
        for actual in ("done", "DONE.", "**Done**", "**dOne.**", "**DONE**.",
                       "__done__", "__DONE.__", "__Done__.", " \n**Done.**\t"):
            with self.subTest(actual=actual):
                self.assertEqual(self.score(actual),
                                 {"id": "answer", "type": "final_text", "match": "confirmation_token",
                                  "outcome": "passed", "actual": actual.strip(), "evidence": {"answerSeq": 4}})

    def test_negation_extra_content_markdown_and_duplicate_punctuation_fail(self):
        for actual in ("", "not done", "done later", "do ne", "**done**\nbut failed",
                       "done..", "__done.__.", "**done**!", "** done **", "*done*",
                       "**done__", "****done****", "`done`", "[done](url)", "# done",
                       "ＤＯＮＥ", "done。", "done\x00"):
            with self.subTest(actual=actual):
                self.assertEqual(self.score(actual)["outcome"], "failed")
        self.answer["equals"] = "ok"
        self.assertEqual(self.score("OK")["outcome"], "failed")
        self.assertEqual(self.score("**Ok.**")["outcome"], "passed")

    def test_legacy_exact_match_keeps_result_shape(self):
        del self.answer["match"]
        for version in (1, 2):
            self.case["caseFormatVersion"] = version
            validate_case(self.case)
            self.assertEqual(self.score("Done")["outcome"], "passed")
            self.assertEqual(self.score("**Done.**"),
                             {"id": "answer", "type": "final_text", "outcome": "failed",
                              "actual": "**Done.**", "evidence": {"answerSeq": 4}})

    def test_validation_rejects_unknown_match_and_invalid_expected_words(self):
        for expected in ("done.", " Done", "done\n", "done123", "ok!", "two words", "**done**", "完成"):
            self.answer["equals"] = expected
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, "ASCII word"):
                validate_case(self.case)
        self.answer["equals"] = "ok"
        for mode in ("exact", "", "CONFIRMATION_TOKEN", None, [], True):
            self.answer["match"] = mode
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "match"):
                validate_case(self.case)
        self.answer["match"] = "confirmation_token"
        self.case["caseFormatVersion"] = 1
        with self.assertRaisesRegex(ValueError, "Unknown fields"):
            validate_case(self.case)
        self.case["caseFormatVersion"] = 2
        self.case["assertions"][1]["match"] = "confirmation_token"
        with self.assertRaisesRegex(ValueError, "Unknown fields"):
            validate_case(self.case)

    def test_not_run_row_preserves_both_role_and_match(self):
        self.answer["role"] = "diagnostic"
        evidence = {"evidenceFormatVersion": 2, "caseRunId": str(uuid4()), "caseId": self.case["caseId"],
                    "runDir": None, "runId": None, "sessionId": None, "source": "synthetic",
                    "configuration": None, "execution": {"status": "runtime_error"},
                    "budgetEnforcement": {"timeoutSeconds": False}}
        with tempfile.TemporaryDirectory() as temp:
            case_path, evidence_path = Path(temp) / "case.json", Path(temp) / "evidence.json"
            case_path.write_text(json.dumps(self.case), encoding="utf-8")
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            result = evaluate(case_path, evidence_path)
        self.assertEqual(result["outcome"], "unevaluable")
        self.assertEqual(result["assertions"]["results"][0],
                         {"id": "answer", "type": "final_text", "role": "diagnostic",
                          "match": "confirmation_token", "outcome": "not_run"})
