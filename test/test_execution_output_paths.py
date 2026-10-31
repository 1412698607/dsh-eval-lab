"""Known Windows install paths are checked before any execution output exists."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

from dsh_eval.batch import run_batch
from dsh_eval.experiment import plan_experiment, run_experiment
from dsh_eval.formats import load_json
from dsh_eval.output_paths import check_output_root
from dsh_eval.runner import ROOT, run_case


class ExecutionOutputPathTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsh-output-preflight-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.case = load_json(ROOT / "fixtures/evaluation/retry-read.case.json")
        self.case["configRef"].update(provider="synthetic", model="none")
        self.case_path = self.save("case.json", self.case)
        self.batch_path = self.save("batch.json", {"batchFormatVersion": 1, "batchName": "path preflight",
            "failurePolicy": "continue", "cases": [{"entryId": "case", "casePath": "case.json"}]})
        self.experiment_path = self.save("experiment.json", {"experimentFormatVersion": 1,
            "experimentName": "path preflight", "failurePolicy": "continue", "repetitions": 1,
            "cases": [{"entryId": "case", "casePath": "case.json"}],
            "configurations": [{"configurationId": "synthetic", "configRef": self.case["configRef"]}]})
        self.executions = (("case", run_case, self.case_path, "runner", "evaluation"),
                           ("batch", run_batch, self.batch_path, "batch", "batches"),
                           ("experiment", run_experiment, self.experiment_path, "experiment", "experiments"))

    def save(self, name, data):
        path = self.directory / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def snapshot(self):
        return {path.relative_to(self.directory).as_posix(): path.read_bytes()
                for path in self.directory.rglob("*") if path.is_file()}

    def test_each_layout_accepts_247_and_rejects_248_utf16_units(self):
        reserved = str(UUID(int=0))
        layouts = {"case": (reserved,), "batch": (reserved, "cases", reserved),
                   "experiment": (reserved, "batches", reserved, "cases", reserved),
                   "resume-batch": (reserved, "batches", reserved, "cases", reserved),
                   "resume-experiment": (reserved, "continuations", reserved, "batches", reserved, "cases", reserved)}
        base = Path(self.directory.anchor) / "r"
        for kind, layout in layouts.items():
            operation = base.joinpath(*layout, "home/profiles/headless/.plugin-manager/logs/operation-XXXXXX")
            padding = 247 - len(str(operation).encode("utf-16-le")) // 2 - 1
            self.assertGreater(padding, 0)
            allowed = base / ("x" * padding)
            with self.subTest(kind=kind), patch("dsh_eval.output_paths.sys.platform", "win32"):
                check_output_root(allowed, kind=kind)
                with self.assertRaisesRegex(ValueError, "248 UTF-16"):
                    check_output_root(allowed.with_name(allowed.name + "x"), kind=kind)
                with self.assertRaisesRegex(ValueError, "248 UTF-16"):
                    check_output_root(allowed.with_name(allowed.name[:-1] + "\U0001f600"), kind=kind)

    def test_deep_output_rejects_before_identity_output_or_host(self):
        output = self.directory / ("deep" * 50)
        before = self.snapshot()
        for kind, function, path, module, _default in self.executions:
            with self.subTest(kind=kind), patch("dsh_eval.output_paths.sys.platform", "win32"), ExitStack() as stack:
                for target in (f"dsh_eval.{module}.uuid4", "dsh_eval.runner._prepare", "subprocess.Popen"):
                    stack.enter_context(patch(target, side_effect=AssertionError("must reject before execution")))
                with self.assertRaisesRegex(ValueError, "no execution output was created"):
                    function(path, output)
            self.assertFalse(output.exists())
            self.assertEqual(self.snapshot(), before)

    def test_default_roots_are_checked_before_identity_allocation(self):
        for kind, function, path, module, default in self.executions:
            with self.subTest(kind=kind), \
                    patch("dsh_eval.output_paths.check_output_root", side_effect=ValueError("path preflight")) as check, \
                    patch(f"dsh_eval.{module}.uuid4", side_effect=AssertionError("must not allocate")), \
                    self.assertRaisesRegex(ValueError, "path preflight"):
                function(path)
            check.assert_called_once_with(ROOT / "runs" / default, kind=kind)

    def test_short_root_passes_preflight_without_starting_a_host(self):
        output = Path(self.directory.anchor) / "r"
        before = self.snapshot()
        for kind, function, path, module, _default in self.executions:
            with self.subTest(kind=kind), patch("dsh_eval.output_paths.sys.platform", "win32"), \
                    patch(f"dsh_eval.{module}.uuid4", side_effect=ValueError("stop before allocation")), \
                    self.assertRaisesRegex(ValueError, "stop before allocation"):
                function(path, output)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_inputs_and_mismatched_plan_precede_output_check(self):
        self.save("case.json", {"invalid": True})
        output = self.directory / ("deep" * 50)
        for kind, function, path, _module, _default in self.executions:
            with self.subTest(kind=kind), patch("dsh_eval.output_paths.check_output_root", side_effect=AssertionError("invalid input first")), \
                    self.assertRaises(ValueError):
                function(path, output)
        self.save("case.json", self.case)
        with patch("dsh_eval.output_paths.check_output_root", side_effect=AssertionError("fingerprint first")), \
                self.assertRaisesRegex(ValueError, "plan fingerprint mismatch"):
            run_experiment(self.experiment_path, output, expected_plan_sha256="0" * 64)
        self.assertFalse(output.exists())

    def test_experiment_preview_never_checks_future_output_or_allocates(self):
        before = self.snapshot()
        with patch("dsh_eval.output_paths.check_output_root", side_effect=AssertionError("preview has no output root")), \
                patch("dsh_eval.experiment.uuid4", side_effect=AssertionError("preview cannot allocate")):
            plan = plan_experiment(self.experiment_path)
        self.assertTrue(plan["valid"])
        self.assertFalse(plan["modelCalled"])
        self.assertEqual(self.snapshot(), before)

    def test_non_windows_does_not_inherit_the_installer_limit(self):
        for kind in ("case", "batch", "experiment", "resume-batch", "resume-experiment"):
            with self.subTest(kind=kind), patch("dsh_eval.output_paths.sys.platform", "linux"):
                check_output_root(self.directory / ("x" * 300), kind=kind)

    @unittest.skipUnless(os.name == "nt", "Windows execution path preflight")
    def test_real_python_cli_rejects_each_entry_without_outputs(self):
        output = self.directory / ("deep" * 50)
        before = self.snapshot()
        for kind, _function, path, _module, _default in self.executions:
            process = subprocess.run([sys.executable, "-m", "dsh_eval", "--" + kind, str(path),
                                      "--run", "--runs-root", str(output)], cwd=ROOT, capture_output=True, timeout=30)
            with self.subTest(kind=kind):
                self.assertEqual(process.returncode, 2)
                result = json.loads(process.stdout.decode("utf-8"))
                self.assertEqual(result["outcome"], "unevaluable")
                self.assertIn("no execution output was created", result["error"])
                self.assertEqual(process.stderr, b"")
                self.assertFalse(output.exists())
                self.assertEqual(self.snapshot(), before)

    @unittest.skipUnless(os.name == "nt", "Windows ordinary Node directory limit")
    def test_real_node_mkdtemp_boundary_matches_the_conservative_guard(self):
        script = """import {mkdir,mkdtemp} from 'node:fs/promises';
import {dirname} from 'node:path';
const prefix=process.argv[1];
await mkdir(dirname(prefix),{recursive:true});
try { const path=await mkdtemp(prefix); console.log(JSON.stringify({ok:true,units:path.length})); }
catch(error) { console.log(JSON.stringify({ok:false,code:error.code})); }
"""
        for limit in (247, 248):
            parent = self.directory / str(limit)
            padding = limit - len(str(parent / "operation-").encode("utf-16-le")) // 2 - 7
            prefix = parent / ("x" * padding) / "operation-"
            process = subprocess.run(["node", "--input-type=module", "-e", script, str(prefix)],
                                     capture_output=True, timeout=15)
            with self.subTest(units=limit):
                self.assertEqual(process.returncode, 0, process.stderr)
                result = json.loads(process.stdout)
                if limit == 247:
                    self.assertEqual(result, {"ok": True, "units": 247})
                else:
                    self.assertFalse(result["ok"])
                    self.assertIn(result["code"], ("ENAMETOOLONG", "ENOENT"))
