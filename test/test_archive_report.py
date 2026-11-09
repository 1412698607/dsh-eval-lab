"""Fresh reports from moved bundles retain scores, identities and continuation proof bytes."""
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dsh_eval.__main__ import main
from dsh_eval.archive_bundle import export_archive, verify_archive
from dsh_eval.experiment import run_experiment
from dsh_eval.formats import load_json
from dsh_eval.report import generate_report
from dsh_eval.runner import ROOT, save_json
import test_experiment_resume_chain as chains


@contextmanager
def hidden_source_directories(root):
    """Rename only known fixture directories within their owned temporary root."""
    retired = []
    root = root.resolve()
    try:
        for name in ("experiments", "resumes", "again"):
            source, target = root / name, root / ("retired-" + name)
            if source.exists():
                if not source.resolve().is_relative_to(root) or not target.resolve().is_relative_to(root) or target.exists():
                    raise AssertionError("Fixture rename escaped its owned root or collided")
                source.rename(target)
                retired.append((source, target))
        yield
    finally:
        for source, target in reversed(retired):
            if not target.resolve().is_relative_to(root) or not source.resolve().is_relative_to(root):
                raise AssertionError("Fixture restore escaped its owned root")
            target.rename(source)


class ArchiveReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsh-archive-report-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        case = load_json(ROOT / "fixtures/evaluation/rename-confirmation.case.json")
        case["configRef"].update(provider="synthetic", model="scripted")
        save_json(self.root / "case.json", case)
        save_json(self.root / "experiment.json", {"experimentFormatVersion": 1, "experimentName": "archive-report",
                  "repetitions": 1, "failurePolicy": "continue", "cases": [{"entryId": "rename", "casePath": "case.json"}],
                  "configurations": [{"configurationId": "scripted", "configRef": case["configRef"]}]})
        result = run_experiment(self.root / "experiment.json", self.root / "experiments",
                                _synthetic_replies={"sample-000001": "**done**"})
        self.source = Path(result["experimentDirectory"]) / "experiment-result.json"
        self.baseline = generate_report(self.source, self.root / "baseline-reports")
        self.original = self.root / "original-bundle"
        export_archive(self.source, self.root, self.original,
                       artifacts=[Path(self.baseline["reportDirectory"]) / "report.json"])
        self.bundle = self.root / "moved-bundle"
        shutil.copytree(self.original, self.bundle)

    def test_cli_rechecks_moved_bundle_with_original_experiment_unavailable(self):
        before = (self.bundle / "archive-manifest.json").read_bytes()
        with hidden_source_directories(self.root):
            self.assertFalse(self.source.exists())
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["--report", str(self.bundle / "archive-manifest.json"),
                             "--reports-root", str(self.root / "moved-reports")])
            self.assertEqual(code, 0, stdout.getvalue())
            report = load_json(Path(json.loads(stdout.getvalue())["reportDirectory"]) / "report.json")
            self.assertEqual(report["summary"], self.baseline["summary"])
            self.assertEqual(report["planVerification"], self.baseline["planVerification"])
            self.assertEqual(report["verificationCounts"], {"verified": 1})
            self.assertEqual(report["samples"][0]["changedFields"], self.baseline["samples"][0]["changedFields"])
            self.assertEqual(report["archiveBundle"]["archiveId"], load_json(self.bundle / "archive-manifest.json")["archiveId"])
            evidence = Path(report["samples"][0]["sourceEvidencePath"])
            self.assertTrue(evidence.is_relative_to(self.bundle / "payload"))
            self.assertEqual(load_json(Path(report["reportDirectory"]) / "report.json"), report)
            self.assertEqual(verify_archive(self.bundle)["status"], "verified")
        self.assertEqual((self.bundle / "archive-manifest.json").read_bytes(), before)

    def test_report_output_inside_immutable_bundle_is_rejected(self):
        before = (self.bundle / "archive-manifest.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "outside the immutable bundle"):
            generate_report(self.bundle, self.bundle / "reports")
        self.assertFalse((self.bundle / "reports").exists())
        self.assertEqual((self.bundle / "archive-manifest.json").read_bytes(), before)
        self.assertEqual(verify_archive(self.bundle)["status"], "verified")

    def test_export_and_verify_cli_bind_the_same_published_directory(self):
        output = self.root / "cli-bundle"
        exported = subprocess.run([sys.executable, "-m", "dsh_eval.archive_bundle", "export", "--entry", str(self.source),
                                   "--source-root", str(self.root), "--output", str(output)], cwd=ROOT,
                                  capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(exported.returncode, 0, exported.stderr + exported.stdout)
        self.assertEqual(json.loads(exported.stdout), load_json(output / "archive-manifest.json"))
        verified = subprocess.run([sys.executable, "-m", "dsh_eval.archive_bundle", "verify", str(output)], cwd=ROOT,
                                  capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(verified.returncode, 0, verified.stderr + verified.stdout)
        value = json.loads(verified.stdout)
        self.assertEqual((value["status"], value["modelCalled"], value["taskEvaluationPerformed"]), ("verified", False, False))
        self.assertEqual(value["archiveId"], json.loads(exported.stdout)["archiveId"])

    def test_bundle_directory_symlink_cannot_bypass_archive_input_validation(self):
        alias = self.root / "bundle-alias"
        try:
            os.symlink(self.bundle, alias, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Cannot create the actual symlink: {error}")
        with self.assertRaisesRegex(ValueError, "links or junctions"):
            generate_report(alias, self.root / "alias-reports")
        self.assertFalse((self.root / "alias-reports").exists())

    def test_changed_payload_during_scoring_is_rejected_before_report_output(self):
        from dsh_eval import report as module
        original = module._recheck
        touched = False

        def change_after_recheck(*args):
            nonlocal touched
            result = original(*args)
            if not touched:
                path = Path(result[1]["association"]["casePath"])
                self.assertTrue(path.is_relative_to(self.bundle / "payload"))
                path.write_bytes(path.read_bytes() + b" ")
                touched = True
            return result

        with patch("dsh_eval.report._recheck", side_effect=change_after_recheck):
            with self.assertRaisesRegex(ValueError, "missing or changed"):
                generate_report(self.bundle, self.root / "rejected-reports")
        self.assertTrue(touched)
        self.assertFalse((self.root / "rejected-reports").exists())

    def test_manifest_mutation_after_semantic_verification_is_rejected_before_output(self):
        from dsh_eval import archive_bundle
        original = archive_bundle.verify_archive

        def change_after_verification(path):
            result = original(path)
            manifest_path = self.bundle / "archive-manifest.json"
            manifest = load_json(manifest_path)
            manifest["artifacts"][0]["kind"] = "experiment_resume"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            return result

        with patch("dsh_eval.archive_bundle.verify_archive", side_effect=change_after_verification):
            with self.assertRaisesRegex(ValueError, "changed during semantic verification"):
                generate_report(self.bundle, self.root / "semantic-change-reports")
        self.assertFalse((self.root / "semantic-change-reports").exists())


class ArchiveContinuationReportTests(unittest.TestCase):
    def test_first_and_continuous_resume_reports_preserve_fingerprints_after_move(self):
        fixture = chains.ExperimentResumeChainTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        root = fixture.fixture.directory
        first = fixture.source
        continued = fixture.execute()
        latest = Path(continued["resumeDirectory"]) / "experiment-resume-result.json"
        for number, (source, version) in enumerate(((first, 2), (latest, 3)), 1):
            with self.subTest(version=version):
                baseline = generate_report(source, root / f"baseline-{number}")
                bundle, moved = root / f"bundle-{number}", root / f"moved-{number}"
                export_archive(source, root, bundle, artifacts=[Path(baseline["reportDirectory"]) / "report.json"])
                shutil.copytree(bundle, moved)
                manifest = load_json(moved / "archive-manifest.json")
                fingerprints = deepcopy(baseline["resumeVerification"])
                with hidden_source_directories(root):
                    self.assertFalse(source.exists())
                    self.assertEqual(verify_archive(moved)["status"], "verified")
                    report = generate_report(moved, root / f"reports-{number}")
                    self.assertEqual(report["comparisonReportFormatVersion"], version)
                    self.assertEqual(report["summary"], baseline["summary"])
                    self.assertEqual(report["reusedSummary"], baseline["reusedSummary"])
                    self.assertEqual(report["newlyExecutedSummary"], baseline["newlyExecutedSummary"])
                    self.assertEqual(report["resumeVerification"]["planFingerprint"], fingerprints["planFingerprint"])
                    self.assertEqual(report["resumeVerification"]["batchPlanFingerprint"], fingerprints["batchPlanFingerprint"])
                    for row in report["samples"]:
                        self.assertTrue(Path(row["sourceBatchResult"]).is_relative_to(moved / "payload"))
                        if row["sourceEvidencePath"] is not None:
                            self.assertTrue(Path(row["sourceEvidencePath"]).is_relative_to(moved / "payload"))
                    for key in ("sourceExperimentResult", "sourceResumeResult"):
                        self.assertTrue(Path(report[key]).is_relative_to(moved / "payload"))
                    self.assertEqual(load_json(moved / "archive-manifest.json"), manifest)


if __name__ == "__main__":
    unittest.main()
