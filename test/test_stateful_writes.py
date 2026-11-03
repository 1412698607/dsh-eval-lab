import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dsh_eval.environment import StatefulEnvironment, snapshot_digest
from dsh_eval.evaluate import evaluate
from dsh_eval.formats import load_json, validate_case
from dsh_eval.runner import ROOT, run_case, supervise, _process_options
from dsh_eval.experiment import run_experiment
from dsh_eval.experiment_resume import plan_experiment_resume, resume_experiment
from dsh_eval.report import generate_report


def case():
    return load_json(ROOT / "fixtures/evaluation/write-retry.case.json")


class WriteEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.case = case()
        self.env = StatefulEnvironment(self.case["environment"], "case", self.case["budget"])
        self.env.bind("session")

    def request(self, name="one", operation="write", path="result.txt", content="done\n"):
        return {"type": "tool-request", "bridgeVersion": 1, "requestId": name, "caseRunId": "case",
                "sessionId": "session", "operation": operation,
                "arguments": {"path": path, **({"content": content} if operation == "write" else {})}}

    def test_write_creates_replaces_and_preserves_other_files(self):
        self.env.handle(self.request())
        self.env.handle(self.request("two", path="nested/new.txt", content=""))
        self.assertEqual(self.env.files, {"guard.txt": "keep\n", "result.txt": "done\n", "nested/new.txt": ""})
        self.assertEqual(self.case["environment"]["files"]["result.txt"], "old\n")
        other = StatefulEnvironment(self.case["environment"], "next")
        self.assertEqual(other.files["result.txt"], "old\n")

    def test_write_paths_and_collisions_fail_without_mutation(self):
        original = dict(self.env.files)
        for index, path in enumerate(("../bad", "/bad", "C:/bad", "a\\b", ".", "guard.txt/child", "a/./b", "")):
            with self.subTest(path=path):
                self.assertTrue(self.env.handle(self.request(str(index), path=path))["isError"])
                self.assertEqual(self.env.files, original)
        self.env.handle(self.request("new", path="a/b"))
        self.assertIn("PATH_COLLISION", self.env.handle(self.request("parent", path="a"))["text"])

    def test_timeout_has_no_late_mutation_and_retry_can_succeed(self):
        request = self.request()
        self.assertEqual(self.env.submit(request, 10), [])
        self.assertEqual(self.env.submit(request, 10.5), [])
        response = self.env.poll(11)[0]
        self.assertIn("TOOL_TIMEOUT", response["text"])
        self.assertEqual(self.env.files["result.txt"], "old\n")
        self.assertEqual(self.env.poll(20), [])
        self.assertEqual(self.env.submit(request, 20), [response])
        self.assertFalse(self.env.submit(self.request("retry"), 20)[0]["isError"])
        self.assertEqual(self.env.files["result.txt"], "done\n")
        self.assertEqual(self.env.attempts["eval_write"], 2)

    def test_write_and_case_validation_agree_on_file_paths(self):
        for path in ("   ", "bad\0name", "a//b", "a/../b"):
            with self.subTest(path=path):
                before = dict(self.env.files)
                response = self.env.handle(self.request(name="write-" + path, path=path))
                self.assertEqual(response["text"], "INVALID_PATH: " + path)
                self.assertEqual(self.env.files, before)
                for files in (self.case["environment"]["files"], self.case["assertions"][4]["equals"]):
                    files[path] = "value"
                    with self.assertRaises(ValueError):
                        validate_case(self.case)
                    del files[path]
        path = "子目录/ file name .txt"
        self.assertFalse(self.env.handle(self.request(path=path))["isError"])
        self.case["environment"]["files"][path] = "done\n"
        self.case["assertions"][4]["equals"][path] = "done\n"
        validate_case(self.case)

    def test_default_override_deadline_and_boundary(self):
        self.env.delays = {"eval_read": [40], "eval_write": [40]}
        self.env.budget = {"toolTimeoutMs": 30, "toolTimeoutsMs": {"eval_write": 80}}
        self.env.submit(self.request("read", "read"), 0)
        self.env.submit(self.request(), 0)
        self.assertIn("TOOL_TIMEOUT", self.env.poll(.03)[0]["text"])
        self.assertFalse(self.env.poll(.04)[0]["isError"])
        self.env.delays = {"eval_write": [80]}
        self.env.attempts.clear()
        self.env.submit(self.request("equal", content="late"), 1)
        self.assertIn("TOOL_TIMEOUT", self.env.poll(1.08)[0]["text"])
        self.assertEqual(self.env.files["result.txt"], "done\n")

    def test_cancelled_or_conflicting_pending_work_cannot_commit(self):
        request = self.request()
        self.env.submit(request, 0)
        with self.assertRaises(ValueError):
            self.env.submit(self.request(content="conflict"), .1)
        cancel = {key: value for key, value in request.items() if key not in ("operation", "arguments")}
        cancel["type"] = "tool-cancel"
        with self.assertRaises(ValueError):
            self.env.cancel({**cancel, "sessionId": "other"})
        self.env.cancel(cancel)
        self.assertEqual(self.env.poll(10), [])
        self.assertEqual(self.env.files["result.txt"], "old\n")
        self.assertFalse(self.env.snapshot(self.case, "run", True)["complete"])
        self.assertIn("TOOL_CANCELLED", self.env.submit(request, 11)[0]["text"])

    def test_formats_reject_invalid_tools_budgets_and_state_assertions(self):
        validate_case(self.case)
        changes = [lambda value: value["environment"]["stateful"].update(tools=["eval_shell"]),
                   lambda value: value["environment"]["stateful"].update(tools=["eval_read", "eval_read"]),
                   lambda value: value["environment"]["stateful"].update(toolDelaysMs={"eval_write": [True]}),
                   lambda value: value["budget"].update(toolTimeoutsMs={"eval_list": 1}),
                   lambda value: value["assertions"][4].update(equals={"../bad": "x"})]
        changes += [lambda value, invalid=invalid: value["budget"].update(toolTimeoutMs=invalid)
                    for invalid in (0, -1, True, "10", 1.5, 3600001)]
        for change in changes:
            value = copy.deepcopy(self.case)
            change(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_case(value)
        legacy = load_json(ROOT / "fixtures/evaluation/retry-read.case.json")
        env = StatefulEnvironment(legacy["environment"], "case")
        env.bind("session")
        with self.assertRaises(ValueError):
            env.handle(self.request())

    def test_task_timeout_remains_responsive_and_prevents_delayed_write(self):
        self.env.budget = {"toolTimeoutMs": 5000}
        self.env.delays = {"eval_write": [3000]}
        script = """import sys,json
print(json.dumps({'type':'selection','sessionId':'session'}),flush=True)
print(sys.argv[1],flush=True)
assert json.loads(sys.stdin.readline())['type']=='timeout'
"""
        process = subprocess.Popen([sys.executable, "-u", "-c", script, json.dumps(self.request())],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", **_process_options())
        try:
            result = supervise(process, .2, environment=self.env, event_log=io.StringIO())
            self.assertEqual(result["intervention"], "timeout")
            self.assertEqual(result["adapterExitCode"], 0, process.stderr.read())
            self.assertEqual(self.env.files["result.txt"], "old\n")
            self.assertFalse(self.env.pending)
            self.assertEqual(self.env.poll(1e10), [])
        finally:
            process.stderr.close()

    def test_short_ready_operation_wakes_before_its_tool_deadline(self):
        self.env.budget = {"toolTimeoutMs": 90}
        self.env.delays = {"eval_write": [10]}
        script = """import sys,json
print(json.dumps({'type':'selection','sessionId':'session'}),flush=True)
print(sys.argv[1],flush=True)
response=json.loads(sys.stdin.readline())
assert response['isError'] is False, response
"""
        process = subprocess.Popen([sys.executable, "-u", "-c", script, json.dumps(self.request())],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", **_process_options())
        try:
            result = supervise(process, 5, environment=self.env)
            self.assertEqual(result["adapterExitCode"], 0, process.stderr.read())
            self.assertEqual(self.env.files["result.txt"], "done\n")
        finally:
            process.stderr.close()


class WriteEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dsh-write-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.case = case()
        self.case["configRef"].update(provider="synthetic", model="none")
        self.case["environment"]["stateful"]["toolDelaysMs"]["eval_write"] = [300, 0]
        self.case["budget"]["toolTimeoutsMs"]["eval_write"] = 100
        self.path = self.root / "case.json"
        self.save(self.path, self.case)
        for target, options in (("dsh_eval.runner._prepare", {}), ("dsh_eval.output_paths.check_output_root", {}),
                                ("dsh_eval.runner.ADAPTER", {"new": ROOT / "scripts/fixtures/write-adapter.js"})):
            mocked = patch(target, **options)
            mocked.start()
            self.addCleanup(mocked.stop)
        result = run_case(self.path, self.root / "runs")
        self.assertEqual(result["outcome"], "passed", result)
        self.evidence_path = Path(result["association"]["evidencePath"])
        self.runtime_path = self.evidence_path.parent / "runtime.json"
        self.evidence = load_json(self.evidence_path)
        self.evidence["source"] = "synthetic"
        self.save(self.evidence_path, self.evidence)
        self.runtime = load_json(self.runtime_path)

    def save(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_real_subprocess_recording_and_fresh_evaluation_pass(self):
        result = evaluate(self.path, self.evidence_path)
        self.assertEqual((result["outcome"], result["recording"]["outcome"], result["source"]), ("passed", "complete", "synthetic"))
        self.assertEqual(result["assertions"]["results"][4]["actual"], {"guard.txt": "keep\n", "result.txt": "done\n"})
        self.assertTrue(result["budgetEnforcement"]["toolTimeouts"])

    def test_correct_answer_does_not_hide_wrong_final_state(self):
        self.case["assertions"][4]["equals"]["guard.txt"] = "wrong"
        self.save(self.path, self.case)
        result = evaluate(self.path, self.evidence_path)
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["assertions"]["results"][5]["outcome"], "passed")

    def test_snapshot_tamper_missing_and_identity_rejected(self):
        for update in ({"files": {"result.txt": "forged"}}, {"sessionId": "other"}, {"complete": False},
                       {"environmentSnapshotFormatVersion": True}, {"toolBudget": {}}, {"environmentSha256": "bad"}):
            with self.subTest(update=update):
                runtime = copy.deepcopy(self.runtime)
                runtime["environmentSnapshot"].update(update)
                self.save(self.runtime_path, runtime)
                self.assertEqual(evaluate(self.path, self.evidence_path)["outcome"], "unevaluable")
                if "files" not in update:
                    self.save(self.evidence_path, {**self.evidence, "environmentSnapshotSha256": snapshot_digest(runtime["environmentSnapshot"])})
                    self.assertEqual(evaluate(self.path, self.evidence_path)["outcome"], "unevaluable")
                self.save(self.evidence_path, self.evidence)
        self.save(self.runtime_path, {key: value for key, value in self.runtime.items() if key != "environmentSnapshot"})
        self.assertEqual(evaluate(self.path, self.evidence_path)["outcome"], "unevaluable")

    def test_old_evidence_and_unverified_tool_deadlines_cannot_pass_new_assertions(self):
        self.evidence.pop("environmentSnapshotSha256")
        self.save(self.evidence_path, self.evidence)
        self.assertEqual(evaluate(self.path, self.evidence_path)["outcome"], "unevaluable")
        self.case["budget"] = {"timeoutSeconds": 120}
        self.save(self.path, self.case)
        result = evaluate(self.path, self.evidence_path)
        self.assertEqual(result["assertions"]["results"][4]["outcome"], "insufficient_evidence")

    def test_matching_digest_cannot_validate_an_impossible_file_map(self):
        snapshot = self.runtime["environmentSnapshot"]
        for files in ({"../bad": ""}, {"bad\0name": ""}, {"   ": ""}, {"a": "", "a/b": ""}):
            with self.subTest(files=files):
                snapshot["files"] = files
                self.save(self.runtime_path, self.runtime)
                self.save(self.evidence_path, {**self.evidence, "environmentSnapshotSha256": snapshot_digest(snapshot)})
                result = evaluate(self.path, self.evidence_path)
                self.assertEqual(result["recording"]["outcome"], "complete")
                self.assertEqual(result["outcome"], "unevaluable")
                self.assertEqual(result["assertions"]["outcome"], "insufficient_evidence")

    def test_write_snapshots_survive_experiment_resume_and_report_recheck(self):
        manifest = {"experimentFormatVersion": 1, "experimentName": "write-resume", "repetitions": 2,
                    "failurePolicy": "continue", "cases": [{"entryId": "write", "casePath": "case.json"}],
                    "configurations": [{"configurationId": "synthetic", "configRef": self.case["configRef"]}]}
        manifest_path = self.root / "experiment.json"
        self.save(manifest_path, manifest)

        def synthetic_run(*args, **kwargs):
            result = run_case(*args, **kwargs)
            evidence_path = Path(result["association"]["evidencePath"])
            evidence = load_json(evidence_path)
            evidence["source"] = "synthetic"
            self.save(evidence_path, evidence)
            result = evaluate(result["association"]["casePath"], evidence_path)
            self.save(evidence_path.parent / "evaluation.json", result)
            return result

        with patch("dsh_eval.batch.run_case", side_effect=synthetic_run):
            original = run_experiment(manifest_path, self.root / "experiments", stop_after=1)
            source = Path(original["experimentDirectory"]) / "experiment-result.json"
            plan = plan_experiment_resume(source)
            self.assertTrue(plan["eligibleForResume"], plan)
            resumed = resume_experiment(source, self.root / "resumes", expected_plan_sha256=plan["planFingerprint"]["sha256"])
        result = generate_report(Path(resumed["resumeDirectory"]) / "experiment-resume-result.json", self.root / "reports")
        self.assertEqual(result["summary"]["outcomes"]["passed"], 2)
        self.assertEqual(result["verificationCounts"], {"verified": 2})
        self.assertEqual({row["source"] for row in result["samples"]}, {"synthetic"})


if __name__ == "__main__":
    unittest.main()
