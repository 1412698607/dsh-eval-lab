import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from dsh_eval.environment import StatefulEnvironment
from dsh_eval.evaluate import evaluate
from dsh_eval.experiment import run_experiment
from dsh_eval.experiment_resume import plan_experiment_resume, resume_experiment
from dsh_eval.formats import load_json, validate_case
from dsh_eval.report import generate_report
from dsh_eval.runner import ROOT, run_case


def case(name="edit-delete"):
    return load_json(ROOT / "fixtures/evaluation" / (name + ".case.json"))


class MutationEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.case = case()
        self.case["environment"]["stateful"]["tools"] += ["eval_write", "eval_list"]
        self.env = StatefulEnvironment(self.case["environment"], "case", {"toolTimeoutMs": 100})
        self.env.bind("session")

    def request(self, operation, path="settings.txt", request_id=None, **arguments):
        return {"type": "tool-request", "bridgeVersion": 1, "requestId": request_id or str(uuid4()),
                "caseRunId": "case", "sessionId": "session", "operation": operation,
                "arguments": {"path": path, **arguments}}

    def test_edit_preserves_exact_surrounding_text_and_supports_empty_replacement(self):
        for old, new, expected in (("draft", "ready", "mode=ready\r\nowner=评测\r\n"),
                                   ("owner=评测\r\n", "", "mode=draft\r\n"),
                                   ("\r\nowner", "\nowner", "mode=draft\nowner=评测\r\n"),
                                   ("draft", "draft", "mode=draft\r\nowner=评测\r\n")):
            with self.subTest(old=old, new=new):
                self.env.files["settings.txt"] = "mode=draft\r\nowner=评测\r\n"
                response = self.env.handle(self.request("edit", oldText=old, newText=new))
                self.assertEqual(response["text"], "EDITED: settings.txt")
                self.assertEqual(self.env.files["settings.txt"], expected)
                self.assertEqual(self.env.files["guard.txt"], "keep\n")
        self.assertEqual(self.case["environment"]["files"]["settings.txt"], "mode=draft\nowner=评测\n")

    def test_missing_empty_repeated_and_overlapping_matches_do_not_mutate(self):
        for content, old, error in (("draft", "DRAFT", "TEXT_NOT_FOUND"), ("draft", "", "EMPTY_EDIT_TARGET"),
                                    ("aa--aa", "aa", "AMBIGUOUS_MATCH"), ("aaa", "aa", "AMBIGUOUS_MATCH")):
            with self.subTest(content=content, old=old):
                self.env.files["settings.txt"] = content
                before = dict(self.env.files)
                response = self.env.handle(self.request("edit", oldText=old, newText="replacement"))
                self.assertTrue(response["isError"])
                self.assertEqual(response["text"], error + ": settings.txt")
                self.assertEqual(self.env.files, before)

    def test_delete_removes_one_file_and_never_recurses(self):
        self.env.files["nested/file.txt"] = "nested"
        for path in ("nested", ".", "missing.txt"):
            before = dict(self.env.files)
            response = self.env.handle(self.request("delete", path))
            self.assertEqual(response["text"], "NOT_FOUND: " + path)
            self.assertEqual(self.env.files, before)
        self.assertEqual(self.env.handle(self.request("delete", "obsolete.txt"))["text"], "DELETED: obsolete.txt")
        self.assertNotIn("obsolete.txt", self.env.files)
        self.assertIn("nested/file.txt", self.env.files)
        self.assertEqual(self.env.handle(self.request("read", "obsolete.txt"))["text"], "NOT_FOUND: obsolete.txt")
        listed = self.env.handle(self.request("list", "."))["text"].splitlines()
        self.assertEqual(listed, sorted(self.env.files))

    def test_invalid_paths_and_missing_edit_file_leave_state_unchanged(self):
        before = dict(self.env.files)
        for operation in ("delete", "edit"):
            extra = {"oldText": "draft", "newText": "ready"} if operation == "edit" else {}
            for path in ("../settings.txt", "C:/settings.txt", "/settings.txt", "a\\b", "a/./b", ""):
                response = self.env.handle(self.request(operation, path, **extra))
                self.assertTrue(response["isError"])
                self.assertIn("INVALID_PATH", response["text"])
                self.assertEqual(self.env.files, before)
        response = self.env.handle(self.request("edit", "missing.txt", oldText="a", newText="b"))
        self.assertEqual(response["text"], "NOT_FOUND: missing.txt")
        self.assertEqual(self.env.files, before)

    def test_duplicate_mutations_are_cached_without_touching_recreated_files(self):
        request = self.request("edit", oldText="draft", newText="draft-draft")
        response = self.env.handle(request)
        self.assertEqual(self.env.handle(request), response)
        self.assertEqual(self.env.files["settings.txt"], "mode=draft-draft\nowner=评测\n")
        with self.assertRaises(ValueError):
            self.env.handle({**request, "arguments": {**request["arguments"], "newText": "other"}})
        request = self.request("delete", "obsolete.txt")
        response = self.env.handle(request)
        self.env.handle(self.request("write", "obsolete.txt", content="new incarnation"))
        self.assertEqual(self.env.handle(request), response)
        self.assertEqual(self.env.files["obsolete.txt"], "new incarnation")
        self.env.handle(self.request("delete", "obsolete.txt"))
        self.assertNotIn("obsolete.txt", self.env.files)

    def test_mutations_do_not_consume_read_faults_and_environments_reset(self):
        self.env.failures["settings.txt"] = 1
        self.env.handle(self.request("edit", oldText="draft", newText="ready"))
        self.assertEqual(self.env.failures["settings.txt"], 1)
        self.env.handle(self.request("delete"))
        self.env.handle(self.request("write", content="replacement"))
        self.assertIn("TEMPORARY_READ_FAILURE", self.env.handle(self.request("read"))["text"])
        fresh = StatefulEnvironment(self.case["environment"], "next")
        self.assertEqual(fresh.files, self.case["environment"]["files"])

    def test_timeout_never_mutates_later_and_new_request_can_retry(self):
        for operation, extra in (("delete", {}), ("edit", {"oldText": "draft", "newText": "ready"})):
            with self.subTest(operation=operation):
                self.setUp()
                self.env.delays = {"eval_" + operation: [200, 0]}
                before = dict(self.env.files)
                request = self.request(operation, **extra)
                self.assertEqual(self.env.submit(request, 0), [])
                self.assertIn("TOOL_TIMEOUT", self.env.poll(.1)[0]["text"])
                self.assertEqual(self.env.poll(1), [])
                self.assertEqual(self.env.files, before)
                self.assertIn("TOOL_TIMEOUT", self.env.submit(request, 1)[0]["text"])
                self.assertFalse(self.env.submit(self.request(operation, **extra), 1)[0]["isError"])
                self.assertNotEqual(self.env.files, before)

    def test_cancel_removes_pending_delete_and_edit(self):
        for operation, extra in (("delete", {}), ("edit", {"oldText": "draft", "newText": "ready"})):
            with self.subTest(operation=operation):
                self.env.delays["eval_" + operation] = [200]
                request = self.request(operation, **extra)
                before = dict(self.env.files)
                self.env.submit(request, 0)
                self.env.cancel({key: ("tool-cancel" if key == "type" else value) for key, value in request.items()
                                 if key not in ("operation", "arguments")})
                self.assertEqual(self.env.poll(10), [])
                self.assertEqual(self.env.files, before)
                self.assertIn("TOOL_CANCELLED", self.env.submit(request, 10)[0]["text"])

    def test_delayed_edit_matches_current_state_at_commit(self):
        self.env.delays["eval_edit"] = [20]
        request = self.request("edit", oldText="draft", newText="ready")
        self.env.submit(request, 0)
        self.env.handle(self.request("write", content="draft draft"))
        self.assertIn("AMBIGUOUS_MATCH", self.env.poll(.02)[0]["text"])
        self.assertEqual(self.env.files["settings.txt"], "draft draft")

    def test_opt_in_argument_validation_and_public_case_budgets(self):
        for name in ("edit-delete", "edit-delete-errors", "edit-delete-timeout"):
            validate_case(case(name))
        for operation in ("edit", "delete"):
            request = self.request(operation, **({"oldText": "draft", "newText": "ready"} if operation == "edit" else {}))
            original = dict(self.env.files)
            for extra in ({"recursive": True}, {"newText": None} if operation == "edit" else {"content": "x"}):
                with self.assertRaises(ValueError):
                    self.env.handle({**request, "arguments": {**request["arguments"], **extra}})
                self.assertEqual(self.env.files, original)
            old = StatefulEnvironment({"files": original, "stateful": {"transientReadFailures": {}}}, "case")
            old.bind("session")
            with self.assertRaises(ValueError):
                old.handle(request)


class MutationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dsh-mutate-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for target, options in (("dsh_eval.runner._prepare", {}), ("dsh_eval.output_paths.check_output_root", {}),
                                ("dsh_eval.runner.ADAPTER", {"new": ROOT / "scripts/fixtures/mutation-adapter.js"})):
            mocked = patch(target, **options)
            mocked.start()
            self.addCleanup(mocked.stop)

    def save(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def prepare(self, name):
        task = case(name)
        task["configRef"].update(provider="synthetic", model="none")
        if "toolDelaysMs" in task["environment"]["stateful"]:
            task["environment"]["stateful"]["toolDelaysMs"] = {tool: [200, 0] for tool in ("eval_edit", "eval_delete")}
            task["budget"]["toolTimeoutsMs"] = {tool: 100 for tool in ("eval_edit", "eval_delete")}
        path = self.root / (name + ".case.json")
        self.save(path, task)
        return path, task

    def execute(self, *args, **kwargs):
        result = run_case(*args, **kwargs)
        evidence_path = Path(result["association"]["evidencePath"])
        evidence = load_json(evidence_path)
        evidence["source"] = "synthetic"
        self.save(evidence_path, evidence)
        result = evaluate(result["association"]["casePath"], evidence_path)
        self.save(evidence_path.parent / "evaluation.json", result)
        return result

    def test_three_public_cases_record_real_tool_results_and_final_state(self):
        for name in ("edit-delete", "edit-delete-errors", "edit-delete-timeout"):
            with self.subTest(name=name):
                path, task = self.prepare(name)
                result = self.execute(path, self.root / "runs")
                self.assertEqual((result["outcome"], result["recording"]["outcome"], result["source"]),
                                 ("passed", "complete", "synthetic"), result)
                state = next(row for row in result["assertions"]["results"] if row["type"] == "environment_files")
                self.assertEqual(state["actual"], next(row for row in task["assertions"] if row["id"] == "state")["equals"])

    def test_correct_answer_cannot_hide_wrong_edit_or_retained_deleted_file(self):
        path, task = self.prepare("edit-delete")
        result = self.execute(path, self.root / "runs")
        state = next(row for row in task["assertions"] if row["id"] == "state")
        original = copy.deepcopy(state["equals"])
        for changes in ({"obsolete.txt": "remove\n"}, {"settings.txt": "mode=draft\nowner=评测\n"}, {"guard.txt": "changed"}):
            state["equals"] = {**original, **changes}
            self.save(path, task)
            fresh = evaluate(path, result["association"]["evidencePath"])
            self.assertEqual(fresh["outcome"], "failed")
            self.assertEqual(next(row for row in fresh["assertions"]["results"] if row["id"] == "answer")["outcome"], "passed")

    def test_error_presentation_keeps_host_prefix_and_rejects_old_exact_expectations(self):
        for name in ("edit-delete-errors", "edit-delete-timeout"):
            with self.subTest(name=name):
                path, task = self.prepare(name)
                result = self.execute(path, self.root / "runs")
                self.assertEqual(result["outcome"], "passed", result)
                trace = next(Path(result["association"]["runDir"]).glob("*.jsonl"))
                messages = [json.loads(line)["event"].get("data", {}).get("message", {})
                            for line in trace.read_text(encoding="utf-8").splitlines()]
                errors = [message["content"][0]["text"] for message in messages if message.get("isError") is True]
                expected = [row["result"]["textEquals"] for row in task["assertions"]
                            if row["type"] == "tool_result" and row["result"]["isError"]]
                self.assertEqual(errors, expected)
                self.assertTrue(all(text.startswith("Error: ") for text in errors))
                for row in task["assertions"]:
                    if row["type"] == "tool_result" and row["result"]["isError"]:
                        row["result"]["textEquals"] = row["result"]["textEquals"].removeprefix("Error: ")
                self.save(path, task)
                fresh = evaluate(path, result["association"]["evidencePath"])
                self.assertEqual(fresh["outcome"], "failed")
                self.assertEqual(next(row for row in fresh["assertions"]["results"] if row["id"] == "state")["outcome"], "passed")

    def test_mutations_recheck_after_experiment_continuation(self):
        path, task = self.prepare("edit-delete-timeout")
        manifest = {"experimentFormatVersion": 1, "experimentName": "mutation-resume", "repetitions": 2,
                    "failurePolicy": "continue", "cases": [{"entryId": "mutation", "casePath": path.name}],
                    "configurations": [{"configurationId": "synthetic", "configRef": task["configRef"]}]}
        manifest_path = self.root / "experiment.json"
        self.save(manifest_path, manifest)
        with patch("dsh_eval.batch.run_case", side_effect=self.execute):
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
