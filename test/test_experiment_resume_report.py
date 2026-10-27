"""Offline reports of synthetic experiment continuations across two batches."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

import test_experiment_resume as fixtures
from dsh_eval import experiment
from dsh_eval.batch import _checkpoint
from dsh_eval.browser import ArtifactBrowser
from dsh_eval.experiment import run_experiment
from dsh_eval.experiment_resume import plan_experiment_resume, resume_experiment
from dsh_eval.formats import load_json
from dsh_eval.report import generate_report
from dsh_eval.resume import CLAIM_NAME, plan_batch_resume, resume_batch
from dsh_eval.runner import ROOT


class ExperimentResumeReportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExperimentResumeTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.directory = self.fixture.directory
        self.outputs = self.directory / "reports"

    def save(self, path, value):
        self.fixture.save(path, value)

    def resume(self, boundary="finished"):
        if boundary == "first-finished":
            def checkpoint(directory, report):
                _checkpoint(directory, report)
                if report["entries"][0]["status"] == "finished" and report["entries"][1]["status"] == "pending":
                    self.fixture.batch_source = directory / "batch-result.json"
                    self.fixture.source = directory.parents[1] / "experiment-result.json"
                    raise fixtures.SimulatedCrash
            with patch("dsh_eval.batch._checkpoint", side_effect=checkpoint), self.assertRaises(fixtures.SimulatedCrash):
                run_experiment(self.fixture.path, self.directory / "outputs", max_samples=8)
            plan = plan_experiment_resume(self.fixture.source, max_samples=7)
            self.result = resume_experiment(self.fixture.source, self.directory / "resumes", max_samples=7,
                                            expected_plan_sha256=plan["planFingerprint"]["sha256"])
        else:
            self.fixture.crash(boundary)
            self.result = self.fixture.execute()
        self.path = Path(self.result["resumeDirectory"]) / "experiment-resume-result.json"
        self.child_path = self.path.parent / self.result["batchResumeResultPath"]
        self.child = load_json(self.child_path)
        self.batch_path = self.child_path.parent / self.child["batchResultPath"]
        self.batch = load_json(self.batch_path)
        self.original = self.fixture.source
        self.original_batch = self.fixture.batch_source
        self.fixture.called.clear()

    def report(self):
        return generate_report(self.path, self.outputs)

    def snapshot(self):
        return {path.relative_to(self.directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for root in (self.original.parent, self.path.parent) for path in root.rglob("*") if path.is_file()}

    def reject(self):
        with patch("dsh_eval.report.evaluate", side_effect=AssertionError("must reject before inspecting")), \
                self.assertRaises((ValueError, OSError, KeyError, TypeError)):
            self.report()
        self.assertFalse(self.outputs.exists())
        self.assertEqual(self.fixture.called, [])

    def test_eight_samples_are_rechecked_paired_and_usage_is_partitioned_without_source_writes(self):
        self.resume()
        before = self.snapshot()
        with patch("dsh_eval.resume.run_batch", side_effect=AssertionError("report cannot execute")), \
                patch("dsh_eval.experiment_resume.uuid4", side_effect=AssertionError("report cannot allocate an execution")):
            report = self.report()
        self.assertEqual(report["comparisonReportFormatVersion"], 2)
        self.assertEqual(report["planVerification"]["status"], "verified")
        self.assertEqual(report["resumeVerification"]["status"], "verified")
        self.assertIsNone(report["batchId"])
        self.assertEqual(report["batchIds"], [self.result["sourceBatchId"], self.batch["batchId"]])
        self.assertEqual(report["verificationCounts"], {"verified": 8})
        self.assertEqual(report["summary"]["sourceCounts"], {"synthetic": 8})
        self.assertEqual(report["summary"]["planned"], 8)
        self.assertEqual(report["reusedSummary"]["planned"], 2)
        self.assertEqual(report["newlyExecutedSummary"]["planned"], 6)
        self.assertEqual([row["executionOrigin"] for row in report["samples"]], ["reused"] * 2 + ["new"] * 6)
        self.assertEqual(len(report["groups"]), 4)
        self.assertEqual([item["pairedSamples"] for item in report["comparisons"]], [2, 2])
        self.assertEqual([row["sampleId"] for row in report["samples"]],
                         [row["sampleId"] for row in self.result["samplePlan"]])
        for key in ("modelCalls", "toolCalls", "elapsedSeconds"):
            self.assertAlmostEqual(report["summary"]["metrics"][key]["observedTotal"],
                report["reusedSummary"]["metrics"][key]["observedTotal"] +
                report["newlyExecutedSummary"]["metrics"][key]["observedTotal"])
        self.assertIsNone(report["newlyExecutedSummary"]["metrics"]["cost"]["observedTotal"])
        markdown = (Path(report["reportDirectory"]) / "report.md").read_text(encoding="utf-8")
        self.assertIn("历史复用与本次新增", markdown)
        self.assertIn("本次新增", markdown)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.fixture.called, [])

    def test_generated_continuation_report_browses_both_batches_and_traces_without_writes(self):
        self.resume()
        report = self.report()
        browser = ArtifactBrowser(ROOT / "fixtures/evaluation", self.directory)
        report_id = browser.reference(Path(report["reportDirectory"]) / "report.json")
        before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in self.directory.rglob("*") if path.is_file()}
        visited, kinds, traces = set(), set(), []
        pending = [report_id]
        with patch("dsh_eval.report.evaluate", side_effect=AssertionError("browse must not recheck")), \
                patch("dsh_eval.runner.run_case", side_effect=AssertionError("browse must not execute")):
            catalog = {item["id"]: item for item in browser.catalog()["items"]}
            self.assertEqual(catalog[report_id]["kind"], "report")
            self.assertNotIn("error", catalog[report_id])
            self.assertEqual(catalog[report_id]["sources"], ["synthetic"])
            document = browser.document(report_id)
            batch_links = [link for link in document["links"] if link["label"].endswith(" / sourceBatchResult")]
            self.assertEqual(len(batch_links), 8)
            self.assertEqual(len({link["id"] for link in batch_links}), 2)
            self.assertTrue(all(link["id"] for link in batch_links))
            while pending:
                identifier = pending.pop()
                if identifier in visited:
                    continue
                visited.add(identifier)
                document = browser.document(identifier)
                kinds.add(document["kind"])
                if document["kind"] == "trace":
                    self.assertTrue(document["rows"])
                    traces.append(identifier)
                pending.extend(link["id"] for link in document["links"] if link["id"])
        self.assertTrue({"experiment", "experiment_resume", "batch_resume", "batch", "report", "evaluation", "evidence", "trace"} <= kinds)
        self.assertEqual(len(traces), 8)
        self.assertTrue(all(browser.reference(path) in visited for path in (self.original, self.original_batch, self.path,
                                                                          self.child_path, self.batch_path)))
        self.assertEqual({str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in self.directory.rglob("*") if path.is_file()}, before)
        self.assertEqual(self.fixture.called, [])

    def test_stale_source_checkpoint_reuses_canonical_evidence_paths(self):
        self.resume("saved-evaluation")
        report = self.report()
        self.assertEqual(report["verificationCounts"], {"verified": 8})
        self.assertEqual(report["reusedSummary"]["planned"], 2)

    def test_pair_can_cross_execution_boundary_but_keeps_the_same_original_repeat(self):
        self.resume("first-finished")
        report = self.report()
        self.assertEqual(report["reusedSummary"]["planned"], 1)
        self.assertEqual(report["newlyExecutedSummary"]["planned"], 7)
        self.assertEqual([row["pairedSamples"] for row in report["comparisons"]], [2, 2])
        self.assertEqual([row["executionOrigin"] for row in report["samples"][:2]], ["reused", "new"])

    def test_original_source_files_are_not_required_after_freezing(self):
        self.resume()
        self.fixture.path.unlink()
        (self.directory / "first.json").unlink()
        self.assertEqual(self.report()["verificationCounts"], {"verified": 8})

    def test_original_finalization_blocks_continuations_until_its_last_checkpoint(self):
        finalizing, release = threading.Event(), threading.Event()
        failures = []
        checkpoint = experiment._checkpoint
        interrupted = False

        def interrupt_after_first(directory, report):
            nonlocal interrupted
            _checkpoint(directory, report)
            if not interrupted and report["entries"][0]["status"] == "finished" and report["entries"][1]["status"] == "pending":
                interrupted = True
                raise KeyboardInterrupt

        def pause_final_checkpoint(directory, report):
            if report["status"] != "running":
                self.original = directory / "experiment-result.json"
                self.original_batch = directory / report["batchResultPath"]
                finalizing.set()
                if not release.wait(30):
                    raise TimeoutError("Experiment finalization was not released")
            checkpoint(directory, report)

        def original_experiment():
            try:
                run_experiment(self.fixture.path, self.directory / "outputs", max_samples=8)
            except BaseException as error:
                failures.append(error)

        with patch("dsh_eval.batch._checkpoint", side_effect=interrupt_after_first), \
                patch("dsh_eval.experiment._checkpoint", side_effect=pause_final_checkpoint):
            worker = threading.Thread(target=original_experiment)
            worker.start()
            try:
                self.assertTrue(finalizing.wait(30), failures)
                self.assertEqual(load_json(self.original)["status"], "running")
                self.assertEqual(load_json(self.original_batch)["status"], "interrupted")
                for operation in (
                    lambda: plan_experiment_resume(self.original, max_samples=7),
                    lambda: plan_batch_resume(self.original_batch, max_samples=7),
                    lambda: resume_experiment(self.original, self.directory / "resumes", max_samples=7,
                                              expected_plan_sha256="0" * 64),
                    lambda: resume_batch(self.original_batch, self.directory / "resumes", max_samples=7,
                                         expected_plan_sha256="0" * 64),
                ):
                    with self.assertRaisesRegex(ValueError, "active or locked"):
                        operation()
                self.assertEqual(len(self.fixture.called), 1)
                self.assertFalse((self.original_batch.parent / CLAIM_NAME).exists())
                self.assertFalse((self.directory / "resumes").exists())
            finally:
                release.set()
                worker.join(30)
            self.assertFalse(worker.is_alive())
            self.assertEqual(failures, [])
        original_bytes = self.original.read_bytes()
        plan = plan_experiment_resume(self.original, max_samples=7)
        self.assertTrue(plan["eligibleForResume"])
        result = resume_experiment(self.original, self.directory / "resumes", max_samples=7,
                                   expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertEqual(result["outcome"], "passed")
        report = generate_report(Path(result["resumeDirectory"]) / "experiment-resume-result.json", self.outputs)
        self.assertEqual(report["verificationCounts"], {"verified": 8})
        self.assertEqual((report["reusedSummary"]["planned"], report["newlyExecutedSummary"]["planned"]), (1, 7))
        self.assertEqual(self.original.read_bytes(), original_bytes)

    def test_failed_experiment_final_checkpoint_releases_the_batch_lock(self):
        checkpoint = experiment._checkpoint

        def fail_final_checkpoint(directory, report):
            if report["status"] != "running":
                self.original = directory / "experiment-result.json"
                raise OSError("Synthetic final checkpoint failure")
            checkpoint(directory, report)

        with patch("dsh_eval.experiment._checkpoint", side_effect=fail_final_checkpoint), \
                self.assertRaisesRegex(OSError, "final checkpoint failure"):
            run_experiment(self.fixture.path, self.directory / "outputs", max_samples=8)
        plan = plan_experiment_resume(self.original)
        self.assertFalse(plan["eligibleForResume"])
        self.assertEqual(plan["counts"], {"original": 8, "reused": 8, "newSamples": 0, "blocked": 0})
        self.assertEqual(load_json(self.original)["status"], "running")

    def test_local_plugin_upgrade_does_not_block_offline_continuation_reports(self):
        self.resume()
        before = self.snapshot()

        def upgraded_package(path):
            data = load_json(path)
            return {**data, "version": data["version"] + "-upgrade-test"} if path == ROOT / "package.json" else data

        with patch("dsh_eval.runner.load_json", side_effect=upgraded_package), \
                patch("dsh_eval.resume.run_batch", side_effect=AssertionError("report must not execute")):
            report = self.report()
        self.assertEqual(report["verificationCounts"], {"verified": 8})
        self.assertTrue(all(row["configurationMatch"] == "matched" for row in report["samples"]))
        self.assertEqual(report["resumeVerification"]["status"], "verified")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.fixture.called, [])

    def test_actual_request_route_mismatch_excludes_the_affected_pair(self):
        self.resume()
        row = self.batch["entries"][0]
        trace = next((self.batch_path.parent / row["runDir"]).glob("*.jsonl"))
        events = [json.loads(line)["event"] for line in trace.read_text(encoding="utf-8").splitlines()]
        next(event["data"]["header"]["config"] for event in events if event["type"] == "request/header")["model"] = "wrong-route"
        case_directory = self.batch_path.parent / row["caseDirectory"]
        code = """
import { recordExample } from './scripts/demo-eval.js';
let text = ''; for await (const chunk of process.stdin) text += chunk;
const data = JSON.parse(text);
console.log(JSON.stringify(await recordExample(data.casePath, data.events, data.outputDir)));
"""
        process = subprocess.run(["node", "--input-type=module", "-e", code], cwd=ROOT,
            input=json.dumps({"casePath": str(case_directory / "case.json"), "events": events,
                              "outputDir": str(case_directory / "replacement")}),
            capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
        recorded = json.loads(process.stdout)
        evidence_path = self.batch_path.parent / row["evidencePath"]
        evidence = load_json(evidence_path)
        for key in ("runId", "sessionId"):
            evidence[key] = row[key] = recorded[key]
        run_dir = Path(recorded["evidencePath"]).parent
        evidence["runDir"] = str(run_dir.relative_to(case_directory))
        row["runDir"] = run_dir.relative_to(self.batch_path.parent).as_posix()
        self.save(evidence_path, evidence)
        self.save(self.batch_path, self.batch)
        report = self.report()
        self.assertEqual(report["samples"][2]["recordingOutcome"], "complete")
        self.assertEqual(report["samples"][2]["configurationMatch"], "mismatched")
        self.assertEqual(sum(item["pairedSamples"] for item in report["comparisons"]), 3)

    def test_source_labels_do_not_allow_live_and_synthetic_to_pair(self):
        self.resume()
        # Deliberately conflicting provenance labels, never a real model sample.
        row = self.batch["entries"][0]
        evidence_path = self.batch_path.parent / row["evidencePath"]
        evidence = load_json(evidence_path)
        evidence["source"] = row["source"] = "live"
        self.save(evidence_path, evidence)
        self.save(self.batch_path, self.batch)
        report = self.report()
        self.assertEqual(report["summary"]["sourceCounts"], {"synthetic": 7, "live": 1})
        self.assertEqual(sum(item["pairedSamples"] for item in report["comparisons"]), 3)
        self.assertTrue(all(item["pairedSamples"] == 0 for item in report["comparisons"] if item["source"] == "live"))

    def test_bad_recording_in_either_batch_keeps_denominators_and_excludes_only_its_pair(self):
        self.resume()
        original = load_json(self.original_batch)
        for batch_path, entry in ((self.original_batch, original["entries"][0]), (self.batch_path, self.batch["entries"][0])):
            trace = next((batch_path.parent / entry["runDir"]).glob("*.jsonl"))
            data = trace.read_bytes()
            trace.write_bytes(data[:-3])
            report = self.report()
            self.assertEqual(report["summary"]["planned"], 8)
            self.assertEqual(report["summary"]["attempted"], 8)
            self.assertEqual(sum(row["pairedSamples"] for row in report["comparisons"]), 3)
            self.assertEqual(sum(row["configurationMatch"] != "matched" for row in report["samples"]), 1)
            trace.write_bytes(data)

    def test_missing_historical_evidence_is_rejected_as_one_sample(self):
        self.resume()
        entry = load_json(self.original_batch)["entries"][0]
        (self.original_batch.parent / entry["evidencePath"]).unlink()
        report = self.report()
        self.assertEqual(report["verificationCounts"], {"rejected": 1, "verified": 7})
        self.assertIsNone(report["samples"][0]["source"])
        self.assertEqual(report["summary"]["planned"], 8)

    def test_duplicate_case_execution_or_wrong_repeat_rejects_before_inspect(self):
        self.resume()
        original = copy.deepcopy(self.batch)
        historical = load_json(self.original_batch)["entries"][0]
        self.batch["entries"][0]["caseRunId"] = historical["caseRunId"]
        self.save(self.batch_path, self.batch)
        self.reject()
        self.save(self.batch_path, original)
        changed = copy.deepcopy(self.result)
        changed["samplePlan"][0]["repeatIndex"] = True
        self.save(self.path, changed)
        self.reject()

    def test_changed_frozen_input_or_plan_snapshot_rejects_before_inspect(self):
        self.resume()
        case_path = self.batch_path.parent / self.batch["entries"][0]["casePath"]
        original = case_path.read_bytes()
        changed = load_json(case_path)
        changed["input"] += " changed"
        self.save(case_path, changed)
        self.reject()
        case_path.write_bytes(original)
        snapshot = self.original.parent / "plan-input.json"
        snapshot.write_bytes(snapshot.read_bytes() + b"\n")
        self.reject()

    def test_foreign_or_escaping_downstream_binding_and_claim_mismatch_reject(self):
        self.resume()
        original = copy.deepcopy(self.result)
        for value in ("../outside/resume-result.json", "continuations/foreign/resume-result.json"):
            self.result["batchResumeResultPath"] = value
            self.save(self.path, self.result)
            self.reject()
        self.save(self.path, original)
        claim = self.original_batch.parent / ".batch-resume-claim.json"
        data = load_json(claim)
        data["resumeDirectory"] = str(self.directory / "foreign")
        self.save(claim, data)
        self.reject()

    def test_running_unknown_version_and_changed_resume_fingerprint_reject(self):
        self.resume()
        original = copy.deepcopy(self.result)
        for change in ({"status": "running"}, {"experimentResumeResultFormatVersion": True},
                       {"planFingerprint": {"version": 1, "sha256": "0" * 64}}):
            self.save(self.path, {**original, **change})
            self.reject()

    def test_huge_repetition_metadata_rejects_before_expansion_inspection_or_output(self):
        self.resume()
        snapshot = self.original.parent / "plan-input.json"
        data = load_json(snapshot)
        data["manifest"]["repetitions"] = 10 ** 100
        self.save(snapshot, data)
        self.reject()

    def test_new_runner_error_keeps_all_eight_samples_and_skipped_source_unknown(self):
        self.fixture.crash()
        with patch("dsh_eval.batch.run_case", side_effect=ValueError("synthetic runner error")):
            self.result = self.fixture.execute()
        self.path = Path(self.result["resumeDirectory"]) / "experiment-resume-result.json"
        report = self.report()
        self.assertEqual(report["summary"]["planned"], 8)
        self.assertEqual(report["newlyExecutedSummary"]["skipped"], 5)
        self.assertEqual(report["newlyExecutedSummary"]["sourceCounts"], {"unknown": 6})
        self.assertEqual(report["reusedSummary"]["sourceCounts"], {"synthetic": 2})
        self.assertTrue(all(row["source"] is None for row in report["samples"][2:]))
        child_path = self.path.parent / self.result["batchResumeResultPath"]
        new_path = child_path.parent / load_json(child_path)["batchResultPath"]
        new_batch = load_json(new_path)
        new_batch["entries"][1]["source"] = "synthetic"
        self.save(new_path, new_batch)
        self.outputs = self.directory / "invalid-reports"
        self.reject()

    def test_historical_failed_tasks_remain_failed_even_when_new_tasks_pass(self):
        self.fixture.manifest["repetitions"] = 1
        self.save(self.fixture.path, self.fixture.manifest)
        case_path = self.directory / "first.json"
        case = load_json(case_path)
        next(row for row in case["assertions"] if row["type"] == "final_text")["equals"] = "wrong"
        self.save(case_path, case)
        self.resume()
        report = self.report()
        self.assertEqual(report["reusedSummary"]["outcomes"]["failed"], 2)
        self.assertEqual(report["newlyExecutedSummary"]["outcomes"]["passed"], 2)
        self.assertEqual(report["summary"]["outcomes"]["failed"], 2)

    def test_real_cli_accepts_resume_result_without_scheduling(self):
        self.resume()
        before = self.snapshot()
        process = subprocess.run([sys.executable, "-m", "dsh_eval", "--report", str(self.path),
                                  "--reports-root", str(self.outputs)], cwd=ROOT,
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(json.loads(process.stdout)["comparisonReportFormatVersion"], 2)
        self.assertEqual(process.stderr, "")
        self.assertEqual(self.snapshot(), before)

    def test_browser_follows_generated_version_two_report_to_both_batches_and_traces(self):
        self.resume()
        report = self.report()
        browser = ArtifactBrowser(self.directory / "library", self.directory)
        identifier = browser.reference(Path(report["reportDirectory"]) / "report.json")
        before = self.snapshot()
        pending, visited = [identifier], set()
        with patch("dsh_eval.report.evaluate", side_effect=AssertionError("browse must not recheck")), \
                patch("dsh_eval.resume.run_batch", side_effect=AssertionError("browse must not schedule")):
            while pending:
                value = pending.pop()
                if value in visited:
                    continue
                visited.add(value)
                document = browser.document(value)
                pending.extend(link["id"] for link in document["links"] if link["id"])
        for path in (self.original, self.original_batch, self.path, self.child_path, self.batch_path):
            self.assertIn(browser.reference(path), visited)
        self.assertTrue(any(value.startswith(browser.reference(self.original_batch).rsplit("/", 1)[0])
                            and value.endswith(".jsonl") for value in visited))
        self.assertTrue(any(value.startswith(browser.reference(self.batch_path).rsplit("/", 1)[0])
                            and value.endswith(".jsonl") for value in visited))
        self.assertEqual(self.snapshot(), before)
