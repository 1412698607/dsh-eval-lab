"""Plan fingerprints bind reviewed experiment inputs to an optional execution guard."""
import copy
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dsh_eval.__main__ import main
from dsh_eval import experiment
from dsh_eval.formats import load_json
from dsh_eval.runner import ROOT


class ExperimentFingerprintTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsh-fingerprint-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.outputs = self.directory / "outputs"
        case = load_json(ROOT / "fixtures/evaluation/retry-read.case.json")
        case["configRef"].update(provider="unavailable-provider", model="first")
        later = copy.deepcopy(case)
        later["caseId"] += "-later"
        self.cases = {"case.json": case, "later.json": later}
        self.manifest = {"experimentFormatVersion": 1, "experimentName": "计划指纹", "repetitions": 2,
                         "failurePolicy": "continue",
                         "cases": [{"entryId": "one", "casePath": "case.json"},
                                   {"entryId": "two", "casePath": "later.json"}],
                         "configurations": [{"configurationId": name, "configRef": {**case["configRef"], "model": name}}
                                            for name in ("first", "second")]}
        self.path = self.directory / "experiment.json"
        self.restore()

    def save(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def restore(self):
        self.save(self.path, self.manifest)
        for name, case in self.cases.items():
            self.save(self.directory / name, case)

    def snapshot(self):
        return {path.relative_to(self.directory).as_posix(): path.read_bytes()
                for path in self.directory.rglob("*") if path.is_file()}

    def fingerprint(self, **options):
        return experiment.plan_experiment(self.path, **options)["planFingerprint"]

    def test_fingerprint_is_versioned_deterministic_and_read_only(self):
        before = self.snapshot()
        with ExitStack() as stack:
            for target in ("dsh_eval.experiment.uuid4", "dsh_eval.experiment.run_batch", "subprocess.Popen"):
                stack.enter_context(patch(target, side_effect=AssertionError(f"Plan must not call {target}")))
            first = self.fingerprint()
            self.assertEqual(first, self.fingerprint())
        self.assertEqual(set(first), {"version", "sha256"})
        self.assertEqual(first["version"], 1)
        self.assertRegex(first["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(self.snapshot(), before)

    def test_json_formatting_key_order_and_root_relocation_do_not_change_fingerprint(self):
        expected = self.fingerprint(max_samples=8)
        moved = self.directory / "moved"
        moved.mkdir()

        def reordered(value):
            if isinstance(value, dict):
                return {key: reordered(value[key]) for key in reversed(value)}
            if isinstance(value, list):
                return [reordered(item) for item in value]
            return value

        for name, value in {"experiment.json": self.manifest, **self.cases}.items():
            (moved / name).write_text(json.dumps(reordered(value), ensure_ascii=True, indent=4), encoding="utf-8")
        result = experiment.plan_experiment(moved / "experiment.json", max_samples=8)
        self.assertEqual(result["planFingerprint"], expected)
        self.assertNotEqual(result["sourceManifest"], str(self.path.resolve()))

    def test_all_manifest_declarations_and_later_case_content_are_covered(self):
        expected = self.fingerprint()
        for change in ({"experimentName": "renamed"}, {"failurePolicy": "stop"}, {"repetitions": 3},
                       {"cases": list(reversed(self.manifest["cases"]))},
                       {"configurations": list(reversed(self.manifest["configurations"]))}):
            self.restore()
            self.save(self.path, {**self.manifest, **change})
            with self.subTest(manifest=change):
                self.assertNotEqual(self.fingerprint(), expected)
        for field, value in (("entryId", "renamed"), ("casePath", "copied.json")):
            self.restore()
            self.save(self.directory / "copied.json", self.cases["later.json"])
            manifest = copy.deepcopy(self.manifest)
            manifest["cases"][1][field] = value
            self.save(self.path, manifest)
            with self.subTest(field=field):
                self.assertNotEqual(self.fingerprint(), expected)
        self.restore()
        manifest = copy.deepcopy(self.manifest)
        manifest["configurations"][1]["configRef"]["model"] = "changed"
        self.save(self.path, manifest)
        self.assertNotEqual(self.fingerprint(), expected)
        later = self.cases["later.json"]
        assertions = copy.deepcopy(later["assertions"])
        next(item for item in assertions if item["type"] == "final_text")["equals"] = "changed answer"
        environment = copy.deepcopy(later["environment"])
        environment["files"]["extra.txt"] = "新增内容"
        for change in ({"caseId": "renamed"}, {"input": "changed task"}, {"budget": {"timeoutSeconds": 99}},
                       {"environment": environment}, {"assertions": assertions},
                       {"configRef": {**later["configRef"], "model": "overridden-but-still-frozen"}}):
            self.restore()
            self.save(self.directory / "later.json", {**later, **change})
            with self.subTest(case=change):
                self.assertNotEqual(self.fingerprint(), expected)

    def test_cap_and_omitted_empty_or_explicit_recorder_declarations_are_distinct(self):
        fingerprints = [self.fingerprint(max_samples=limit)["sha256"] for limit in (None, 8, 9)]
        self.assertEqual(len(set(fingerprints)), 3)
        declarations = [None, {}, {"maxEventBytes": 1048576}, {"maxPendingBytes": 16777216}]
        fingerprints = []
        for declaration in declarations:
            case = copy.deepcopy(self.cases["later.json"])
            if declaration is not None:
                case["recorder"] = declaration
            self.save(self.directory / "later.json", case)
            fingerprints.append(self.fingerprint()["sha256"])
        self.assertEqual(len(set(fingerprints)), len(declarations))

    def test_mismatch_rejects_before_expansion_identifiers_output_or_runtime(self):
        before = self.snapshot()
        with ExitStack() as stack:
            for target in ("dsh_eval.experiment._expand_samples", "dsh_eval.experiment.uuid4",
                           "dsh_eval.experiment.run_batch", "dsh_eval.runner._prepare", "subprocess.Popen"):
                stack.enter_context(patch(target, side_effect=AssertionError(f"Mismatch must precede {target}")))
            with self.assertRaisesRegex(ValueError, "Experiment plan fingerprint mismatch"):
                experiment.run_experiment(self.path, self.outputs, expected_plan_sha256="0" * 64)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.outputs.exists())

    def test_malformed_expected_hash_is_rejected_before_reading_inputs(self):
        for value in (True, 1, {}, [], "", "g" * 64, "a" * 63, "a" * 65, "a" * 64 + "\n", " " + "a" * 64):
            with self.subTest(value=value), \
                    patch("dsh_eval.experiment.load_json", side_effect=AssertionError("Must validate expected hash first")), \
                    self.assertRaisesRegex(ValueError, "expected_plan_sha256 must contain exactly 64 hexadecimal characters"):
                experiment.run_experiment(self.path, self.outputs, expected_plan_sha256=value)
        self.assertFalse(self.outputs.exists())

    def test_cli_rejects_expected_hash_outside_experiment_run(self):
        for selection in (["--experiment", str(self.path), "--plan"], ["--experiment", str(self.path)],
                          ["--case", "x", "--run"], ["--batch", "x", "--run"], ["--report", "x"], ["--browse"]):
            for value in ("a" * 64, ""):
                with self.subTest(selection=selection, value=value), redirect_stderr(io.StringIO()), \
                        self.assertRaises(SystemExit) as error:
                    main([*selection, "--expected-plan-sha256", value])
                self.assertEqual(error.exception.code, 2)

    def test_cli_forwards_expected_hash_and_preserves_task_exit_codes(self):
        for outcome, code in (("passed", 0), ("failed", 1), ("unevaluable", 2)):
            with self.subTest(outcome=outcome), \
                    patch("dsh_eval.experiment.run_experiment", return_value={"outcome": outcome}) as run, \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--experiment", str(self.path), "--run", "--max-samples", "8",
                                       "--expected-plan-sha256", "a" * 64]), code)
            self.assertEqual(run.call_args.kwargs, {"max_samples": 8, "expected_plan_sha256": "a" * 64, "stop_after": None})

    def test_cli_malformed_hash_returns_input_error_without_runtime_or_output(self):
        before = self.snapshot()
        for value in ("", "not-a-hash", "a" * 64 + "\n"):
            with self.subTest(value=value), redirect_stdout(io.StringIO()) as output, \
                    patch("dsh_eval.experiment.uuid4", side_effect=AssertionError("Must not allocate identity")):
                code = main(["--experiment", str(self.path), "--run", "--runs-root", str(self.outputs),
                             "--expected-plan-sha256", value])
            self.assertEqual(code, 2)
            report = json.loads(output.getvalue())
            self.assertEqual(report["outcome"], "unevaluable")
            self.assertIn("exactly 64 hexadecimal characters", report["error"])
            self.assertEqual(self.snapshot(), before)
            self.assertFalse(self.outputs.exists())

    def test_expected_hash_cannot_bypass_case_or_configuration_validation(self):
        expected = self.fingerprint()["sha256"]
        self.save(self.directory / "later.json", {"invalid": True})
        with self.assertRaisesRegex(ValueError, "Missing fields"):
            experiment.run_experiment(self.path, self.outputs, expected_plan_sha256=expected)
        self.restore()
        manifest = copy.deepcopy(self.manifest)
        manifest["configurations"][1]["configRef"]["profile"] = "web"
        self.save(self.path, manifest)
        with self.assertRaisesRegex(ValueError, "headless"):
            experiment.run_experiment(self.path, self.outputs, expected_plan_sha256=expected)
        self.assertFalse(self.outputs.exists())

    def test_real_cli_detects_same_count_content_changes_and_missing_cap_without_output(self):
        result = subprocess.run([sys.executable, "-m", "dsh_eval", "--experiment", str(self.path),
                                 "--plan", "--max-samples", "8"], cwd=ROOT, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(result.stderr, b"")
        plan = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(plan["experimentName"], "计划指纹")
        expected = plan["planFingerprint"]["sha256"]
        for cap in ([], ["--max-samples", "8"]):
            self.restore()
            if cap:
                later = {**self.cases["later.json"], "input": "same sample count, changed task"}
                self.save(self.directory / "later.json", later)
            before = self.snapshot()
            result = subprocess.run([sys.executable, "-m", "dsh_eval", "--experiment", str(self.path), "--run",
                                     "--runs-root", str(self.outputs), "--expected-plan-sha256", expected, *cap],
                                    cwd=ROOT, capture_output=True, check=False)
            with self.subTest(cap=cap):
                self.assertEqual(result.returncode, 2, result.stderr.decode("utf-8", errors="replace"))
                self.assertEqual(result.stderr, b"")
                report = json.loads(result.stdout.decode("utf-8"))
                self.assertEqual(report["outcome"], "unevaluable")
                self.assertIn("Experiment plan fingerprint mismatch", report["error"])
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(self.outputs.exists())


if __name__ == "__main__":
    unittest.main()
