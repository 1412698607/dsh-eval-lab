"""Public rename matrix uses fixed rules before execution; all tests are synthetic."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from dsh_eval.environment import StatefulEnvironment
from dsh_eval.evaluate import evaluate
from dsh_eval.experiment import plan_experiment, run_experiment
from dsh_eval.formats import load_json, validate_case
from dsh_eval.report import generate_report
from dsh_eval.runner import ROOT, run_case


FIXTURES = ROOT / "fixtures/evaluation"
NAMES = ("rename-confirmation", "rename-timeout-retry")


def run_synthetic_case(*args, **kwargs):
    result = run_case(*args, **kwargs)
    evidence_path = Path(result["association"]["evidencePath"])
    evidence = load_json(evidence_path)
    evidence["source"] = "synthetic"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    result = evaluate(result["association"]["casePath"], evidence_path)
    evidence_path.with_name("evaluation.json").write_text(json.dumps(result), encoding="utf-8")
    return result


class RenameConfirmationMatrixTests(unittest.TestCase):
    def test_public_matrix_has_four_predeclared_tasks_and_separate_answer_roles(self):
        path = FIXTURES / "rename-confirmation.experiment.json"
        manifest = load_json(path)
        self.assertEqual((manifest["repetitions"], manifest["failurePolicy"]), (2, "continue"))
        plan = plan_experiment(path, max_samples=4)
        self.assertEqual(plan["counts"], {"cases": 2, "configurations": 1, "samples": 4})
        self.assertFalse(plan["modelCalled"])
        self.assertEqual([row["caseId"] for row in plan["samples"]], [*NAMES, *NAMES])
        for name in NAMES:
            case = validate_case(load_json(FIXTURES / (name + ".case.json")))
            answers = {row["id"]: row for row in case["assertions"] if row["type"] == "final_text"}
            self.assertEqual(answers["answer"], {"id": "answer", "type": "final_text",
                                               "equals": "done", "match": "confirmation_token"})
            self.assertEqual(answers["answer-exact"], {"id": "answer-exact", "type": "final_text",
                                                     "equals": "done", "role": "diagnostic"})
        with self.assertRaisesRegex(ValueError, "exceeds"):
            plan_experiment(path, max_samples=3)

    def test_public_timeout_keeps_source_until_retry(self):
        case = validate_case(load_json(FIXTURES / "rename-timeout-retry.case.json"))
        env = StatefulEnvironment(case["environment"], "case", case["budget"])
        env.bind("session")

        def request(operation, path, **arguments):
            return {"type": "tool-request", "bridgeVersion": 1, "requestId": str(uuid4()),
                    "caseRunId": "case", "sessionId": "session", "operation": operation,
                    "arguments": {"path": path, **arguments}}

        initial = copy.deepcopy(case["environment"]["files"])
        first = request("rename", "draft.txt", destination="archive/final.txt")
        self.assertEqual(env.submit(first, 0), [])
        self.assertEqual(env.poll(1)[0]["text"], "TOOL_TIMEOUT: draft.txt")
        self.assertEqual(env.files, initial)
        self.assertEqual(env.poll(2), [])
        self.assertEqual(env.handle(request("read", "draft.txt"))["text"], "评测\r\n")
        self.assertEqual(env.handle(request("read", "archive/final.txt"))["text"], "NOT_FOUND: archive/final.txt")
        retry = request("rename", "draft.txt", destination="archive/final.txt")
        self.assertFalse(env.submit(retry, 2)[0]["isError"])
        self.assertEqual(env.files, {"archive/final.txt": "评测\r\n", "guard.txt": "keep\n"})

    def test_four_synthetic_tasks_keep_exact_answer_failures_as_diagnostics(self):
        with tempfile.TemporaryDirectory(prefix="dsh-rename-matrix-") as temp:
            root = Path(temp)
            manifest = load_json(FIXTURES / "rename-confirmation.experiment.json")
            manifest["configurations"][0]["configRef"].update(provider="synthetic", model="none")
            for name in NAMES:
                case = load_json(FIXTURES / (name + ".case.json"))
                case["configRef"].update(provider="synthetic", model="none")
                (root / (name + ".case.json")).write_text(json.dumps(case), encoding="utf-8")
            path = root / "experiment.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            plan = plan_experiment(path, max_samples=4)

            def execute(*args, **kwargs):
                result = run_synthetic_case(*args, **kwargs)
                rows = {row["id"]: row for row in result["assertions"]["results"]}
                self.assertEqual(result["outcome"], "passed", result)
                self.assertEqual((rows["answer"]["outcome"], rows["answer-exact"]["outcome"]), ("passed", "failed"))
                self.assertEqual(rows["answer"]["actual"], "**Done.**")
                self.assertEqual(rows["answer-exact"]["role"], "diagnostic")
                return result

            with patch("dsh_eval.runner._prepare"), patch("dsh_eval.output_paths.check_output_root"), \
                    patch("dsh_eval.runner.ADAPTER", ROOT / "scripts/fixtures/mutation-adapter.js"), \
                    patch("dsh_eval.batch.run_case", side_effect=execute):
                result = run_experiment(path, root / "runs", max_samples=4,
                                        expected_plan_sha256=plan["planFingerprint"]["sha256"])
            self.assertEqual((result["status"], result["outcome"]), ("completed", "passed"))
            self.assertEqual(result["summary"]["outcomes"], {"passed": 4, "failed": 0, "unevaluable": 0})
            report = generate_report(Path(result["experimentDirectory"]) / "experiment-result.json", root / "reports")
            self.assertEqual(report["verificationCounts"], {"verified": 4})
            self.assertTrue(all(row["source"] == "synthetic" and row["outcome"] == "passed" for row in report["samples"]))

    def test_retry_without_intermediate_reads_cannot_pass_with_correct_final_state(self):
        case = load_json(FIXTURES / "rename-timeout-retry.case.json")
        case["caseId"] = "rename-timeout-skip-readbacks"
        case["configRef"].update(provider="synthetic", model="none")
        with tempfile.TemporaryDirectory(prefix="dsh-skip-reads-") as temp:
            root = Path(temp)
            case_path = root / "input.json"
            case_path.write_text(json.dumps(case), encoding="utf-8")
            with patch("dsh_eval.runner._prepare"), patch("dsh_eval.output_paths.check_output_root"), \
                    patch("dsh_eval.runner.ADAPTER", ROOT / "scripts/fixtures/mutation-adapter.js"):
                result = run_synthetic_case(case_path, root / "runs")
            run_dir = Path(result["association"]["runDir"])
            trace, = run_dir.glob("*.jsonl")
            events = [json.loads(line)["event"] for line in trace.read_text(encoding="utf-8").splitlines()]
            calls = [e for e in events if e["type"] == "tool/call"]
            replies = [e for e in events if e["type"] == "tool/result"]
            self.assertEqual([e["data"]["name"] for e in calls], ["eval_rename", "eval_rename", "eval_read"])
            self.assertEqual([json.loads(e["data"]["arguments"]) for e in calls],
                             [{"path": "draft.txt", "destination": "archive/final.txt"}] * 2
                             + [{"path": "archive/final.txt"}])
            messages = [r["data"]["message"] for r in replies]
            self.assertEqual([m["toolCallId"] for m in messages], [c["data"]["callId"] for c in calls])
            self.assertEqual([m["isError"] for m in messages], [True, False, False])
            self.assertEqual([m["content"][0]["text"] for m in messages],
                             ["Error: TOOL_TIMEOUT: draft.txt", "RENAMED: draft.txt -> archive/final.txt", "评测\r\n"])
            self.assertEqual([e["type"] for e in events if e["type"] in ("tool/call", "tool/result")],
                             ["tool/call", "tool/result"] * 3)

            self.assertEqual((result["source"], result["execution"]["status"], result["recording"]["outcome"]),
                             ("synthetic", "completed", "complete"))
            rows = {row["id"]: row for row in result["assertions"]["results"]}
            for key in ("timeout", "moves", "state", "answer", "answer-exact", "end"):
                self.assertEqual(rows[key]["outcome"], "passed", key)
            self.assertEqual(rows["state"]["actual"], {"archive/final.txt": "评测\r\n", "guard.txt": "keep\n"})
            for key in ("source-still-present", "target-still-missing", "retry", "verify"):
                self.assertEqual(rows[key]["outcome"], "insufficient_evidence", key)
            self.assertIn("No matching call/result", rows["source-still-present"]["reason"])
            for key, predecessor in (("target-still-missing", "source-still-present"),
                                     ("retry", "target-still-missing"), ("verify", "retry")):
                self.assertIn(predecessor, rows[key]["reason"])
            self.assertEqual((result["assertions"]["outcome"], result["outcome"]),
                             ("insufficient_evidence", "unevaluable"))


if __name__ == "__main__":
    unittest.main()
