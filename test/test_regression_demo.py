"""Public gate examples use actual synthetic subprocesses and fresh CLI rechecks."""
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from dsh_eval.formats import load_json
from dsh_eval.regression_demo import _check_comparison, _compare, generate_regression_demo, main
from dsh_eval.runner import ROOT
from dsh_eval import regression_demo


def process_active(pid):
    if os.name == "nt":
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # The owned PID no longer exists.
                return False
            raise ctypes.WinError(error)
        try:
            status = ctypes.c_uint32()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(status)):
                raise ctypes.WinError(ctypes.get_last_error())
            return status.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    status = Path(f"/proc/{pid}/stat")
    try:
        return not status.is_file() or status.read_text().split()[2] != "Z"
    except FileNotFoundError:
        return False


def cleanup_owned_process(pid):
    if not process_active(pid):
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        os.kill(pid, signal.SIGKILL)


class RegressionDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="dsh-regression-demo-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.base = Path(cls.temporary.name).resolve()
        cls.directory = cls.base / "first"
        cls.index = generate_regression_demo(cls.directory)

    def scenario(self, name):
        return next(row for row in self.index["scenarios"] if row["id"] == name)

    def test_actual_cli_exit_codes_keep_confirmed_regression_when_coverage_is_incomplete(self):
        self.assertEqual(self.index["status"], "completed")
        self.assertFalse(self.index["modelCalled"])
        self.assertEqual([row["actualExitCode"] for row in self.index["scenarios"]], [0, 1, 2])
        for name, expected in (("no-regression", (0, 2, 0, 2)), ("regression", (1, 1, 0, 2)),
                               ("incomplete", (1, 0, 1, 1))):
            with self.subTest(scenario=name):
                result = load_json(self.scenario(name)["comparisonPath"])
                self.assertEqual(result["status"], "compared")
                counts = result["counts"]
                self.assertEqual(tuple(counts[key] for key in ("regression", "unchanged_passed", "unavailable", "compared")), expected)
                self.assertEqual(counts["total"], 2)
                self.assertTrue(all(row["baseline"]["source"] == "synthetic" for row in result["samples"]))
        incomplete = load_json(self.scenario("incomplete")["comparisonPath"])
        self.assertTrue(incomplete["hasRegressions"])
        self.assertEqual(incomplete["outcome"], "unevaluable")
        self.assertEqual(incomplete["samples"][1]["candidate"]["status"], "skipped")
        self.assertIn("candidate_evidence_unavailable", incomplete["samples"][1]["reasons"])

    def test_independent_recordings_and_fixed_replies_supply_real_synthetic_evidence(self):
        paths = [self.index["baselinePath"], *(row["candidatePath"] for row in self.index["scenarios"])]
        experiments = [load_json(path) for path in paths]
        self.assertEqual(len({row["experimentId"] for row in experiments}), 4)
        identities = {key: [] for key in ("caseRunId", "runId", "sessionId")}
        for path, experiment in zip(paths, experiments):
            self.assertFalse(experiment["modelCalled"])
            self.assertEqual(experiment["executionMode"], "synthetic")
            for sample in experiment["samples"]:
                if sample["status"] == "skipped":
                    continue
                for key in identities:
                    identities[key].append(sample[key])
                evidence_path = Path(path).parent / sample["evidencePath"]
                evidence = load_json(evidence_path)
                self.assertEqual(evidence["source"], "synthetic")
                self.assertFalse(load_json(evidence_path.parent / "runtime.json")["modelCalled"])
                trace, = (Path(path).parent / sample["runDir"]).glob("*.jsonl")
                events = [json.loads(line)["event"] for line in trace.read_text(encoding="utf-8").splitlines()]
                answer, = [event for event in events if event["type"] == "assistant/message"]
                text = answer["data"]["message"]["content"][0]["text"]
                expected = "WRONG" if experiment["outcome"] == "failed" and sample["repeatIndex"] == 1 else "done"
                self.assertEqual(text, expected)
        for values in identities.values():
            self.assertEqual(len(values), 7)
            self.assertEqual(len(set(values)), 7)

    def test_only_five_generated_summary_files_are_artifacts_and_sources_keep_their_bytes(self):
        artifacts = Path(self.index["artifactsDirectory"])
        self.assertEqual({path.name for path in artifacts.iterdir()},
                         {"no-regression.json", "regression.json", "incomplete.json", "summary.md", "index.json"})
        self.assertTrue(all(path.is_file() for path in artifacts.iterdir()))
        self.assertEqual(load_json(artifacts / "index.json"), self.index)
        self.assertTrue(self.index["sourceArchivesUnchanged"])
        checked = 0
        for root, files in self.index["archiveSha256"].items():
            for name, digest in files.items():
                self.assertEqual(hashlib.sha256((self.directory / root / name).read_bytes()).hexdigest(), digest)
                checked += 1
        self.assertEqual(checked, self.index["archiveFilesChecked"])
        text = (artifacts / "summary.md").read_text(encoding="utf-8")
        self.assertIn("not that all tasks passed", text)
        self.assertIn("Real gates must propagate", text)
        for name in ("no-regression", "regression", "incomplete"):
            self.assertIn(f"`{name}.json`", text)

    def test_real_cli_rechecks_recording_even_when_saved_experiment_outcome_is_forged(self):
        path = Path(self.scenario("regression")["candidatePath"])
        before = path.read_bytes()
        try:
            saved = load_json(path)
            saved["samples"][0]["outcome"] = "passed"
            path.write_text(json.dumps(saved), encoding="utf-8")
            completed = subprocess.run([sys.executable, "-m", "dsh_eval", "--compare-baseline", self.index["baselinePath"],
                                        "--candidate", str(path)], cwd=ROOT, capture_output=True, text=True,
                                       encoding="utf-8", timeout=60)
            self.assertEqual(completed.returncode, 1, completed.stderr + completed.stdout)
            comparison = json.loads(completed.stdout)
            candidate = comparison["samples"][0]["candidate"]
            self.assertEqual(candidate["saved"]["outcome"], "passed")
            self.assertEqual(candidate["outcome"], "failed")
            self.assertIn("outcome", candidate["changedFields"])
        finally:
            path.write_bytes(before)

    def test_input_error_exit_two_cannot_satisfy_expected_incomplete_example(self):
        result = load_json(self.scenario("incomplete")["comparisonPath"])
        with self.assertRaisesRegex(ValueError, "normal, model-free comparison"):
            _check_comparison({"regressionComparisonFormatVersion": 1, "modelCalled": False,
                               "status": "error", "exitCode": 2}, "incomplete", 2)
        with self.assertRaisesRegex(ValueError, "exit code"):
            _check_comparison(result, "incomplete", 0)
        changed = deepcopy(result)
        changed["counts"]["regression"] = 0
        with self.assertRaisesRegex(ValueError, "coverage or verdict"):
            _check_comparison(changed, "incomplete", 2)

    def test_actual_cli_input_error_keeps_scenario_and_exit_in_demo_diagnostic(self):
        output = self.base / "input-error.json"
        with self.assertRaisesRegex(ValueError, "incomplete comparison failed \\(exit 2\\).*normal, model-free comparison") as error:
            _compare(self.base / "missing-baseline.json", self.scenario("incomplete")["candidatePath"], output, "incomplete")
        self.assertIn("stderr tail: (empty)", str(error.exception))
        self.assertFalse(output.exists())

    def test_existing_outputs_and_file_parents_fail_without_overwriting(self):
        index_path = Path(self.index["artifactsDirectory"]) / "index.json"
        before = index_path.read_bytes()
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--output-dir", str(self.directory)])
        self.assertEqual((code, json.loads(output.getvalue())["status"]), (2, "error"))
        self.assertEqual(index_path.read_bytes(), before)
        blocked = self.base / "blocked"
        blocked.write_bytes(b"keep")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--output-dir", str(blocked / "child")]), 2)
        self.assertEqual(blocked.read_bytes(), b"keep")

    def test_existing_dangling_output_link_cannot_create_target_or_be_overwritten(self):
        target, link = self.base / "uncreated-output-target", self.base / "dangling-output-link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Actual directory symlink creation unavailable: {error}")
        original = os.readlink(link)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--output-dir", str(link)]), 2)
        self.assertFalse(target.exists())
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), original)

    def fault_comparison(self, name):
        directory = self.base / name
        package = directory / "dsh_eval"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "__main__.py").write_text(
            "import json, os, subprocess\nfrom pathlib import Path\n"
            "options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}\n"
            "child = subprocess.Popen(['node', '-e', "
            "\"setTimeout(() => require('node:fs').writeFileSync(process.argv[1], 'natural'), 30000)\", "
            "str(Path(__file__).parents[1] / 'natural-exit')], stdin=subprocess.DEVNULL, "
            "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)\n"
            "Path(__file__).parents[1].joinpath('owned-processes.json').write_text("
            "json.dumps({'parent': os.getpid(), 'child': child.pid}), encoding='utf-8')\n"
            "child.wait(timeout=35)\n", encoding="utf-8")
        return directory, directory / "owned-processes.json"

    def assert_fault_processes_reaped(self, marker):
        self.assertTrue(marker.is_file(), "The fault CLI did not start its real inspector descendant")
        identities = load_json(marker)
        try:
            self.assertFalse(marker.with_name("natural-exit").exists(), "Cleanup waited for the fixture's natural exit")
            for pid in identities.values():
                self.assertNotEqual(pid, os.getpid())
                deadline = time.monotonic() + 3
                while process_active(pid) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertFalse(process_active(pid), f"Owned comparison process {pid} survived cleanup")
        finally:
            for pid in identities.values():
                if pid != os.getpid():
                    cleanup_owned_process(pid)

    def test_timeout_reaps_actual_comparison_cli_and_its_inspector_descendant(self):
        directory, marker = self.fault_comparison("timeout-cli")
        try:
            with patch.object(regression_demo, "ROOT", directory), patch.object(regression_demo, "COMPARISON_TIMEOUT", 2):
                with self.assertRaises(subprocess.TimeoutExpired):
                    _compare(directory / "baseline.json", directory / "candidate.json", directory / "comparison.json", "no-regression")
        finally:
            self.assert_fault_processes_reaped(marker)

    def test_keyboard_interrupt_reaps_actual_comparison_cli_and_inspector_descendant(self):
        directory, marker = self.fault_comparison("interrupted-cli")
        actual_popen = subprocess.Popen

        class InterruptedPopen(actual_popen):
            def communicate(self, *args, **kwargs):
                if self.args[:3] == [sys.executable, "-m", "dsh_eval"]:
                    deadline = time.monotonic() + 3
                    while not marker.is_file() and self.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.01)
                    if not marker.is_file() or not process_active(load_json(marker)["child"]):
                        raise AssertionError("Fault CLI did not start its real inspector descendant")
                    # Inject only the interruption; both processes and their cleanup remain real.
                    raise KeyboardInterrupt
                return super().communicate(*args, **kwargs)

        try:
            with patch.object(regression_demo, "ROOT", directory), \
                    patch("dsh_eval.regression_demo.subprocess.Popen", InterruptedPopen):
                with self.assertRaises(KeyboardInterrupt):
                    _compare(directory / "baseline.json", directory / "candidate.json", directory / "comparison.json", "no-regression")
        finally:
            self.assert_fault_processes_reaped(marker)

    def test_public_cli_rebuilds_from_clean_copied_checkout_with_new_identities(self):
        checkout = self.base / "checkout"
        checkout.mkdir()
        for name in ("dsh_eval", "src", "scripts", "fixtures"):
            shutil.copytree(ROOT / name, checkout / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(ROOT / "package.json", checkout / "package.json")
        completed = subprocess.run([sys.executable, "-m", "dsh_eval.regression_demo", "--output-dir", str(self.base / "second")],
                                   cwd=checkout, capture_output=True, text=True, encoding="utf-8", timeout=90)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        index = json.loads(completed.stdout)
        self.assertEqual([row["actualExitCode"] for row in index["scenarios"]], [0, 1, 2])
        self.assertNotEqual(index["demoId"], self.index["demoId"])
        old, new = load_json(self.index["baselinePath"]), load_json(index["baselinePath"])
        self.assertNotEqual(old["experimentId"], new["experimentId"])
        self.assertNotEqual(old["samples"][0]["caseRunId"], new["samples"][0]["caseRunId"])
        self.assertFalse(index["modelCalled"])


if __name__ == "__main__":
    unittest.main()
