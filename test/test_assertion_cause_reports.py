"""Structured cause reports keep real synthetic archives, outcomes and source boundaries intact."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from urllib.parse import quote

from dsh_eval.browser import ArtifactBrowser
from dsh_eval.experiment import run_experiment
from dsh_eval.experiment_resume import plan_experiment_resume, resume_experiment
from dsh_eval.formats import load_json
from dsh_eval.report import generate_report
from dsh_eval.runner import ROOT, save_json
import test_experiment_resume as resume_fixtures


def digest(directory):
    return {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in directory.rglob("*") if path.is_file()}


class AssertionCauseReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="dsh-cause-reports-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.base = Path(cls.temporary.name)
        inputs = cls.base / "inputs"
        inputs.mkdir()
        config = {"provider": "synthetic", "model": "scripted", "profile": "headless", "pluginVersion": "0.1.2"}
        cases = []
        for entry, name in (("skipped-reads", "rename-timeout-retry"), ("format", "rename-confirmation")):
            case = load_json(ROOT / "fixtures/evaluation" / (name + ".case.json"))
            case["configRef"] = config.copy()
            if entry == "skipped-reads":
                case["caseId"] = "rename-timeout-skip-readbacks"
            filename = entry + ".case.json"
            save_json(inputs / filename, case)
            cases.append({"entryId": entry, "casePath": filename})
        manifest = inputs / "experiment.json"
        save_json(manifest, {"experimentFormatVersion": 1, "experimentName": "structured cause integration",
                            "repetitions": 1, "failurePolicy": "continue", "cases": cases,
                            "configurations": [{"configurationId": "scripted", "configRef": config}]})
        result = run_experiment(manifest, cls.base / "source", _synthetic_replies={
            "sample-000001": "done", "sample-000002": "**done**"})
        cls.source = Path(result["experimentDirectory"])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsh-cause-copy-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.archive = self.root / "archive"
        shutil.copytree(self.source, self.archive)
        self.path = self.archive / "experiment-result.json"
        self.saved = load_json(self.path)

    def report(self):
        before = digest(self.archive)
        report = generate_report(self.path, self.root / "reports")
        self.assertEqual(digest(self.archive), before)
        return report

    def test_legacy_archive_report_distinguishes_one_root_three_blockers_and_diagnostic_failure(self):
        # Old persisted evaluations remain valid inputs; only fresh report copies acquire new metadata.
        for sample in self.saved["samples"]:
            path = self.archive / sample["evaluationPath"]
            evaluation = load_json(path)
            evaluation.pop("assertionDiagnostics")
            path.write_text(json.dumps(evaluation), encoding="utf-8")
        report = self.report()
        self.assertEqual(report["summary"]["outcomes"], {"passed": 1, "failed": 0, "unevaluable": 1})
        self.assertTrue(all(row["changedFields"] == [] for row in report["samples"]))
        causes = report["summary"]["assertionCauseSummary"]
        self.assertEqual((causes["plannedSamples"], causes["availableSamples"], causes["missingSamples"]), (2, 2, 0))
        required, diagnostic = (causes["byRole"][role] for role in ("required", "diagnostic"))
        self.assertEqual((required["rootAffectedSamples"], required["rootIssueCount"],
                          required["blockedAffectedSamples"], required["blockedAssertionCount"],
                          required["globalGateAffectedSamples"]), (1, 1, 1, 3, 0))
        self.assertEqual(required["rootReasons"], [{"reasonCode": "tool_evidence_missing", "affectedSamples": 1,
                                                    "sampleIds": ["sample-000001"]}])
        self.assertEqual((diagnostic["declaredSamples"], diagnostic["rootAffectedSamples"],
                          diagnostic["blockedAffectedSamples"]), (2, 1, 0))
        self.assertEqual(diagnostic["rootReasons"], [{"reasonCode": "final_text_mismatch", "affectedSamples": 1,
                                                      "sampleIds": ["sample-000002"]}])
        self.assertEqual(report["summary"]["diagnosticSummary"]["passedSamplesWithFailures"], 1)
        for group in report["groups"]:
            self.assertEqual(set(group["bySource"]), {"synthetic"})
            selected = group["bySource"]["synthetic"]["assertionCauseSummary"]
            self.assertEqual((selected["plannedSamples"], selected["availableSamples"]), (1, 1))
        rows = report["samples"]
        blocked = rows[0]["assertionCauses"]["byRole"]["required"]["blockedAssertions"]
        self.assertEqual([item["id"] for item in blocked], ["target-still-missing", "retry", "verify"])
        self.assertEqual(rows[1]["outcome"], "passed")
        directory = Path(report["reportDirectory"])
        browser = ArtifactBrowser(self.root, self.root)
        document = browser.document(browser.reference(directory / "report.json"))
        links = {row["id"] for row in document["links"] if row["id"] is not None}
        markdown = (directory / "report.md").read_text(encoding="utf-8")
        self.assertIn("结构化原因与依赖汇总", markdown)
        for sample in rows:
            self.assertIn(quote(sample["evaluationPath"], safe="/"), markdown)
            reference = browser.reference(directory / sample["evaluationPath"])
            self.assertIn(reference, links)
            fresh = browser.document(reference)["data"]
            self.assertEqual(fresh["assertionDiagnostics"]["assertionDiagnosticsFormatVersion"], 1)
            self.assertEqual(fresh["outcome"], sample["outcome"])
        for sample in self.saved["samples"]:
            self.assertNotIn("assertionDiagnostics", load_json(self.archive / sample["evaluationPath"]))

    def test_missing_evidence_remains_missing_in_the_planned_denominator(self):
        sample = self.saved["samples"][1]
        (self.archive / sample["evidencePath"]).unlink()
        report = self.report()
        missing = report["samples"][1]
        self.assertEqual((missing["verification"], missing["outcome"], missing["evaluationPath"]),
                         ("rejected", "unevaluable", None))
        self.assertEqual((missing["assertionCauses"]["status"], missing["assertionCauses"]["reasonCode"]),
                         ("unavailable", "not_evaluated"))
        summary = report["summary"]["assertionCauseSummary"]
        self.assertEqual((summary["plannedSamples"], summary["availableSamples"], summary["missingSamples"]), (2, 1, 1))
        self.assertEqual(summary["missingReasons"], {"not_evaluated": 1})
        group = next(row for row in report["groups"] if row["caseEntryId"] == "format")
        self.assertEqual(set(group["bySource"]), {"unknown"})
        unknown = group["bySource"]["unknown"]["assertionCauseSummary"]
        self.assertEqual((unknown["plannedSamples"], unknown["availableSamples"], unknown["missingSamples"]), (1, 0, 1))

    def test_global_snapshot_gate_does_not_add_independent_step_roots(self):
        sample = self.saved["samples"][1]
        runtime_path = self.archive / sample["runtimeReport"]
        runtime = load_json(runtime_path)
        runtime["environmentSnapshot"]["complete"] = False
        runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
        report = self.report()
        affected = report["samples"][1]
        self.assertEqual((affected["verification"], affected["outcome"]), ("verified", "unevaluable"))
        value = affected["assertionCauses"]["byRole"]
        self.assertEqual(value["required"]["rootIssues"], [])
        self.assertEqual(value["required"]["blockedAssertions"], [])
        self.assertTrue(value["required"]["globalGates"])
        for role in ("required", "diagnostic"):
            selected = report["summary"]["assertionCauseSummary"]["byRole"][role]
            self.assertEqual(selected["globalGateAffectedSamples"], 1)
            self.assertEqual(selected["globalGateReasons"], [{"reasonCode": "evaluation_evidence_invalid",
                "affectedSamples": 1, "sampleIds": ["sample-000002"]}])
        # The first task still supplies exactly one independent required root and three blocked steps.
        required = report["summary"]["assertionCauseSummary"]["byRole"]["required"]
        self.assertEqual((required["rootIssueCount"], required["blockedAssertionCount"]), (1, 3))


class AssertionCauseContinuationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = resume_fixtures.ExperimentResumeTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.fixture.manifest["repetitions"] = 1
        self.fixture.manifest["configurations"] = self.fixture.manifest["configurations"][:1]
        for entry in self.fixture.manifest["cases"]:
            path = self.fixture.directory / entry["casePath"]
            case = load_json(path)
            answer = next(row for row in case["assertions"] if row["type"] == "final_text")
            answer.update(role="diagnostic", equals="not-the-scripted-answer")
            self.fixture.save(path, case)
        self.fixture.save(self.fixture.path, self.fixture.manifest)

    def test_continuation_reports_separate_reused_new_and_source_cause_coverage(self):
        saved = run_experiment(self.fixture.path, self.fixture.directory / "outputs", stop_after=1)
        source = Path(saved["experimentDirectory"]) / "experiment-result.json"
        plan = plan_experiment_resume(source)
        self.assertTrue(plan["eligibleForResume"])
        continued = resume_experiment(source, self.fixture.directory / "resumes",
                                      expected_plan_sha256=plan["planFingerprint"]["sha256"])
        continuation_path = Path(continued["resumeDirectory"]) / "experiment-resume-result.json"
        before = digest(source.parent)
        report = generate_report(continuation_path, self.fixture.directory / "reports")
        self.assertEqual(digest(source.parent), before)
        self.assertEqual(report["comparisonReportFormatVersion"], 2)
        self.assertEqual([row["executionOrigin"] for row in report["samples"]], ["reused", "new"])
        summary = report["summary"]["assertionCauseSummary"]
        self.assertEqual((summary["plannedSamples"], summary["availableSamples"]), (2, 2))
        self.assertEqual(summary["byRole"]["diagnostic"]["rootAffectedSamples"], 2)
        self.assertEqual(summary["byRole"]["required"]["rootAffectedSamples"], 0)
        for key in ("reusedSummary", "newlyExecutedSummary"):
            selected = report[key]["assertionCauseSummary"]
            self.assertEqual((selected["plannedSamples"], selected["availableSamples"], selected["missingSamples"]), (1, 1, 0))
            self.assertEqual(selected["byRole"]["diagnostic"]["rootAffectedSamples"], 1)
        for group in report["groups"]:
            selected = group["bySource"]["synthetic"]["assertionCauseSummary"]
            self.assertEqual((selected["plannedSamples"], selected["availableSamples"]), (1, 1))
            self.assertTrue(all(sample["outcome"] == "passed" for sample in report["samples"]))

    def test_continuous_resume_report_keeps_all_ancestor_causes_and_latest_origin_split(self):
        self.fixture.manifest["repetitions"] = 2
        self.fixture.save(self.fixture.path, self.fixture.manifest)
        saved = run_experiment(self.fixture.path, self.fixture.directory / "outputs", stop_after=1)
        source = Path(saved["experimentDirectory"]) / "experiment-result.json"
        first_plan = plan_experiment_resume(source)
        first = resume_experiment(source, self.fixture.directory / "first-resumes", stop_after=1,
                                  expected_plan_sha256=first_plan["planFingerprint"]["sha256"])
        first_path = Path(first["resumeDirectory"]) / "experiment-resume-result.json"
        next_plan = plan_experiment_resume(first_path)
        second = resume_experiment(first_path, self.fixture.directory / "second-resumes",
                                   expected_plan_sha256=next_plan["planFingerprint"]["sha256"])
        second_path = Path(second["resumeDirectory"]) / "experiment-resume-result.json"
        roots = [source.parent, first_path.parent, second_path.parent]
        before = {str(root): digest(root) for root in roots}
        report = generate_report(second_path, self.fixture.directory / "reports")
        self.assertEqual({str(root): digest(root) for root in roots}, before)
        self.assertEqual(report["comparisonReportFormatVersion"], 3)
        causes = report["summary"]["assertionCauseSummary"]
        self.assertEqual((causes["plannedSamples"], causes["availableSamples"], causes["missingSamples"]), (4, 4, 0))
        self.assertEqual(causes["byRole"]["diagnostic"]["rootAffectedSamples"], 4)
        for key in ("reusedSummary", "newlyExecutedSummary"):
            selected = report[key]["assertionCauseSummary"]
            self.assertEqual((selected["plannedSamples"], selected["availableSamples"]), (2, 2))
            self.assertEqual(selected["byRole"]["diagnostic"]["rootAffectedSamples"], 2)
        # Batch continuation rows do not all persist configurationMatch; that existing difference is unrelated.
        self.assertTrue(all(not ({"outcome", "assertionOutcome", "recordingOutcome", "executionStatus"}
                                 & set(row["changedFields"])) for row in report["samples"]))
        self.assertTrue(all(row["outcome"] == "passed" for row in report["samples"]))


if __name__ == "__main__":
    unittest.main()
