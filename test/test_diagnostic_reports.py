import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from dsh_eval.diagnostics import diagnostic_sample, diagnostic_summary
from dsh_eval.experiment import run_experiment
from dsh_eval.experiment_resume import plan_experiment_resume, resume_experiment
from dsh_eval.formats import load_json
from dsh_eval.report import generate_report
import test_stateful_mutations as fixtures


class DiagnosticSummaryTests(unittest.TestCase):
    def test_counts_diagnostic_outcomes_and_distinguishes_missing_from_zero(self):
        evaluation = {"assertions": {"results": [
            {"id": "required", "outcome": "failed"},
            {"id": "format", "role": "diagnostic", "outcome": "failed"},
            {"id": "read", "role": "diagnostic", "outcome": "insufficient_evidence"},
            {"id": "end", "role": "diagnostic", "outcome": "not_run"},
            {"id": "ok", "role": "diagnostic", "outcome": "passed"},
        ]}}
        value = diagnostic_sample(evaluation)
        self.assertEqual(value["declaredAssertions"], 4)
        self.assertEqual(value["outcomes"], {"passed": 1, "failed": 1, "insufficient_evidence": 1, "not_run": 1})
        self.assertEqual(value["failedAssertionIds"], ["format"])
        self.assertEqual(value["insufficientAssertionIds"], ["read"])
        self.assertEqual(value["notRunAssertionIds"], ["end"])
        legacy = diagnostic_sample({"assertions": {"results": [{"id": "old", "outcome": "passed"}]}})
        rows = [{"outcome": "passed", "diagnosticSummary": value},
                {"outcome": "failed", "diagnosticSummary": copy.deepcopy(value)},
                {"outcome": "passed", "diagnosticSummary": legacy},
                {"outcome": None, "diagnosticSummary": None}, {"outcome": None}]
        self.assertEqual(diagnostic_summary(rows),
                         {"observedSamples": 3, "missingSamples": 2, "samplesWithDiagnostics": 2,
                          "samplesWithFailures": 2, "passedSamplesWithFailures": 1,
                          "assertionCounts": {"passed": 2, "failed": 2, "insufficient_evidence": 2, "not_run": 2}})


class DiagnosticReportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MutationIntegrationTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.path, self.case = self.fixture.prepare("rename-no-overwrite")
        answer = next(row for row in self.case["assertions"] if row["id"] == "answer")
        answer.update(equals="Done.", role="diagnostic")
        self.fixture.save(self.path, self.case)
        manifest = {"experimentFormatVersion": 1, "experimentName": "diagnostic-report", "repetitions": 2,
                    "failurePolicy": "continue", "cases": [{"entryId": "rename", "casePath": self.path.name}],
                    "configurations": [{"configurationId": "synthetic", "configRef": self.case["configRef"]}]}
        self.manifest = self.fixture.root / "experiment.json"
        self.fixture.save(self.manifest, manifest)

    def run_experiment(self, **options):
        with patch("dsh_eval.batch.run_case", side_effect=self.fixture.execute):
            result = run_experiment(self.manifest, self.fixture.root / "experiments", **options)
        return Path(result["experimentDirectory"]) / "experiment-result.json"

    def assert_two_diagnostic_failures(self, report):
        self.assertEqual(report["summary"]["outcomes"]["passed"], 2)
        expected = {"observedSamples": 2, "missingSamples": 0, "samplesWithDiagnostics": 2,
                    "samplesWithFailures": 2, "passedSamplesWithFailures": 2,
                    "assertionCounts": {"passed": 0, "failed": 2, "insufficient_evidence": 0, "not_run": 0}}
        self.assertEqual(report["summary"]["diagnosticSummary"], expected)
        self.assertEqual(report["groups"][0]["summary"]["diagnosticSummary"], expected)
        for row in report["samples"]:
            self.assertEqual(row["diagnosticSummary"]["failedAssertionIds"], ["answer"])
            evaluation = load_json(Path(report["reportDirectory"]) / row["evaluationPath"])
            self.assertEqual(evaluation["outcome"], "passed")
            answer = next(item for item in evaluation["assertions"]["results"] if item["id"] == "answer")
            self.assertEqual((answer["outcome"], answer["actual"], answer["role"]), ("failed", "done", "diagnostic"))
        markdown = (Path(report["reportDirectory"]) / "report.md").read_text(encoding="utf-8")
        self.assertIn("诊断项覆盖与结果", markdown)
        self.assertIn("任务通过且存在诊断失败的样本 2", markdown)
        self.assertIn("answer", markdown)

    def test_normal_experiment_reports_keep_diagnostic_failures_separate(self):
        source = self.run_experiment()
        before = {path: path.read_bytes() for path in source.parent.rglob("*") if path.is_file()}
        report = generate_report(source, self.fixture.root / "reports")
        self.assertEqual(report["comparisonReportFormatVersion"], 1)
        self.assert_two_diagnostic_failures(report)
        self.assertTrue(all(path.read_bytes() == value for path, value in before.items()))
        evidence = source.parent / load_json(source)["samples"][1]["evidencePath"]
        evidence.unlink()
        incomplete = generate_report(source, self.fixture.root / "reports")
        stats = incomplete["summary"]["diagnosticSummary"]
        self.assertEqual((stats["observedSamples"], stats["missingSamples"], stats["passedSamplesWithFailures"]), (1, 1, 1))
        self.assertIsNone(incomplete["samples"][1]["diagnosticSummary"])

    def test_continuation_report_partitions_old_and_new_diagnostic_counts(self):
        source = self.run_experiment(stop_after=1)
        plan = plan_experiment_resume(source)
        self.assertTrue(plan["eligibleForResume"])
        with patch("dsh_eval.batch.run_case", side_effect=self.fixture.execute):
            result = resume_experiment(source, self.fixture.root / "resumes",
                                       expected_plan_sha256=plan["planFingerprint"]["sha256"])
        report = generate_report(Path(result["resumeDirectory"]) / "experiment-resume-result.json",
                                 self.fixture.root / "reports")
        self.assertEqual(report["comparisonReportFormatVersion"], 2)
        self.assert_two_diagnostic_failures(report)
        for key in ("reusedSummary", "newlyExecutedSummary"):
            self.assertEqual(report[key]["diagnosticSummary"]["passedSamplesWithFailures"], 1)
            self.assertEqual(report[key]["diagnosticSummary"]["assertionCounts"]["failed"], 1)
        self.assertEqual([row["executionOrigin"] for row in report["samples"]], ["reused", "new"])
