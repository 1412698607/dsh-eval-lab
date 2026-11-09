"""Optional scoring diagnostics preserve legacy evidence, comparison and resume contracts."""
from copy import deepcopy
from pathlib import Path
import unittest

from dsh_eval.assertion_comparison import compare_assertions
from dsh_eval.evaluate import evaluate
from dsh_eval.experiment_assertion_preview import preview_experiment_assertions
from dsh_eval.experiment_resume import plan_experiment_resume, resume_experiment
from dsh_eval.formats import load_json
from dsh_eval.resume import CLAIM_NAME, plan_batch_resume
import test_experiment_resume as resume_fixture
from test_report import ReportFixture


class DiagnosticsResumeCompatibilityTests(unittest.TestCase):
    # Reuse the established real-process fixture without inheriting its test methods.
    save = resume_fixture.ExperimentResumeTests.save
    synthetic_case = resume_fixture.ExperimentResumeTests.synthetic_case
    crash = resume_fixture.ExperimentResumeTests.crash
    snapshot = resume_fixture.ExperimentResumeTests.snapshot

    def setUp(self):
        resume_fixture.ExperimentResumeTests.setUp(self)
        self.manifest["repetitions"] = 1  # Two completed samples and two still unstarted.
        self.save(self.path, self.manifest)
        self.crash()
        self.legacy = []
        batch = load_json(self.batch_source)
        for row in batch["entries"][:2]:
            path = self.batch_source.parent / row["evaluationPath"]
            previous = load_json(path)
            self.assertIn("assertionDiagnostics", previous)
            previous.pop("assertionDiagnostics")
            self.save(path, previous)
            self.legacy.append((path, previous))

    def test_legacy_saved_evaluations_are_reused_and_only_pending_samples_execute(self):
        before = self.snapshot()
        for path, previous in self.legacy:
            fresh = evaluate(path.with_name("case.json"), path.with_name("evidence.json"))
            self.assertEqual(fresh["assertionDiagnostics"]["assertionDiagnosticsFormatVersion"], 1)
            self.assertEqual(fresh["assertions"], previous["assertions"])
            self.assertEqual(fresh["outcome"], previous["outcome"])
            self.assertEqual([row["id"] for row in fresh["assertionDiagnostics"]["results"]],
                             [row["id"] for row in previous["assertions"]["results"]])
        batch_plan = plan_batch_resume(self.batch_source, max_samples=2)
        plan = plan_experiment_resume(self.source, max_samples=2)
        self.assertTrue(batch_plan["canResume"])
        self.assertTrue(plan["eligibleForResume"])
        self.assertEqual(plan["counts"], {"original": 4, "reused": 2, "newSamples": 2, "blocked": 0})
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.called, [])
        original_ids = {row["caseRunId"] for row in plan["samples"] if row["disposition"] == "reuse"}
        continued = resume_experiment(self.source, self.directory / "resumes", max_samples=2,
                                      expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertEqual((continued["status"], continued["outcome"]), ("completed", "passed"))
        self.assertEqual(continued["samplePlan"], plan["samples"])
        self.assertEqual(len(self.called), 2)
        self.assertTrue(original_ids.isdisjoint(self.called))
        after = self.snapshot()
        self.assertTrue(all(after[name] == digest for name, digest in before.items()))
        self.assertEqual(set(after) - set(before),
                         {(self.batch_source.parent / CLAIM_NAME).relative_to(self.source.parent).as_posix()})
        for path, previous in self.legacy:
            self.assertEqual(load_json(path), previous)
            self.assertNotIn("assertionDiagnostics", load_json(path))

    def test_missing_optional_metadata_does_not_relax_core_assertion_equality(self):
        original_plan = plan_experiment_resume(self.source, max_samples=2)
        self.assertTrue(original_plan["eligibleForResume"])
        path, previous = self.legacy[0]
        altered = deepcopy(previous)
        altered["assertions"]["results"][0]["outcome"] = "failed"
        self.save(path, altered)
        batch_plan = plan_batch_resume(self.batch_source)
        plan = plan_experiment_resume(self.source)
        self.assertFalse(batch_plan["canResume"])
        self.assertFalse(plan["eligibleForResume"])
        self.assertTrue(any("assertions" in row["reason"] for row in batch_plan["blockedEntries"]))
        with self.assertRaisesRegex(ValueError, "cannot resume"):
            resume_experiment(self.source, self.directory / "rejected", max_samples=2,
                              expected_plan_sha256=original_plan["planFingerprint"]["sha256"])
        self.assertFalse((self.directory / "rejected").exists())
        self.assertFalse((self.batch_source.parent / CLAIM_NAME).exists())
        self.assertEqual(self.called, [])
        self.save(path, previous)
        self.assertTrue(plan_experiment_resume(self.source, max_samples=2)["eligibleForResume"])


class DiagnosticsReportCompatibilityTests(ReportFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.case["environment"]["files"]["project.md"] = "projectName: done\n"
        self.case["assertions"][1]["result"]["textContains"] = "done"
        next(row for row in self.case["assertions"] if row["id"] == "answer").update(
            equals="done", match="confirmation_token")
        self.save(self.directory / "case.json", self.case)
        self.manifest["configurations"] = self.manifest["configurations"][:1]
        self.experiment()

        def decorate(events):
            final = next(row for row in events if row["type"] == "assistant/message")
            final["data"]["message"]["content"][0]["text"] = "**done**"

        self.rerecord(0, decorate)
        self.legacy = []
        for sample in self.saved["samples"]:
            path = self.base / sample["evaluationPath"]
            fresh = evaluate(path.with_name("case.json"), path.with_name("evidence.json"))
            self.assertEqual(fresh["assertionDiagnostics"]["assertionDiagnosticsFormatVersion"], 1)
            fresh.pop("assertionDiagnostics")
            self.save(path, fresh)
            self.legacy.append((path, fresh))

    def test_report_and_both_rule_previews_preserve_legacy_results_and_sources(self):
        before = self.digest(self.base)
        report = self.report()
        self.assertEqual(report["verificationCounts"], {"verified": 2})
        self.assertTrue(all(row["changedFields"] == [] for row in report["samples"]))
        for row, (path, previous) in zip(report["samples"], self.legacy):
            fresh = load_json(Path(report["reportDirectory"]) / row["evaluationPath"])
            self.assertIn("assertionDiagnostics", fresh)
            self.assertEqual(fresh["assertions"], previous["assertions"])
            self.assertEqual(fresh["outcome"], "passed")

        sample = self.saved["samples"][0]
        candidate = load_json(self.base / sample["caseDirectory"] / "case.json")
        next(row for row in candidate["assertions"] if row["id"] == "answer").pop("match")
        candidate_path = self.directory / "candidate.json"
        self.save(candidate_path, candidate)
        comparison = compare_assertions(self.base / sample["evidencePath"], candidate_path)
        self.assertEqual((comparison["baseline"]["outcome"], comparison["candidate"]["outcome"]), ("passed", "failed"))
        self.assertEqual(comparison["summary"], {"taskOutcomeChanged": True, "changedAssertionIds": ["answer"]})
        self.assertEqual([item["baseline"]["result"] for item in comparison["assertions"]], self.legacy[0][1]["assertions"]["results"])
        # Diagnostic-only metadata must not make every unchanged assertion appear changed.
        self.assertTrue(all(not item["resultChanged"] for item in comparison["assertions"] if item["id"] != "answer"))

        rule_map_path = self.directory / "rule-map.json"
        self.save(rule_map_path, {"assertionRuleMapFormatVersion": 1, "cases": {"retry": candidate["assertions"]}})
        preview = preview_experiment_assertions(self.path, rule_map_path)
        self.assertEqual(preview["summary"], {"plannedSamples": 2, "comparedSamples": 2, "passToFail": 1,
                                              "failToPass": 0, "unchangedPassed": 1, "unchangedFailed": 0, "inconclusive": 0})
        self.assertTrue(all(row["changedAssertionIds"] == ["answer"] for row in preview["samples"]))
        self.assertEqual(self.digest(self.base), before)
        for path, previous in self.legacy:
            self.assertEqual(load_json(path), previous)
            self.assertNotIn("assertionDiagnostics", load_json(path))


if __name__ == "__main__":
    unittest.main()
