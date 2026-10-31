import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dsh_eval.__main__ import main
from dsh_eval.batch import _checkpoint, run_batch
from dsh_eval.evaluate import evaluate
from dsh_eval.formats import load_json, validate_batch
from dsh_eval.runner import ROOT, run_case


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dsh-batch-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.outputs = self.directory / "outputs"
        self.case = load_json(ROOT / "fixtures/evaluation/retry-read.case.json")
        self.case["configRef"].update(provider="synthetic", model="none")
        self.save("retry.json", self.case)
        self.manifest = {"batchFormatVersion": 1, "batchName": "test", "failurePolicy": "continue", "cases": [
            {"entryId": "first", "casePath": "retry.json"}, {"entryId": "reset", "casePath": "retry.json"}]}
        self.path = self.directory / "batch.json"
        self.preparation = patch("dsh_eval.runner._prepare")
        self.adapter = patch("dsh_eval.runner.ADAPTER", ROOT / "scripts/fixtures/batch-adapter.js")
        self.preparation.start()
        output_paths = patch("dsh_eval.output_paths.check_output_root")
        output_paths.start()
        self.addCleanup(output_paths.stop)
        self.adapter.start()
        self.addCleanup(self.preparation.stop)
        self.addCleanup(self.adapter.stop)

    def save(self, name, value):
        path = self.directory / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def run_batch(self, **options):
        self.save("batch.json", self.manifest)
        return run_batch(self.path, self.outputs, **options)

    def test_batch_format_rejects_ambiguous_inputs_but_allows_repeated_case(self):
        self.assertIs(validate_batch(self.manifest), self.manifest)
        for change in ({"batchFormatVersion": True}, {"batchFormatVersion": 2}, {"failurePolicy": "guess"},
                       {"cases": []}, {"typo": True}, {"cases": [self.manifest["cases"][0]] * 2}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_batch({**self.manifest, **change})
        for path in ("/file.json", "C:/file.json", "a\\b.json", "a//b.json", "./file.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_batch({**self.manifest, "cases": [{"entryId": "one", "casePath": path}]})

    def test_all_inputs_are_preflighted_before_any_execution(self):
        invalid = copy.deepcopy(self.case)
        invalid["configRef"]["profile"] = "web"
        self.save("bad.json", invalid)
        self.manifest["cases"][1]["casePath"] = "bad.json"
        with patch("dsh_eval.batch.run_case") as runner, self.assertRaises(ValueError):
            self.run_batch()
        runner.assert_not_called()
        self.assertFalse(self.outputs.exists())

    def test_repeated_case_resets_state_and_binds_saved_evidence(self):
        report = self.run_batch()
        self.assertEqual((report["status"], report["outcome"]), ("completed", "passed"))
        base = Path(report["batchDirectory"])
        self.assertEqual(load_json(base / "batch-result.json"), report)
        self.assertEqual(len({row["caseRunId"] for row in report["entries"]}), 2)
        self.assertEqual(len({row["runId"] for row in report["entries"]}), 2)
        self.assertEqual(len({row["sessionId"] for row in report["entries"]}), 2)
        for row in report["entries"]:
            result = load_json(base / row["evaluationPath"])
            evidence = load_json(base / row["evidencePath"])
            self.assertEqual(result["batchId"], report["batchId"])
            self.assertEqual(evidence["batchId"], report["batchId"])
            self.assertEqual(evidence["caseRunId"], row["caseRunId"])
            self.assertEqual(row["configuration"], self.case["configRef"])
            self.assertTrue((base / row["caseDirectory"] / "home/synthetic-session.txt").exists())
            self.assertEqual(list((base / row["caseDirectory"] / "workspace").iterdir()), [])
            self.assertEqual(evaluate(result["association"]["casePath"], base / row["evidencePath"])["outcome"], "passed")
        # The saved manifest is runnable and creates another batch, without changing the old result.
        original = (base / "batch-result.json").read_bytes()
        rerun = run_batch(base / "batch.json", self.outputs)
        self.assertNotEqual(rerun["batchId"], report["batchId"])
        self.assertEqual(rerun["outcome"], "passed")
        self.assertEqual((base / "batch-result.json").read_bytes(), original)

    def test_snapshots_freeze_later_inputs_and_keep_configurations_separate(self):
        other = copy.deepcopy(self.case)
        other["configRef"]["model"] = "second-model"
        self.save("other.json", other)
        self.manifest["cases"][1]["casePath"] = "other.json"
        def mutate_source(*args, **kwargs):
            self.save("other.json", {"invalid": "edited after preflight"})
            return run_case(*args, **kwargs)
        with patch("dsh_eval.batch.run_case", side_effect=mutate_source):
            report = self.run_batch()
        self.assertEqual(report["outcome"], "passed")
        self.assertEqual([row["configuration"]["model"] for row in report["entries"]], ["none", "second-model"])

    def test_failure_policy_continues_or_skips_without_inventing_identities(self):
        wrong = copy.deepcopy(self.case)
        next(item for item in wrong["assertions"] if item["type"] == "final_text")["equals"] = "wrong-answer"
        self.save("wrong.json", wrong)
        self.manifest["cases"][0]["casePath"] = "wrong.json"
        for policy, expected in (("continue", ["finished", "finished"]), ("stop", ["finished", "skipped"])):
            with self.subTest(policy=policy):
                self.manifest["failurePolicy"] = policy
                report = self.run_batch()
                self.assertEqual(report["outcome"], "failed")
                self.assertEqual(report["entries"][0]["outcome"], "failed")
                self.assertEqual([row["status"] for row in report["entries"]], expected)
                if policy == "stop":
                    self.assertIsNone(report["entries"][1]["caseRunId"])
                    self.assertIsNone(report["entries"][1]["runId"])
                    self.assertIsNone(report["entries"][1]["outcome"])

    def test_controlled_cancellation_follows_policy_and_preserves_case_result(self):
        cancelled = copy.deepcopy(self.case)
        cancelled["input"] = "WAIT_FOR_CANCEL"
        self.save("cancel.json", cancelled)
        self.manifest["cases"][0]["casePath"] = "cancel.json"
        for policy in ("continue", "stop"):
            with self.subTest(policy=policy):
                self.manifest["failurePolicy"] = policy
                report = self.run_batch(cancel_after_stream=True)
                self.assertEqual(report["entries"][0]["executionStatus"], "cancelled")
                self.assertEqual(report["entries"][0]["assertionOutcome"], "not_run")
                self.assertEqual(report["outcome"], "unevaluable")
                self.assertEqual(report["entries"][1]["status"], "finished" if policy == "continue" else "skipped")

    def test_runtime_startup_errors_can_continue_when_no_process_remains(self):
        with patch("dsh_eval.runner._prepare", side_effect=ValueError("no host started")):
            report = self.run_batch()
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["outcome"], "unevaluable")
        self.assertEqual([row["executionStatus"] for row in report["entries"]], ["runtime_error"] * 2)
        self.assertTrue(all(row["runId"] is None for row in report["entries"]))

    def test_adapter_launch_failure_follows_policy_and_preserves_missing_facts(self):
        popen = subprocess.Popen
        for policy in ("continue", "stop"):
            with self.subTest(policy=policy):
                self.manifest["failurePolicy"] = policy
                failed = False
                def fail_first_launch(*args, **kwargs):
                    nonlocal failed
                    if not failed:
                        failed = True
                        raise OSError("Adapter process was not created")
                    return popen(*args, **kwargs)
                with patch("dsh_eval.runner.subprocess.Popen", side_effect=fail_first_launch):
                    report = self.run_batch()
                self.assertEqual(report["status"], "completed" if policy == "continue" else "stopped")
                self.assertEqual(report["stopReason"], None if policy == "continue" else "failure_policy")
                self.assertEqual(report["outcome"], "unevaluable")
                base = Path(report["batchDirectory"])
                first, following = report["entries"]
                self.assertEqual(first["executionStatus"], "runtime_error")
                self.assertEqual(first["assertionOutcome"], "not_run")
                for key in ("runId", "sessionId", "configuration"):
                    self.assertIsNone(first[key])
                runtime = load_json(base / first["runtimeReport"])
                self.assertIs(runtime["adapterProcessStarted"], False)
                self.assertEqual((runtime["stage"], runtime["host"], runtime["supervisor"]), ("run", {}, {}))
                self.assertEqual(runtime["error"]["type"], "OSError")
                self.assertEqual(evaluate(base / first["caseDirectory"] / "case.json", base / first["evidencePath"])["outcome"], "unevaluable")
                if policy == "continue":
                    self.assertEqual(following["outcome"], "passed")
                    self.assertIs(load_json(base / following["runtimeReport"])["adapterProcessStarted"], True)
                else:
                    self.assertEqual(following["status"], "skipped")
                    self.assertIsNone(following["caseRunId"])

    def test_unknown_adapter_launch_cannot_confirm_empty_supervision(self):
        for missing in (True, False):
            with self.subTest(missing=missing):
                def forget_launch(*args, **kwargs):
                    result = run_case(*args, **kwargs)
                    runtime_path = Path(result["association"]["runtimeReport"])
                    runtime = load_json(runtime_path)
                    if missing:
                        runtime.pop("adapterProcessStarted", None)
                    else:
                        runtime["adapterProcessStarted"] = None
                    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
                    return result
                with patch("dsh_eval.runner.subprocess.Popen", side_effect=OSError("No adapter created")), \
                        patch("dsh_eval.batch.run_case", side_effect=forget_launch):
                    report = self.run_batch()
                self.assertEqual((report["status"], report["stopReason"]), ("error", "cleanup_unconfirmed"))
                self.assertEqual(report["entries"][0]["executionStatus"], "runtime_error")
                self.assertEqual(report["entries"][1]["status"], "skipped")

    def test_interrupt_during_adapter_launch_stops_batch_with_unknown_start(self):
        with patch("dsh_eval.runner.subprocess.Popen", side_effect=KeyboardInterrupt) as launch:
            report = self.run_batch()
        self.assertEqual(launch.call_count, 1)
        self.assertEqual((report["status"], report["stopReason"]), ("interrupted", "user_interrupt"))
        runtime = load_json(Path(report["batchDirectory"]) / report["entries"][0]["runtimeReport"])
        self.assertIsNone(runtime["adapterProcessStarted"])
        self.assertTrue(runtime["userInterrupted"])
        self.assertEqual(report["entries"][1]["status"], "skipped")
        self.assertIsNone(report["entries"][1]["caseRunId"])

    def test_timeout_follows_policy_without_becoming_task_failure(self):
        timed = copy.deepcopy(self.case)
        timed["input"] = "WAIT_FOR_TIMEOUT"
        timed["budget"]["timeoutSeconds"] = 1
        self.save("timeout.json", timed)
        self.manifest["cases"][0]["casePath"] = "timeout.json"
        for policy in ("continue", "stop"):
            with self.subTest(policy=policy):
                self.manifest["failurePolicy"] = policy
                report = self.run_batch()
                self.assertEqual(report["entries"][0]["executionStatus"], "timed_out")
                self.assertEqual(report["entries"][0]["outcome"], "unevaluable")
                self.assertEqual(report["entries"][1]["status"], "finished" if policy == "continue" else "skipped")

    def test_interrupt_handled_inside_runner_still_stops_batch(self):
        with patch("dsh_eval.runner._prepare", side_effect=KeyboardInterrupt):
            report = self.run_batch()
        self.assertEqual(report["status"], "interrupted")
        self.assertEqual(report["entries"][0]["status"], "finished")
        self.assertEqual(report["entries"][1]["status"], "skipped")

    def test_wrong_batch_association_is_rejected_before_continuing(self):
        def wrong_batch(*args, **kwargs):
            result = run_case(*args, **kwargs)
            result["batchId"] = "wrong-batch"
            saved = Path(result["association"]["evidencePath"]).with_name("evaluation.json")
            saved.write_text(json.dumps(result), encoding="utf-8")
            return result
        with patch("dsh_eval.batch.run_case", side_effect=wrong_batch):
            report = self.run_batch()
        self.assertEqual(report["stopReason"], "runner_error")
        self.assertIn("association", report["entries"][0]["error"]["message"])
        self.assertEqual(report["entries"][1]["status"], "skipped")

    def test_unconfirmed_cleanup_stops_even_under_continue_policy(self):
        def unsafe_cleanup(*args, **kwargs):
            result = run_case(*args, **kwargs)
            runtime_path = Path(result["association"]["runtimeReport"])
            runtime = load_json(runtime_path)
            runtime["supervisor"]["stdinWriterStopped"] = False
            runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
            return result
        with patch("dsh_eval.batch.run_case", side_effect=unsafe_cleanup):
            report = self.run_batch()
        self.assertEqual((report["status"], report["stopReason"]), ("error", "cleanup_unconfirmed"))
        self.assertEqual(report["entries"][0]["outcome"], "passed")
        self.assertEqual(report["outcome"], "unevaluable")
        self.assertEqual(report["entries"][1]["status"], "skipped")

    def test_user_interrupt_stops_batch_and_keeps_previous_results(self):
        calls = 0
        def interrupt_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt
            return run_case(*args, **kwargs)
        with patch("dsh_eval.batch.run_case", side_effect=interrupt_second):
            report = self.run_batch()
        self.assertEqual(report["status"], "interrupted")
        self.assertEqual(report["outcome"], "unevaluable")
        self.assertEqual(report["entries"][0]["outcome"], "passed")
        self.assertEqual(report["entries"][1]["error"]["type"], "KeyboardInterrupt")
        self.assertTrue((Path(report["batchDirectory"]) / report["entries"][0]["evaluationPath"]).exists())

    def test_runner_error_cannot_launch_remaining_cases(self):
        with patch("dsh_eval.batch.run_case", side_effect=OSError("output failure")) as runner:
            report = self.run_batch()
        self.assertEqual(runner.call_count, 1)
        self.assertEqual((report["status"], report["outcome"]), ("error", "unevaluable"))
        self.assertEqual(report["entries"][0]["status"], "error")
        self.assertIsNone(report["entries"][0]["evaluationPath"])
        self.assertEqual(report["entries"][1]["status"], "skipped")

    def test_checkpoint_failure_stops_before_another_case_is_launched(self):
        def checkpoint(directory, report):
            if report["entries"][1]["status"] == "running":
                raise OSError("checkpoint unavailable")
            _checkpoint(directory, report)
        with patch("dsh_eval.batch._checkpoint", side_effect=checkpoint), self.assertRaises(OSError):
            self.run_batch()
        report = load_json(next(self.outputs.glob("*/batch-result.json")))
        self.assertEqual(report["entries"][0]["outcome"], "passed")
        self.assertEqual(report["entries"][1]["status"], "pending")
        self.assertEqual(len(list(self.outputs.glob("*/cases/*"))), 1)

    def test_cli_requires_explicit_run_and_reports_batch_exit_codes(self):
        self.save("batch.json", self.manifest)
        with redirect_stderr(io.StringIO()):
            for args in (["--batch", str(self.path)], ["--case", "x", "--batch", str(self.path)],
                         ["--batch", str(self.path), "--run", "--evidence", "x"]):
                with self.subTest(args=args), self.assertRaises(SystemExit) as exited:
                    main(args)
                self.assertEqual(exited.exception.code, 2)
        for expected, change in ((0, None), (1, "answer"), (2, "runtime")):
            with self.subTest(expected=expected), redirect_stdout(io.StringIO()) as stdout:
                if change == "answer":
                    next(item for item in self.case["assertions"] if item["type"] == "final_text")["equals"] = "wrong"
                    self.save("retry.json", self.case)
                if change == "runtime":
                    with patch("dsh_eval.runner._prepare", side_effect=ValueError("no host")):
                        code = main(["--batch", str(self.path), "--run", "--runs-root", str(self.outputs)])
                else:
                    code = main(["--batch", str(self.path), "--run", "--runs-root", str(self.outputs)])
                self.assertEqual(code, expected)
                self.assertEqual(json.loads(stdout.getvalue())["batchResultFormatVersion"], 1)


if __name__ == "__main__":
    unittest.main()
