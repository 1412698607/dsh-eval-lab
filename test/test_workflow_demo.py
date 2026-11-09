"""Rebuild the public workflow with actual Node pipes/recording and offline rechecks."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

from dsh_eval.__main__ import main as evaluate_main
from dsh_eval.browser import ArtifactBrowser
from dsh_eval.experiment import run_experiment
from dsh_eval.experiment_resume import plan_experiment_resume
from dsh_eval.formats import load_json
from dsh_eval.runner import ROOT
from dsh_eval.resume import plan_batch_resume
from dsh_eval.workflow_demo import generate_workflow, main


class WorkflowDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="dsh-workflow-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.base = Path(cls.temporary.name)
        cls.directory = cls.base / "first"
        cls.index = generate_workflow(cls.directory)

    def result(self, name):
        scenario = next(row for row in self.index["scenarios"] if row["id"] == name)
        return load_json(scenario.get("evaluationPath", scenario.get("previewPath")))

    def trace(self, result):
        path, = Path(result["association"]["runDir"]).glob("*.jsonl")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(all(row["runId"] == result["association"]["runId"]
                            and row["sessionId"] == result["association"]["sessionId"] for row in rows))
        return [row["event"] for row in rows]

    def test_recorded_calls_results_and_snapshot_show_the_missing_intermediate_steps(self):
        for name, expected_paths in (("complete", ["draft.txt", "draft.txt", "archive/final.txt", "draft.txt", "archive/final.txt"]),
                                     ("skip-readbacks", ["draft.txt", "draft.txt", "archive/final.txt"])):
            with self.subTest(name=name):
                result = self.result(name)
                events = self.trace(result)
                calls = [row for row in events if row["type"] == "tool/call"]
                results = [row for row in events if row["type"] == "tool/result"]
                self.assertEqual([json.loads(row["data"]["arguments"])["path"] for row in calls], expected_paths)
                self.assertEqual([row["type"] for row in events if row["type"] in ("tool/call", "tool/result")],
                                 ["tool/call", "tool/result"] * len(calls))
                self.assertEqual([row["data"]["message"]["toolCallId"] for row in results],
                                 [row["data"]["callId"] for row in calls])
                texts = [row["data"]["message"]["content"][0]["text"] for row in results]
                self.assertEqual(texts[0], "Error: TOOL_TIMEOUT: draft.txt")
                self.assertEqual(texts[-2:], ["RENAMED: draft.txt -> archive/final.txt", "评测\r\n"])
                if name == "complete":
                    self.assertEqual(texts[1:3], ["评测\r\n", "Error: NOT_FOUND: archive/final.txt"])
                evidence_path = Path(result["association"]["evidencePath"])
                evidence = load_json(evidence_path)
                snapshot = load_json(evidence_path.parent / "runtime.json")["environmentSnapshot"]
                self.assertEqual(snapshot["files"], {"archive/final.txt": "评测\r\n", "guard.txt": "keep\n"})
                self.assertEqual(evidence["source"], "synthetic")
                self.assertFalse(load_json(evidence_path.parent / "runtime.json")["modelCalled"])
                self.assertFalse((evidence_path.parent / "home").exists())
        complete, skipped = self.result("complete"), self.result("skip-readbacks")
        self.assertEqual((complete["execution"]["status"], complete["recording"]["outcome"], complete["outcome"]),
                         ("completed", "complete", "passed"))
        self.assertEqual([row["id"] for row in skipped["assertions"]["results"] if row["outcome"] == "insufficient_evidence"],
                         ["source-still-present", "target-still-missing", "retry", "verify"])
        self.assertEqual(sum(row["outcome"] == "passed" for row in skipped["assertions"]["results"]), 6)
        self.assertEqual(skipped["outcome"], "unevaluable")

    def test_frozen_four_samples_and_cli_preview_preserve_archive_digests(self):
        index = self.index
        manifest = load_json(index["experimentPath"])
        self.assertEqual(manifest["summary"]["outcomes"], {"passed": 4, "failed": 0, "unevaluable": 0})
        replies = []
        experiment_dir = Path(index["experimentPath"]).parent
        for sample in manifest["samples"]:
            result = load_json(experiment_dir / sample["evaluationPath"])
            final, = [row for row in self.trace(result) if row["type"] == "assistant/message"]
            replies.append(final["data"]["message"]["content"][0]["text"])
        self.assertEqual(replies, ["done", "**done**", "done", "done"])
        output = io.StringIO()
        with redirect_stdout(output):
            code = evaluate_main(["--compare-experiment-assertions", index["experimentPath"], "--candidate",
                                  str(self.directory / "inputs/strict-rule-map.json")])
        preview = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(preview["summary"], {"plannedSamples": 4, "comparedSamples": 4, "passToFail": 1,
                                              "failToPass": 0, "unchangedPassed": 3, "unchangedFailed": 0, "inconclusive": 0})
        self.assertEqual([row["sampleId"] for row in preview["samples"] if row["transition"] == "passToFail"], ["sample-000002"])
        digest_map = load_json(self.directory / "archive-sha256.json")
        for root, files in digest_map.items():
            for path, digest in files.items():
                self.assertEqual(hashlib.sha256((self.directory / root / path).read_bytes()).hexdigest(), digest)
        report = load_json(index["reportPath"])
        self.assertEqual(report["verificationCounts"], {"verified": 4})
        self.assertTrue(all(row["source"] == "synthetic" and row["configurationMatch"] == "matched" for row in report["samples"]))

    def test_structured_dependency_chain_links_observed_results_without_changing_scores(self):
        complete, skipped = self.result("complete"), self.result("skip-readbacks")
        positive = {row["id"]: row for row in complete["assertionDiagnostics"]["results"]}
        self.assertTrue(all(row["reasonCode"] == "matched" for row in positive.values()))
        expected = {"source-still-present": "timeout", "target-still-missing": "source-still-present",
                    "retry": "target-still-missing", "verify": "retry"}
        self.assertEqual({key: positive[key]["after"] for key in expected}, expected)
        diagnostics = {row["id"]: row for row in skipped["assertionDiagnostics"]["results"]}
        self.assertEqual(diagnostics["source-still-present"]["reasonCode"], "tool_evidence_missing")
        for key in ("target-still-missing", "retry", "verify"):
            self.assertEqual((diagnostics[key]["reasonCode"], diagnostics[key]["blockedBy"]),
                             ("dependency_not_passed", [expected[key]]))
        events = {event["seq"]: event for event in self.trace(skipped)}
        scores = {row["id"]: row for row in skipped["assertions"]["results"]}
        for key, seq in (("retry", 5), ("verify", 7)):
            location, = diagnostics[key]["observedMatches"]
            self.assertEqual(location["resultSeq"], seq)
            self.assertEqual(events[seq]["type"], "tool/result")
            self.assertFalse(events[seq]["data"]["message"]["isError"])
            self.assertEqual(scores[key]["outcome"], "insufficient_evidence")
            self.assertNotIn("evidence", scores[key])

    def test_experiment_cause_report_separates_the_diagnostic_deviation_from_passed_tasks(self):
        report = load_json(self.index["reportPath"])
        value = report["summary"]["assertionCauseSummary"]
        self.assertEqual((value["plannedSamples"], value["availableSamples"], value["missingSamples"]), (4, 4, 0))
        self.assertEqual(value["byRole"]["required"]["rootAffectedSamples"], 0)
        self.assertEqual(value["byRole"]["diagnostic"]["rootReasons"],
                         [{"reasonCode": "final_text_mismatch", "affectedSamples": 1, "sampleIds": ["sample-000002"]}])
        self.assertTrue(all(sample["outcome"] == "passed" for sample in report["samples"]))
        groups = {row["caseEntryId"]: row["bySource"]["synthetic"]["assertionCauseSummary"] for row in report["groups"]}
        self.assertEqual(groups["confirmation"]["byRole"]["diagnostic"]["rootAffectedSamples"], 0)
        self.assertEqual(groups["timeout-retry"]["byRole"]["diagnostic"]["rootAffectedSamples"], 1)

    def test_index_and_preview_are_browsable_with_bound_source_traces(self):
        browser = ArtifactBrowser(self.directory / "inputs", self.directory)
        items = browser.catalog()["items"]
        workflow, = [row for row in items if row["kind"] == "workflow_demo"]
        document = browser.document(workflow["id"])
        self.assertEqual([row["id"] for row in document["data"]["scenarios"]], ["complete", "skip-readbacks", "rule-impact"])
        self.assertTrue(all(browser.reference(row.get("evaluationPath", row.get("previewPath")))
                            for row in document["data"]["scenarios"]))
        preview, = [row for row in items if row["kind"] == "experiment_assertion_preview"]
        detail = browser.document(preview["id"])
        self.assertEqual(len(detail["sampleEvidence"]), 4)
        self.assertTrue(all(row["assertionTrace"]["id"] for row in detail["sampleEvidence"]))

    def test_second_cli_run_creates_fresh_identities_and_exits_without_serving(self):
        checkout = self.base / "checkout"
        checkout.mkdir()
        for name in ("dsh_eval", "src", "scripts", "fixtures"):
            shutil.copytree(ROOT / name, checkout / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(ROOT / "package.json", checkout / "package.json")
        completed = subprocess.run([sys.executable, "-m", "dsh_eval.workflow_demo", "--generate-only",
                                    "--output-dir", str(self.base / "second")], cwd=checkout,
                                   capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        second = json.loads(completed.stdout)
        self.assertNotEqual(second["workflowId"], self.index["workflowId"])
        self.assertNotEqual(second["outputDirectory"], self.index["outputDirectory"])
        old = self.result("complete")
        new = load_json(second["scenarios"][0]["evaluationPath"])
        self.assertNotEqual(old["caseRunId"], new["caseRunId"])
        self.assertNotEqual(old["association"]["runId"], new["association"]["runId"])
        self.assertNotIn("url", second)
        self.assertFalse(second["modelCalled"])

    def test_existing_output_and_unwritable_parent_report_errors_without_overwrite(self):
        existing = self.directory / "workflow-index.json"
        original = existing.read_bytes()
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--generate-only", "--output-dir", str(self.directory)])
        self.assertEqual((code, json.loads(output.getvalue())["status"]), (2, "error"))
        self.assertEqual(existing.read_bytes(), original)
        # A file in the parent position exercises an actual filesystem failure.
        blocked = self.base / "blocked"
        blocked.write_text("keep", encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--generate-only", "--output-dir", str(blocked / "child")]), 2)
        self.assertEqual(blocked.read_text(encoding="utf-8"), "keep")

    def test_synthetic_matrix_requires_exact_reply_coverage_before_output(self):
        path = self.directory / "inputs/workflow.experiment.json"
        for replies in ({}, {"sample-000001": "done"}, {f"sample-{i:06}": None for i in range(1, 5)}):
            with self.subTest(replies=replies), self.assertRaisesRegex(ValueError, "exactly"):
                run_experiment(path, self.base / "invalid", _synthetic_replies=replies)
        self.assertFalse((self.base / "invalid").exists())

    def test_occupied_viewer_port_reports_error_and_preserves_completed_artifacts(self):
        with socket.socket() as occupied:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            directory = self.base / "port-conflict"
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--output-dir", str(directory), "--port", str(occupied.getsockname()[1])])
            self.assertEqual((code, json.loads(output.getvalue())["status"]), (2, "error"))
            self.assertEqual(load_json(directory / "workflow-index.json")["status"], "completed")
            self.assertEqual(self.index["status"], "completed")

    def test_stopped_synthetic_matrix_cannot_resume_with_the_live_executor(self):
        path = self.directory / "inputs/workflow.experiment.json"
        result = run_experiment(path, self.base / "stopped", stop_after=1,
                                _synthetic_replies={f"sample-{i:06}": "done" for i in range(1, 5)})
        self.assertEqual((result["status"], result["stopReason"], result["modelCalled"]), ("stopped", "stop_after", False))
        self.assertNotIn("resumeSupportVersion", result)
        experiment_path = Path(result["experimentDirectory"]) / "experiment-result.json"
        with self.assertRaisesRegex(ValueError, "cannot be resumed"):
            plan_experiment_resume(experiment_path)
        batch_path = Path(result["experimentDirectory"]) / result["batchResultPath"]
        self.assertNotIn("resumeSupportVersion", load_json(batch_path))
        with self.assertRaisesRegex(ValueError, "cannot be resumed"):
            plan_batch_resume(batch_path)


if __name__ == "__main__":
    unittest.main()
