"""Impact of candidate assertion rules across a frozen synthetic experiment."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import unittest
from unittest.mock import patch

from dsh_eval import experiment_assertion_preview
from dsh_eval.__main__ import main
from dsh_eval.experiment_assertion_preview import preview_experiment_assertions
from dsh_eval.formats import load_json
from test_report import ReportFixture


class ExperimentAssertionPreviewTests(ReportFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.case["environment"]["files"]["project.md"] = "projectName: done\n"
        self.case["assertions"][1]["result"]["textContains"] = "done"
        self.answer = next(row for row in self.case["assertions"] if row["id"] == "answer")
        self.answer.update(equals="done", match="confirmation_token")
        self.save(self.directory / "case.json", self.case)
        self.manifest["configurations"] = self.manifest["configurations"][:1]
        self.manifest["repetitions"] = 1
        self.rule_map = self.directory / "rule-map.json"

    def rules(self, mapping):
        self.save(self.rule_map, {"assertionRuleMapFormatVersion": 1, "cases": mapping})

    def preview(self):
        return preview_experiment_assertions(self.path, self.rule_map)

    def cli(self, *options):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--compare-experiment-assertions", str(self.path), "--candidate", str(self.rule_map), *options])
        return code, json.loads(output.getvalue())

    def test_strict_candidate_flips_only_one_repetition_and_configuration(self):
        self.manifest["repetitions"] = 2
        first = self.manifest["configurations"][0]
        self.manifest["configurations"].append({"configurationId": "second",
                                                "configRef": {**first["configRef"], "model": "second"}})
        self.manifest["cases"].append({"entryId": "other", "casePath": "other.json"})
        self.save(self.directory / "other.json", {**self.case, "caseId": "second-case"})
        self.experiment()
        target = next(i for i, sample in enumerate(self.saved["samples"])
                      if (sample["caseEntryId"], sample["configurationId"], sample["repeatIndex"]) == ("other", "second", 1))

        def decorate(events):
            final = next(event for event in events if event["type"] == "assistant/message")
            final["data"]["message"]["content"][0]["text"] = "**done**"

        self.rerecord(target, decorate)
        strict = deepcopy(self.case["assertions"])
        answer = next(row for row in strict if row["id"] == "answer")
        del answer["match"]
        self.rules({"other": strict, "retry": strict})
        before = self.digest(self.base)
        code, report = self.cli()
        self.assertEqual((code, report["exitCode"], report["status"], report["modelCalled"]), (0, 0, "compared", False))
        summary = report["summary"]
        self.assertEqual((summary["plannedSamples"], summary["comparedSamples"], summary["passToFail"],
                          summary["unchangedPassed"], summary["failToPass"], summary["inconclusive"]), (8, 8, 1, 7, 0, 0))
        self.assertEqual([row["sampleId"] for row in report["samples"]], [row["sampleId"] for row in self.saved["samples"]])
        flips = [row for row in report["samples"] if row["transition"] == "passToFail"]
        self.assertEqual(len(flips), 1)
        sample = flips[0]
        self.assertEqual((sample["caseEntryId"], sample["configurationId"], sample["repeatIndex"],
                          sample["baselineOutcome"], sample["candidateOutcome"]), ("other", "second", 1, "passed", "failed"))
        self.assertEqual(sample["changedAssertionIds"], ["answer"])
        change, = sample["changes"]
        self.assertTrue(change["ruleChanged"] and change["outcomeChanged"])
        baseline, candidate = (change[key]["result"] for key in ("baseline", "candidate"))
        self.assertEqual((baseline["actual"], candidate["actual"], candidate["outcome"]), ("**done**", "**done**", "failed"))
        self.assertEqual(baseline["evidence"], candidate["evidence"])
        self.assertEqual(self.digest(self.base), before)

    def test_no_rule_change_and_added_removed_reordered_diagnostics(self):
        self.experiment()
        self.rules({"retry": self.case["assertions"]})
        sample, = self.preview()["samples"]
        self.assertEqual((sample["changedAssertionIds"], sample["changes"]), ([], []))
        _, tool1, answer, end = deepcopy(self.case["assertions"])
        new = {**answer, "id": "format", "role": "diagnostic", "equals": "wrong"}
        self.rules({"retry": [end, tool1, {**answer, "role": "diagnostic"}, new]})
        sample, = self.preview()["samples"]
        self.assertEqual((sample["transition"], sample["candidateOutcome"]), ("unchangedPassed", "passed"))
        changes = {row["id"]: row for row in sample["changes"]}
        self.assertIsNone(changes["tool-0"]["candidate"])
        self.assertIsNone(changes["format"]["baseline"])
        self.assertTrue(changes["completed"]["positionChanged"])
        self.assertTrue(changes["answer"]["ruleChanged"])
        self.assertFalse(changes["answer"]["outcomeChanged"])

    def test_inconclusive_evidence_keeps_denominator_and_comparable_failures(self):
        self.manifest["repetitions"] = 2
        self.experiment()
        rules = deepcopy(self.case["assertions"])
        next(row for row in rules if row["id"] == "answer").update(equals="wrong")
        self.rules({"retry": rules})
        original = self.base / self.saved["samples"][0]["evidencePath"]
        evidence = load_json(original)
        for corrupted in (False, True):
            with self.subTest(corrupted=corrupted):
                if corrupted:
                    self.save(original, {**evidence, "sessionId": "foreign-session"})
                else:
                    original.unlink()
                code, report = self.cli()
                self.assertEqual((code, report["exitCode"], report["status"]), (2, 2, "inconclusive"))
                self.assertEqual([report["summary"][k] for k in
                                  ("plannedSamples", "comparedSamples", "inconclusive", "passToFail")], [2, 1, 1, 1])
                self.assertEqual([r["transition"] for r in report["samples"]], ["inconclusive", "passToFail"])
                self.assertTrue(report["samples"][0]["reasons"])

    def test_rechecks_baseline_failures_instead_of_using_saved_success(self):
        self.manifest["repetitions"] = 2
        self.answer["equals"] = "wrong"
        self.save(self.directory / "case.json", self.case)
        self.experiment()

        def different_word(events):
            next(e for e in events if e["type"] == "assistant/message")["data"]["message"]["content"][0]["text"] = "other"

        self.rerecord(1, different_word)
        for sample in self.saved["samples"]:
            sample["outcome"] = "passed"
        self.persist()
        self.rules({"retry": [{**a, "equals": "done"} if a["id"] == "answer" else a for a in self.case["assertions"]]})
        report = self.preview()
        self.assertEqual((report["exitCode"], report["summary"]["failToPass"], report["summary"]["unchangedFailed"]), (0, 1, 1))
        self.assertEqual([s["baselineOutcome"] for s in report["samples"]], ["failed", "failed"])

    def test_evidence_directory_is_inconclusive_without_hiding_another_flip(self):
        self.manifest["repetitions"] = 2
        self.experiment()
        self.rules({"retry": [{**a, "equals": "wrong"} if a["id"] == "answer" else a for a in self.case["assertions"]]})
        damaged = self.base / self.saved["samples"][0]["evidencePath"]
        damaged.unlink()
        damaged.mkdir()
        before = self.digest(self.base)
        code, report = self.cli()
        self.assertEqual((code, report["exitCode"], report["status"]), (2, 2, "inconclusive"))
        self.assertEqual([report["summary"][k] for k in ("plannedSamples", "comparedSamples", "inconclusive", "passToFail")],
                         [2, 1, 1, 1])
        self.assertEqual([s["transition"] for s in report["samples"]], ["inconclusive", "passToFail"])
        self.assertTrue(report["samples"][0]["reasons"])
        self.assertEqual(self.digest(self.base), before)

    def test_escaping_sample_path_is_an_input_error(self):
        self.experiment()
        self.rules({"retry": self.case["assertions"]})
        self.saved["samples"][0]["evidencePath"] = "../outside/evidence.json"
        self.persist()
        path = self.directory / "preview.json"
        code, error = self.cli("--output", str(path))
        self.assertEqual((code, error["status"]), (2, "error"))
        self.assertFalse(path.exists())

    def test_map_requires_exact_case_entries_and_valid_assertions(self):
        self.experiment()
        for candidate in (
            {"assertionRuleMapFormatVersion": True, "cases": {"retry": self.case["assertions"]}},
            {"assertionRuleMapFormatVersion": 1, "cases": {}},
            {"assertionRuleMapFormatVersion": 1, "cases": {"retry": self.case["assertions"], "other": []}},
            {"assertionRuleMapFormatVersion": 1, "cases": {"retry": []}},
            {"assertionRuleMapFormatVersion": 1, "cases": {"retry": [{**self.answer, "role": "diagnostic"}]}},
        ):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                self.save(self.rule_map, candidate)
                self.preview()

    def test_rejects_incomplete_or_unverifiable_source_plan(self):
        self.experiment()
        self.rules({"retry": self.case["assertions"]})
        for patch in ({"status": "running"}, {"planFingerprint": {"version": 1, "sha256": "0" * 64}}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.save(self.path, {**self.saved, **patch})
                self.preview()
        self.save(self.path, {k: v for k, v in self.saved.items() if k != "planInputPath"})
        with self.assertRaises(ValueError):
            self.preview()
        self.save(self.path, self.saved)
        frozen = self.base / self.saved["manifestPath"]
        frozen_case = self.base / load_json(frozen)["cases"][0]["casePath"]
        self.save(frozen_case, {**load_json(frozen_case), "input": "Different frozen prompt"})
        with self.assertRaises(ValueError):
            self.preview()

    def test_earlier_sample_drift_during_later_sample_invalidates_preview(self):
        self.manifest["repetitions"] = 2
        self.experiment()
        self.rules({"retry": self.case["assertions"]})
        first_trace = next((self.base / self.saved["samples"][0]["runDir"]).glob("*.jsonl"))
        compare = experiment_assertion_preview._preview_sample

        def change_previous_trace(sample, *args):
            if sample["repeatIndex"] == 2:
                with first_trace.open("ab") as stream:
                    stream.write(b"\n")
            return compare(sample, *args)

        with patch.object(experiment_assertion_preview, "_preview_sample", side_effect=change_previous_trace):
            with self.assertRaisesRegex(ValueError, "source files changed"):
                self.preview()

    def test_cli_writes_exclusively_outside_source_and_rejects_execution_options(self):
        self.experiment()
        self.rules({"retry": self.case["assertions"]})
        before = self.digest(self.base)
        path = self.directory / "preview.json"
        code, result = self.cli("--output", str(path))
        self.assertEqual(code, 0)
        self.assertEqual(result, load_json(path))
        for target in (path, self.base / "new.json", self.path, self.rule_map):
            with self.subTest(target=target):
                self.assertEqual(self.cli("--output", str(target))[0], 2)
        self.assertEqual(self.digest(self.base), before)
        self.assertEqual(load_json(path), result)
        for extra in (["--run"], ["--plan"], ["--candidate-config", "first"]):
            with self.subTest(extra=extra), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.cli(*extra)
