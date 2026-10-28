"""Windows installer paths must be rejected before a source is claimed."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import UUID

import test_batch_resume as batch_fixtures
import test_experiment_resume as experiment_fixtures
import test_experiment_resume_chain as chain_fixtures
from dsh_eval.experiment_resume import plan_experiment_resume, resume_experiment
from dsh_eval.resume import CLAIM_NAME, _check_resume_output_root, plan_batch_resume, resume_batch
from dsh_eval.runner import ROOT


class ResumeOutputPathTests(unittest.TestCase):
    def snapshot(self, directory):
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in directory.rglob("*") if path.is_file()}

    def fixture(self, kind):
        if kind == "batch":
            fixture = batch_fixtures.BatchResumeTests()
        elif kind == "experiment":
            fixture = experiment_fixtures.ExperimentResumeTests()
        else:
            fixture = chain_fixtures.ExperimentResumeChainTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        if kind != "chain":
            fixture.crash()
        return fixture

    def test_windows_limit_uses_utf16_units_and_includes_the_installer_suffix(self):
        reserved = str(UUID(int=0))
        root = Path(Path.cwd().anchor) / "r"
        operation = root / reserved / "batches" / reserved / "cases" / reserved / "home/profiles/headless/.plugin-manager/logs/operation-XXXXXX"
        padding = 247 - len(str(operation).encode("utf-16-le")) // 2
        allowed = root / ("x" * (padding - 1))
        with patch("dsh_eval.resume.sys.platform", "win32"):
            _check_resume_output_root(allowed)
            with self.assertRaisesRegex(ValueError, "248 UTF-16"):
                _check_resume_output_root(allowed.with_name(allowed.name + "x"))
            # Replacing one ASCII character by a non-BMP character adds one UTF-16 unit.
            with self.assertRaisesRegex(ValueError, "248 UTF-16"):
                _check_resume_output_root(allowed.with_name(allowed.name[:-1] + "\U0001f600"))

    def test_experiment_layout_includes_both_continuation_identifiers(self):
        root = Path(Path.cwd().anchor) / ("r" * 45)
        with patch("dsh_eval.resume.sys.platform", "win32"):
            _check_resume_output_root(root)
            with self.assertRaisesRegex(ValueError, "shorter --runs-root"):
                _check_resume_output_root(root, experiment=True)

    def test_other_platforms_do_not_inherit_the_windows_limit(self):
        with patch("dsh_eval.resume.sys.platform", "linux"):
            _check_resume_output_root(Path("x" * 300), experiment=True)

    def test_batch_rejection_does_not_allocate_claim_or_change_the_source(self):
        fixture = self.fixture("batch")
        plan = plan_batch_resume(fixture.source)
        output = fixture.directory / ("deep" * 35)
        before = self.snapshot(fixture.directory)
        with patch("dsh_eval.resume.sys.platform", "win32"), \
                patch("dsh_eval.resume._check_resume_output_root", wraps=_check_resume_output_root), \
                patch("dsh_eval.resume.uuid4", side_effect=AssertionError("must reject before allocation")), \
                self.assertRaisesRegex(ValueError, "no continuation was claimed"):
            resume_batch(fixture.source, output, expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertFalse(output.exists())
        self.assertFalse((fixture.source.parent / CLAIM_NAME).exists())
        self.assertEqual(self.snapshot(fixture.directory), before)
        self.assertTrue(plan_batch_resume(fixture.source)["canResume"])

    def test_first_and_chained_experiments_reject_before_any_new_identity_or_output(self):
        for kind, module in (("experiment", "experiment_resume"), ("chain", "experiment_resume_chain")):
            with self.subTest(entry=kind):
                fixture = self.fixture(kind)
                source = fixture.source
                directory = fixture.directory if kind == "experiment" else fixture.fixture.directory
                plan = plan_experiment_resume(source)
                output = directory / ("deep" * 35)
                before = self.snapshot(directory)
                with patch("dsh_eval.resume.sys.platform", "win32"), \
                        patch(f"dsh_eval.{module}._check_resume_output_root", wraps=_check_resume_output_root), \
                        patch(f"dsh_eval.{module}.uuid4", side_effect=AssertionError("must reject before allocation")), \
                        self.assertRaisesRegex(ValueError, "no continuation was claimed"):
                    resume_experiment(source, output, expected_plan_sha256=plan["planFingerprint"]["sha256"])
                self.assertFalse(output.exists())
                self.assertEqual(self.snapshot(directory), before)
                self.assertTrue(plan_experiment_resume(source)["eligibleForResume"])

    @unittest.skipUnless(os.name == "nt", "Windows installer path limit")
    def test_real_cli_rejects_before_claiming_and_leaves_the_source_eligible(self):
        fixture = self.fixture("experiment")
        plan = plan_experiment_resume(fixture.source)
        output = fixture.directory / ("deep" * 35)
        before = self.snapshot(fixture.directory)
        process = subprocess.run([sys.executable, "-m", "dsh_eval", "--resume-experiment", str(fixture.source),
            "--run", "--expected-plan-sha256", plan["planFingerprint"]["sha256"], "--runs-root", str(output)],
            cwd=ROOT, capture_output=True, timeout=30)
        self.assertEqual(process.returncode, 2)
        result = json.loads(process.stdout.decode("utf-8"))
        self.assertEqual(result["outcome"], "unevaluable")
        self.assertIn("no continuation was claimed", result["error"])
        self.assertEqual(process.stderr, b"")
        self.assertEqual(self.snapshot(fixture.directory), before)
        self.assertFalse(output.exists())
        self.assertTrue(plan_experiment_resume(fixture.source)["eligibleForResume"])


if __name__ == "__main__":
    unittest.main()
