import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from dsh_eval.evaluate import evaluate
from dsh_eval.formats import load_json, validate_case, validate_evidence
from dsh_eval.runner import _process_options, classify_execution, prepare_workspace, run_case, supervise

ROOT = Path(__file__).resolve().parents[1]


def live_case():
    return load_json(ROOT / "fixtures" / "evaluation" / "live-read.case.json")


def completed_host():
    return {"childClosed": True, "exitCode": 0, "signal": None, "intervention": None,
            "forceStopped": False, "error": None,
            "protocol": {"valid": True, "turnEndReason": {"kind": "completed"}}}


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dsh-case-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def test_fresh_workspace_materializes_exact_initial_text(self):
        case = live_case()
        case["environment"]["files"]["nested/说明.md"] = "文本\n"
        workspace = prepare_workspace(self.directory, validate_case(case))
        self.assertEqual((workspace / "nested" / "说明.md").read_bytes(), "文本\n".encode())
        with self.assertRaises(FileExistsError):
            prepare_workspace(self.directory, case)

    def test_windows_reserved_names_and_case_collisions_rejected(self):
        for files in ({"CON.txt": "a"}, {"file.": "a"}, {"file ": "a"}, {"a?b": "a"},
                      {"A.md": "a", "a.md": "b"}, {"A": "a", "a/b.md": "b"}):
            case = live_case()
            case["environment"]["files"] = files
            with self.subTest(files=files), self.assertRaises(ValueError):
                prepare_workspace(self.directory, validate_case(case))
        self.assertFalse((self.directory / "workspace").exists())

    def test_startup_failure_preserves_null_facts_and_can_be_re_evaluated(self):
        case_file = self.directory / "input.json"
        case_file.write_text(json.dumps(live_case()), encoding="utf-8")
        with patch("dsh_eval.runner._prepare", side_effect=ValueError("test startup failure")):
            result = run_case(case_file, self.directory / "outputs")
        self.assertEqual(result["evaluationFormatVersion"], 2)
        self.assertEqual(result["execution"]["status"], "runtime_error")
        self.assertIsNone(result["association"]["runId"])
        self.assertIsNone(result["association"]["sessionId"])
        self.assertIsNone(result["configuration"])
        self.assertFalse(result["budgetEnforcement"]["timeoutSeconds"])
        self.assertEqual(result["assertions"]["outcome"], "not_run")
        self.assertEqual(load_json(result["association"]["runtimeReport"])["error"]["message"], "test startup failure")
        rerun = evaluate(result["association"]["casePath"], result["association"]["evidencePath"])
        self.assertEqual(rerun["outcome"], "unevaluable")
        self.assertEqual(rerun["caseRunId"], result["caseRunId"])

    def test_each_execution_gets_distinct_directories_and_ids(self):
        case_file = self.directory / "input.json"
        case_file.write_text(json.dumps(live_case()), encoding="utf-8")
        with patch("dsh_eval.runner._prepare", side_effect=ValueError("test startup failure")):
            first = run_case(case_file, self.directory / "outputs")
            second = run_case(case_file, self.directory / "outputs")
        self.assertNotEqual(first["caseRunId"], second["caseRunId"])
        self.assertNotEqual(first["association"]["casePath"], second["association"]["casePath"])

    def test_forced_timeout_without_host_report_keeps_timeout_fact(self):
        case = live_case()
        case["budget"]["timeoutSeconds"] = 1
        case_file = self.directory / "input.json"
        case_file.write_text(json.dumps(case), encoding="utf-8")
        # Real process, synthetic protocol: deliberately omit the final host report.
        adapter = self.directory / "adapter.mjs"
        adapter.write_text("import { createInterface } from 'node:readline';\n"
                           "const input = createInterface({input:process.stdin});\n"
                           "input.on('line', () => process.exit(0));\n", encoding="utf-8")
        with patch("dsh_eval.runner._prepare"), patch("dsh_eval.runner.ADAPTER", adapter):
            result = run_case(case_file, self.directory / "outputs")
        self.assertEqual(result["execution"]["status"], "timed_out")
        self.assertEqual(result["outcome"], "unevaluable")


class EvidenceV2Tests(unittest.TestCase):
    def evidence(self):
        return {"evidenceFormatVersion": 2, "caseRunId": str(uuid4()), "caseId": live_case()["caseId"],
                "runId": None, "sessionId": None, "runDir": None, "source": "live", "configuration": None,
                "budgetEnforcement": {"timeoutSeconds": False}, "execution": {"status": "runtime_error"},
                "runtimeReport": "runtime.json"}

    def test_version_two_allows_missing_startup_facts(self):
        self.assertEqual(validate_evidence(self.evidence(), live_case())["evidenceFormatVersion"], 2)

    def test_version_one_does_not_accept_null_recording_facts(self):
        evidence = self.evidence()
        evidence.update(evidenceFormatVersion=1)
        evidence.pop("runtimeReport")
        with self.assertRaises(ValueError):
            validate_evidence(evidence, live_case())


class ExecutionTests(unittest.TestCase):
    def test_completed_requires_normal_exit_protocol_and_cleanup(self):
        supervisor = {"adapterExitCode": 0}
        self.assertEqual(classify_execution(completed_host(), supervisor)["status"], "completed")
        for updates in ({"exitCode": 1}, {"signal": "SIGKILL"}, {"childClosed": False}, {"forceStopped": True},
                        {"protocol": {"valid": False}}, {"error": "fork EPERM"}):
            with self.subTest(updates=updates):
                self.assertEqual(classify_execution({**completed_host(), **updates}, supervisor)["status"], "runtime_error")

    def test_timeout_and_cancel_are_not_ordinary_task_failures(self):
        host = completed_host()
        host["protocol"]["turnEndReason"] = {"kind": "aborted", "reason": {"kind": "user"}}
        self.assertEqual(classify_execution(host, {"intervention": "timeout"})["status"], "timed_out")
        self.assertEqual(classify_execution(host, {"intervention": "cancel"})["status"], "cancelled")
        host["protocol"]["turnEndReason"] = {"kind": "completed"}
        self.assertEqual(classify_execution(host, {"intervention": "cancel"})["status"], "unknown")


class SupervisorTests(unittest.TestCase):
    def child(self, code):
        process = subprocess.Popen([sys.executable, "-u", "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, encoding="utf-8", **_process_options())
        def cleanup():
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout):
                if stream and not stream.closed:
                    stream.close()
        self.addCleanup(cleanup)
        return process

    def test_real_process_stream_trigger_sends_cancellation_and_reaps(self):
        child = self.child("import json,sys; print(json.dumps({'type':'streaming'}),flush=True); "
                           "command=json.loads(sys.stdin.readline()); sys.exit(0 if command['type']=='cancel' else 9)")
        report = supervise(child, 5, cancel_after_stream=True, event_log=io.StringIO())
        self.assertEqual(report["intervention"], "cancel")
        self.assertEqual(report["adapterExitCode"], 0)
        self.assertIsNotNone(child.poll())

    def test_real_process_deadline_sends_timeout_and_reaps(self):
        child = self.child("import json,sys; command=json.loads(sys.stdin.readline()); "
                           "sys.exit(0 if command['type']=='timeout' else 9)")
        report = supervise(child, 0.2)
        self.assertEqual(report["intervention"], "timeout")
        self.assertEqual(report["adapterExitCode"], 0)

    def test_malformed_protocol_requests_shutdown(self):
        child = self.child("import json,sys; print('bad json',flush=True); command=json.loads(sys.stdin.readline()); "
                           "sys.exit(0 if command['type']=='shutdown' else 9)")
        report = supervise(child, 5)
        self.assertTrue(report["protocolError"])
        self.assertEqual(report["intervention"], "shutdown")

    def test_hung_owned_process_is_forcibly_reaped_after_grace(self):
        child = self.child("import time; time.sleep(60)")
        with patch("dsh_eval.runner.CLEANUP_TIMEOUT", 0.2):
            report = supervise(child, 0.2)
        self.assertTrue(report["forceStopAttempted"])
        self.assertIsNotNone(child.poll())
        denied_child = self.child("import time; time.sleep(60)")
        partial = {}
        with patch("dsh_eval.runner.CLEANUP_TIMEOUT", 0.2), \
                patch("dsh_eval.runner.stop_process_tree", side_effect=ValueError("permission denied")):
            with self.assertRaises(ValueError):
                supervise(denied_child, 0.2, report=partial)
        self.assertEqual(partial["intervention"], "timeout")
        self.assertTrue(partial["forceStopAttempted"])


if __name__ == "__main__":
    unittest.main()
