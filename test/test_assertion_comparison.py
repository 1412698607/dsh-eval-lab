"""Compare scoring rules against one archived synthetic runner task."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dsh_eval.__main__ import main
from dsh_eval.assertion_comparison import compare_assertions
from dsh_eval.evaluate import evaluate
from dsh_eval.formats import load_json
from dsh_eval.runner import ROOT, run_case


class AssertionComparisonTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dsh-compare-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.candidate = self.root / "candidate.json"
        self.case = load_json(ROOT / "fixtures/evaluation/rename-no-overwrite.case.json")
        self.case["configRef"].update(provider="synthetic", model="none")
        answer = next(row for row in self.case["assertions"] if row["id"] == "answer")
        answer["equals"] = "Done"  # The scripted adapter returns lowercase "done".
        self.save(self.candidate, self.case)
        with patch("dsh_eval.runner._prepare"), patch("dsh_eval.output_paths.check_output_root"), \
                patch("dsh_eval.runner.ADAPTER", ROOT / "scripts/fixtures/mutation-adapter.js"):
            result = run_case(self.candidate, self.root / "runs")
        self.evidence = Path(result["association"]["evidencePath"])
        self.archive = self.evidence.parent
        self.trace = next(Path(result["association"]["runDir"]).glob("*.jsonl"))
        evidence = load_json(self.evidence)
        self.save(self.evidence, {**evidence, "source": "synthetic"})
        self.original = evaluate(self.archive / "case.json", self.evidence)
        self.assertEqual(self.original["outcome"], "failed")
        self.save(self.archive / "evaluation.json", self.original)

    @staticmethod
    def save(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def archive_hashes(self):
        return {p.relative_to(self.archive): hashlib.sha256(p.read_bytes()).digest()
                for p in self.archive.rglob("*") if p.is_file()}

    def test_role_and_match_distinguish_aggregate_change_from_answer_change(self):
        before = self.archive_hashes()
        for field, value, answer_verdict in (("role", "diagnostic", "failed"), ("match", "confirmation_token", "passed")):
            with self.subTest(field=field):
                candidate = deepcopy(self.case)
                next(row for row in candidate["assertions"] if row["id"] == "answer")[field] = value
                self.save(self.candidate, candidate)
                report = compare_assertions(self.evidence, self.candidate)
                self.assertEqual((report["assertionComparisonFormatVersion"], report["status"], report["exitCode"]),
                                 (1, "compared", 0))
                self.assertEqual(report["caseRunId"], self.original["caseRunId"])
                self.assertEqual(report["runId"], self.original["association"]["runId"])
                self.assertEqual(report["source"], "synthetic")
                self.assertEqual((report["baseline"]["outcome"], report["candidate"]["outcome"]), ("failed", "passed"))
                self.assertEqual(report["summary"], {"taskOutcomeChanged": True, "changedAssertionIds": ["answer"]})
                for key in ("caseSha256", "assertionsSha256"):
                    self.assertNotEqual(report["baseline"][key], report["candidate"][key])
                changed = [row for row in report["assertions"] if row["ruleChanged"]]
                self.assertEqual([row["id"] for row in changed], ["answer"])
                answer = changed[0]
                self.assertFalse(answer["positionChanged"])
                self.assertTrue(answer["resultChanged"])
                self.assertEqual(answer["outcomeChanged"], answer_verdict == "passed")
                self.assertEqual(answer["candidate"]["definition"][field], value)
                old, new = (answer[side]["result"] for side in ("baseline", "candidate"))
                self.assertEqual((old["outcome"], new["outcome"]), ("failed", answer_verdict))
                self.assertEqual(old["actual"], new["actual"])
                self.assertEqual(old["evidence"], new["evidence"])
        self.assertEqual(self.archive_hashes(), before)

    def test_unchanged_successor_rule_and_verdict_still_report_different_evidence(self):
        candidate = deepcopy(self.case)
        occupied, move = candidate["assertions"][:2]
        # Let "move" select the first (rejected) rename instead of the second.
        candidate["assertions"][1] = {**occupied, "id": move["id"]}
        self.save(self.candidate, candidate)
        report = compare_assertions(self.evidence, self.candidate)
        self.assertEqual(report["summary"], {"taskOutcomeChanged": False, "changedAssertionIds": ["move", "verify"]})
        verify = next(row for row in report["assertions"] if row["id"] == "verify")
        self.assertTrue(verify["resultChanged"])
        self.assertFalse(verify["ruleChanged"] or verify["outcomeChanged"] or verify["positionChanged"])
        old, new = (verify[side]["result"] for side in ("baseline", "candidate"))
        self.assertEqual((old["outcome"], new["outcome"]), ("passed", "passed"))
        self.assertEqual(old["evidence"]["resultSeq"], new["evidence"]["resultSeq"])
        self.assertLess(new["evidence"]["afterResultSeq"], old["evidence"]["afterResultSeq"])

    def test_diff_by_id_includes_position_addition_removal_and_changed_type(self):
        candidate = deepcopy(self.case)
        old_rows = {row["id"]: row for row in self.case["assertions"]}
        candidate["assertions"] = [old_rows["end"], {"id": "answer", "type": "turn_end", "reason": {"kind": "completed"}},
                                   {"id": "extra", "type": "tool_forbidden", "tool": "eval_delete"}]
        self.save(self.candidate, candidate)
        report = compare_assertions(self.evidence, self.candidate)
        rows = {row["id"]: row for row in report["assertions"]}
        self.assertEqual(list(rows), [*old_rows, "extra"])
        self.assertIsNone(rows["extra"]["baseline"])
        self.assertEqual(rows["extra"]["candidate"]["position"], 3)
        self.assertIsNone(rows["occupied"]["candidate"])
        self.assertEqual(rows["occupied"]["baseline"]["position"], 1)
        self.assertTrue(rows["end"]["positionChanged"])
        self.assertEqual(rows["end"]["candidate"]["position"], 1)
        self.assertFalse(rows["end"]["ruleChanged"])
        self.assertFalse(rows["end"]["outcomeChanged"])
        self.assertEqual(rows["answer"]["candidate"]["definition"]["type"], "turn_end")
        self.assertTrue(rows["answer"]["ruleChanged"])

    def test_non_assertion_changes_and_broken_evidence_rejected(self):
        for change in ({"input": "different task"}, {"caseId": "another"},
                       {"environment": {**self.case["environment"], "files": {}}},
                       {"budget": {"timeoutSeconds": 1}}, {"configRef": {**self.case["configRef"], "model": "another"}}):
            with self.subTest(field=next(iter(change))):
                self.save(self.candidate, {**self.case, **change})
                with self.assertRaises(ValueError):
                    compare_assertions(self.evidence, self.candidate)
        self.save(self.candidate, self.case)
        self.evidence.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            compare_assertions(self.evidence, self.candidate)

    def test_without_trace_both_verdicts_are_inconclusive(self):
        self.trace.unlink()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--compare-assertions", str(self.evidence), "--candidate", str(self.candidate)]), 2)
        report = json.loads(output.getvalue())
        self.assertEqual((report["status"], report["exitCode"]), ("inconclusive", 2))
        for side in ("baseline", "candidate"):
            self.assertEqual(report[side]["outcome"], "unevaluable")
            self.assertEqual(report[side]["assertionOutcome"], "not_run")
            self.assertTrue(all(row[side]["result"]["outcome"] == "not_run" for row in report["assertions"]))

    def test_rejects_archive_drift_between_evaluations(self):
        def evaluate_then_change_trace(case_path, evidence_path):
            result = evaluate(case_path, evidence_path)
            with self.trace.open("ab") as stream:
                stream.write(b"\n")
            return result

        with patch("dsh_eval.assertion_comparison.evaluate", side_effect=evaluate_then_change_trace):
            with self.assertRaisesRegex(ValueError, "changed"):
                compare_assertions(self.evidence, self.candidate)

    def test_cli_reports_unchanged_failure_and_prevents_archive_writes(self):
        args = ["--compare-assertions", str(self.evidence), "--candidate", str(self.candidate)]
        # Neither side may use the saved verdict as its baseline.
        self.save(self.archive / "evaluation.json", {**self.original, "outcome": "passed"})
        before = self.archive_hashes()
        path = self.root / "comparison.json"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([*args, "--output", str(path)]), 0)
        result = load_json(path)
        self.assertEqual(result["candidate"]["outcome"], "failed")
        self.assertEqual(result["summary"], {"taskOutcomeChanged": False, "changedAssertionIds": []})
        self.assertEqual(result["baseline"]["assertionsSha256"], result["candidate"]["assertionsSha256"])
        self.assertTrue(all(not row["ruleChanged"] and not row["outcomeChanged"] and not row["positionChanged"]
                            for row in result["assertions"]))
        for target in (self.archive / "new.json", self.archive / "evaluation.json", path, self.candidate):
            with self.subTest(target=target), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main([*args, "--output", str(target)]), 2)
        self.assertEqual(self.archive_hashes(), before)
        self.assertEqual(load_json(path), result)

    def test_cli_rejects_execution_and_unrelated_controls(self):
        args = ["--compare-assertions", str(self.evidence), "--candidate", str(self.candidate)]
        for option in (["--run"], ["--plan"], ["--baseline-config", "old"]):
            with self.subTest(option=option), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main([*args, *option])
            self.assertEqual(error.exception.code, 2)
