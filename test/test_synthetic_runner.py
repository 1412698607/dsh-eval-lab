"""Fixed scripts exercise the production supervisor, recorder and evaluator without Harness."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

from dsh_eval.evaluate import evaluate
from dsh_eval.formats import load_json
from dsh_eval.runner import ROOT, run_synthetic_case


class SyntheticRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dsh-synthetic-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.case = load_json(ROOT / "fixtures/evaluation/rename-timeout-retry.case.json")
        self.case["configRef"].update(provider="synthetic", model="none")
        self.path = self.directory / "input.json"
        self.path.write_text(json.dumps(self.case), encoding="utf-8")
        self.outputs = self.directory / "runs"

    def test_real_script_records_source_and_exact_answer_before_independent_scoring(self):
        result = run_synthetic_case(self.path, self.outputs, final_text="done")
        self.assertEqual((result["source"], result["execution"]["status"], result["recording"]["outcome"], result["outcome"]),
                         ("synthetic", "completed", "complete", "passed"))
        evidence = load_json(result["association"]["evidencePath"])
        runtime = load_json(result["association"]["runtimeReport"])
        directory = Path(result["association"]["evidencePath"]).parent
        self.assertEqual(evidence["source"], "synthetic")
        self.assertFalse(runtime["modelCalled"])
        self.assertEqual(runtime["preparation"], {"processStarted": False, "processExited": True})
        self.assertFalse((directory / "home").exists())
        self.assertFalse((directory / "prepare.stdout.log").exists())
        self.assertEqual(load_json(directory / "synthetic.json")["finalText"], "done")
        trace, = Path(result["association"]["runDir"]).glob("*.jsonl")
        events = [json.loads(line)["event"] for line in trace.read_text(encoding="utf-8").splitlines()]
        calls = [event["data"] for event in events if event["type"] == "tool/call"]
        self.assertEqual([row["name"] for row in calls],
                         ["eval_rename", "eval_read", "eval_read", "eval_rename", "eval_read"])
        self.assertEqual([json.loads(row["arguments"])["path"] for row in calls],
                         ["draft.txt", "draft.txt", "archive/final.txt", "draft.txt", "archive/final.txt"])
        self.assertEqual(runtime["environmentSnapshot"]["files"],
                         {"archive/final.txt": "评测\r\n", "guard.txt": "keep\n"})
        fresh = evaluate(result["association"]["casePath"], result["association"]["evidencePath"])
        self.assertEqual((fresh["outcome"], fresh["assertions"]), (result["outcome"], result["assertions"]))

    def test_scenario_override_preserves_case_and_exposes_missing_intermediate_evidence(self):
        result = run_synthetic_case(self.path, self.outputs, scenario="rename-timeout-skip-readbacks", final_text="done")
        self.assertEqual(result["caseId"], self.case["caseId"])
        self.assertEqual(load_json(result["association"]["casePath"]), self.case)
        outcomes = [row["outcome"] for row in result["assertions"]["results"]]
        self.assertEqual((outcomes.count("passed"), outcomes.count("insufficient_evidence"), result["outcome"]),
                         (6, 4, "unevaluable"))

    def test_declared_recorder_limits_are_applied_to_the_actual_recording(self):
        self.case["recorder"] = {"maxEventBytes": 8192, "maxPendingBytes": 123456}
        self.path.write_text(json.dumps(self.case), encoding="utf-8")
        result = run_synthetic_case(self.path, self.outputs, final_text="done")
        self.assertEqual((result["recording"]["outcome"], result["outcome"]), ("complete", "passed"))
        run = load_json(Path(result["association"]["runDir"]) / "run.json")
        self.assertEqual({key: run[key] for key in self.case["recorder"]}, self.case["recorder"])
        self.assertEqual(Path(result["association"]["runDir"]).parent,
                         Path(result["association"]["evidencePath"]).parent / "traces")

    def test_declared_small_event_limit_cannot_silently_use_the_defaults_and_pass(self):
        self.case["recorder"] = {"maxEventBytes": 64, "maxPendingBytes": 123456}
        self.path.write_text(json.dumps(self.case), encoding="utf-8")
        result = run_synthetic_case(self.path, self.outputs, final_text="done")
        run = load_json(Path(result["association"]["runDir"]) / "run.json")
        self.assertEqual({key: run[key] for key in self.case["recorder"]}, self.case["recorder"])
        self.assertNotEqual(result["recording"]["outcome"], "complete")
        self.assertEqual((result["source"], result["outcome"]), ("synthetic", "unevaluable"))

    def test_distinct_runs_and_reserved_identity_conflict(self):
        identity = str(uuid4())
        first = run_synthetic_case(self.path, self.outputs, case_run_id=identity, final_text="**done**")
        second = run_synthetic_case(self.path, self.outputs, final_text="done")
        self.assertNotEqual(first["caseRunId"], second["caseRunId"])
        self.assertNotEqual(first["association"]["runId"], second["association"]["runId"])
        self.assertEqual(first["outcome"], "passed")
        exact = next(row for row in first["assertions"]["results"] if row["id"] == "answer-exact")
        self.assertEqual((exact["actual"], exact["outcome"]), ("**done**", "failed"))
        before = Path(first["association"]["evidencePath"]).read_bytes()
        with self.assertRaises(FileExistsError):
            run_synthetic_case(self.path, self.outputs, case_run_id=identity)
        self.assertEqual(Path(first["association"]["evidencePath"]).read_bytes(), before)

    def test_invalid_script_options_rejected_before_creating_output(self):
        for options in ({"scenario": "unknown"}, {"scenario": []}, {"final_text": 7}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                run_synthetic_case(self.path, self.outputs, **options)
            self.assertFalse(self.outputs.exists())
        ordinary = load_json(ROOT / "fixtures/evaluation/live-read.case.json")
        self.path.write_text(json.dumps(ordinary), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "stateful"):
            run_synthetic_case(self.path, self.outputs, scenario="rename-confirmation")
        self.assertFalse(self.outputs.exists())

    def test_unreadable_input_leaves_no_execution_output(self):
        with self.assertRaises(OSError):
            run_synthetic_case(self.directory / "missing.json", self.outputs)
        self.assertFalse(self.outputs.exists())

    def test_missing_node_preserves_synthetic_startup_failure_for_offline_inspection(self):
        # Use a separate Python process with no executable search path: Popen really fails.
        script = ("import json,sys; from dsh_eval.runner import run_synthetic_case; "
                  "print(json.dumps(run_synthetic_case(sys.argv[1], sys.argv[2], final_text='done')))")
        completed = subprocess.run([sys.executable, "-c", script, str(self.path), str(self.outputs)],
                                   cwd=ROOT, env={**os.environ, "PATH": str(self.directory)},
                                   capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual((result["source"], result["execution"]["status"], result["outcome"]),
                         ("synthetic", "runtime_error", "unevaluable"))
        self.assertIsNone(result["association"]["runId"])
        runtime = load_json(result["association"]["runtimeReport"])
        self.assertEqual(runtime["error"]["type"], "FileNotFoundError")
        self.assertFalse(runtime["adapterProcessStarted"])
        self.assertFalse(runtime["modelCalled"])


if __name__ == "__main__":
    unittest.main()
