"""Regression pages bind saved comparisons to the configured original source graph."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dsh_eval.browser import ArtifactBrowser
from dsh_eval.formats import load_json
from dsh_eval.regression import compare_baseline
from dsh_eval.regression_demo import generate_regression_demo


class RegressionBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="dsh-regression-browser-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.base = Path(cls.temporary.name).resolve()
        cls.directory = cls.base / "full"
        cls.index = generate_regression_demo(cls.directory)
        cls.browser = ArtifactBrowser(cls.directory / "inputs", cls.directory)
        cls.regression = load_json(cls.directory / "artifacts/regression.json")

    def save(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def document(self, data=None):
        path = self.save(self.directory / "artifacts" / (self._testMethodName + ".json"),
                         self.regression if data is None else data)
        return self.browser.document(self.browser.reference(path))

    @contextmanager
    def changed(self, path, mutate):
        before = path.read_bytes()
        value = load_json(path)
        mutate(value)
        self.save(path, value)
        try:
            yield
        finally:
            path.write_bytes(before)

    def assert_unavailable(self, descriptor):
        self.assertEqual(descriptor["status"], "unavailable")
        self.assertFalse(any(descriptor.get(key) for key in ("evidenceId", "evaluationId", "assertionTrace")))

    def test_catalog_discovers_arbitrary_output_names_and_preserves_counts_sources(self):
        path = self.save(self.directory / "artifacts/arbitrary-output-name.json", self.regression)
        self.save(self.directory / "artifacts/unrelated.json", {"secret": "not a comparison"})
        catalog = self.browser.catalog()
        item, = [row for row in catalog["items"] if row["id"] == self.browser.reference(path)]
        self.assertEqual(item["kind"], "regression_comparison")
        self.assertEqual(item["regressionCounts"], self.regression["counts"])
        self.assertEqual(item["sources"], ["synthetic"])
        self.assertFalse(any(row["path"].endswith("unrelated.json") for row in catalog["items"]))
        self.assertTrue({"no-regression.json", "regression.json", "incomplete.json"}.issubset(
            {Path(row["path"]).name for row in catalog["items"] if row["kind"] == "regression_comparison"}))

    def test_original_evaluations_and_both_answer_events_are_bound_without_rechecking(self):
        with patch("dsh_eval.report.evaluate", side_effect=AssertionError("Viewer must not re-evaluate")), \
                patch("subprocess.Popen", side_effect=AssertionError("Viewer must not execute processes")):
            document = self.document()
            self.assertEqual(document["data"], self.regression)
            self.assertEqual(document["links"], [])
            self.assertTrue(all(value["status"] == "available" for value in document["regressionSources"].values()))
            for side, expected in (("baseline", "done"), ("candidate", "WRONG")):
                descriptor = document["regressionEvidence"][0][side]
                self.assertEqual(descriptor["status"], "available")
                evaluation = self.browser.document(descriptor["evaluationId"])
                self.assertEqual(evaluation["kind"], "evaluation")
                evidence = self.browser.document(descriptor["evidenceId"])["data"]
                trace = descriptor["assertionTrace"]
                self.assertEqual((trace["runId"], trace["sessionId"]), (evidence["runId"], evidence["sessionId"]))
                seq = next(row["evidence"]["answerSeq"] for row in evaluation["data"]["assertions"]["results"]
                           if isinstance(row.get("evidence"), dict) and "answerSeq" in row["evidence"])
                page = self.browser.document(trace["id"], seq=seq, run_id=trace["runId"], session_id=trace["sessionId"])
                selected, = [row["data"] for row in page["rows"] if row["line"] == page["focus"]["line"]]
                self.assertEqual(selected["event"]["data"]["message"]["content"][0]["text"], expected)

    def test_ci_only_files_do_not_probe_existing_originals_outside_the_configured_roots(self):
        target = self.base / "ci-only"
        shutil.copytree(self.directory / "artifacts", target)
        browser = ArtifactBrowser(target / "cases", target)
        original = browser._json
        def bounded(path):
            self.assertTrue(path.is_relative_to(target))
            return original(path)
        with patch.object(browser, "_json", side_effect=bounded):
            result = browser.document(browser.reference(target / "regression.json"))
        self.assertEqual(result["data"]["counts"], self.regression["counts"])
        self.assertTrue(all(row["status"] == "unavailable" for row in result["regressionSources"].values()))
        for pair in result["regressionEvidence"]:
            for side in ("baseline", "candidate"):
                self.assert_unavailable(pair[side])

    def test_incomplete_and_missing_sides_keep_their_saved_meaning_without_fake_links(self):
        data = load_json(self.directory / "artifacts/incomplete.json")
        result = self.document(data)
        self.assertEqual(result["data"]["exitCode"], 2)
        self.assertTrue(result["data"]["hasRegressions"])
        self.assertEqual(result["regressionEvidence"][1]["candidate"]["status"], "not_recorded")
        data["samples"][0]["candidate"] = None
        result = self.document(data)
        self.assertEqual(result["regressionEvidence"][0]["candidate"]["status"], "missing_side")
        self.assertEqual(result["regressionEvidence"][0]["baseline"]["status"], "available")

    def test_source_configuration_matrix_and_duplicate_execution_ids_are_not_guessed(self):
        data = deepcopy(self.regression)
        data["baseline"]["configuration"]["configRef"]["model"] = "forged"
        self.assertEqual(self.document(data)["regressionSources"]["baseline"]["status"], "unavailable")
        source = Path(self.regression["baseline"]["sourceResult"])
        for mutate in (lambda value: value["samples"][1].update(sampleId=value["samples"][0]["sampleId"]),
                       lambda value: value["samples"][1].update(repeatIndex=value["samples"][0]["repeatIndex"]),
                       lambda value: value["samples"][1].update(caseRunId=value["samples"][0]["caseRunId"])):
            with self.changed(source, mutate):
                result = self.document()
                self.assertEqual(result["regressionSources"]["baseline"]["status"], "unavailable")
                self.assert_unavailable(result["regressionEvidence"][0]["baseline"])

    def test_foreign_evidence_same_ids_and_boolean_repeat_cannot_make_links(self):
        source = Path(self.regression["samples"][0]["baseline"]["sourceEvidencePath"])
        copy = source.with_name("copied-evidence.json")
        copy.write_bytes(source.read_bytes())
        data = deepcopy(self.regression)
        data["samples"][0]["baseline"]["sourceEvidencePath"] = str(copy)
        self.assert_unavailable(self.document(data)["regressionEvidence"][0]["baseline"])
        data = deepcopy(self.regression)
        data["samples"][0]["baseline"]["repeatIndex"] = True
        self.assert_unavailable(self.document(data)["regressionEvidence"][0]["baseline"])
        data = deepcopy(self.regression)
        data["samples"][1] = deepcopy(data["samples"][0])
        for pair in self.document(data)["regressionEvidence"]:
            self.assert_unavailable(pair["baseline"])

    def test_identity_tampering_and_rejected_rows_disable_only_the_affected_side(self):
        for field, value in (("caseRunId", "../escape"), ("runId", "foreign-run"),
                             ("sessionId", "foreign-session"), ("sampleId", "foreign-sample"),
                             ("caseEntryId", "foreign-entry"), ("verification", "rejected")):
            data = deepcopy(self.regression)
            data["samples"][0]["candidate"][field] = value
            result = self.document(data)
            self.assert_unavailable(result["regressionEvidence"][0]["candidate"])
            self.assertEqual(result["regressionEvidence"][0]["baseline"]["status"], "available")

    def test_missing_or_mismatched_saved_evaluation_does_not_hide_valid_trace_evidence(self):
        descriptor = self.document()["regressionEvidence"][0]["candidate"]
        evaluation = self.browser.path(descriptor["evaluationId"])
        with self.changed(evaluation, lambda value: value["association"].update(runId="foreign")):
            result = self.document()["regressionEvidence"][0]["candidate"]
            self.assertEqual(result["status"], "available")
            self.assertNotIn("evaluationId", result)
            self.assertIn("assertionTrace", result)
            self.assertEqual(result["reasonCode"], "partial_evidence")

    def test_foreign_run_and_runtime_pointers_cannot_be_approved_through_raw_evidence(self):
        result = self.document()
        evidence = self.browser.path(result["regressionEvidence"][0]["baseline"]["evidenceId"])
        evaluation = self.browser.path(result["regressionEvidence"][0]["baseline"]["evaluationId"])
        foreign_evidence = self.browser.path(result["regressionEvidence"][0]["candidate"]["evidenceId"])
        foreign = foreign_evidence.parent
        foreign_run = self.browser.path(result["regressionEvidence"][0]["candidate"]["assertionTrace"]["id"]).parent
        with self.changed(evidence, lambda value: value.update(runDir=str(foreign_run))), \
                self.changed(evaluation, lambda value: value["association"].update(runDir=str(foreign_run))):
            self.assert_unavailable(self.document()["regressionEvidence"][0]["baseline"])
        for mutate in (lambda value: value.update(runtimeReport=str(foreign / "runtime.json")),
                       lambda value: value.update(sourceExperimentResult=str(foreign_evidence))):
            with self.changed(evidence, mutate):
                self.assert_unavailable(self.document()["regressionEvidence"][0]["baseline"])

    def test_saved_evaluation_rejects_extra_navigation_and_foreign_runtime_targets(self):
        result = self.document()
        evaluation = self.browser.path(result["regressionEvidence"][0]["baseline"]["evaluationId"])
        foreign = self.browser.path(result["regressionEvidence"][0]["candidate"]["evidenceId"]).parent
        for mutate in (lambda value: value["association"].update(runtimeReport=str(foreign / "runtime.json")),
                       lambda value: value["association"].update(sourceEvidencePath=str(foreign / "evidence.json")),
                       lambda value: value.update(sourceEvidencePath=str(foreign / "evidence.json")),
                       lambda value: value.update(samples=[{"runDir": str(foreign / "traces")}])):
            with self.changed(evaluation, mutate):
                descriptor = self.document()["regressionEvidence"][0]["baseline"]
                self.assertEqual(descriptor["status"], "available")
                self.assertNotIn("evaluationId", descriptor)
                self.assertIn("evidenceId", descriptor)
                self.assertIn("assertionTrace", descriptor)

    def test_recording_member_symlink_cannot_reopen_a_foreign_case_from_approved_json(self):
        result = self.document()
        trace = self.browser.path(result["regressionEvidence"][0]["baseline"]["assertionTrace"]["id"])
        foreign = self.browser.path(result["regressionEvidence"][0]["candidate"]["assertionTrace"]["id"])
        before = trace.read_bytes()
        trace.unlink()
        try:
            try:
                trace.symlink_to(foreign)
            except OSError as error:
                self.skipTest(f"Actual file symlink creation unavailable: {error}")
            self.assert_unavailable(self.document()["regressionEvidence"][0]["baseline"])
        finally:
            if trace.is_symlink():
                trace.unlink()
            trace.write_bytes(before)

    def test_recording_manifest_identity_mismatch_or_missing_disables_all_side_links(self):
        descriptor = self.document()["regressionEvidence"][0]["baseline"]
        manifest = self.browser.path(descriptor["assertionTrace"]["id"]).parent / "run.json"
        with self.changed(manifest, lambda value: value.update(runId="foreign-recording")):
            self.assert_unavailable(self.document()["regressionEvidence"][0]["baseline"])
        backup = manifest.with_name("backup-manifest.json")
        manifest.rename(backup)
        try:
            self.assert_unavailable(self.document()["regressionEvidence"][0]["baseline"])
        finally:
            backup.rename(manifest)

    @unittest.skipUnless(os.name == "nt", "Actual Windows directory junction behavior")
    def test_recording_directory_junction_cannot_redirect_an_unchanged_source_graph(self):
        document = self.document()
        original = self.browser.path(document["regressionEvidence"][0]["baseline"]["assertionTrace"]["id"]).parent
        foreign = self.browser.path(document["regressionEvidence"][0]["candidate"]["assertionTrace"]["id"]).parent
        backup = original.with_name("saved-original-run")
        copied = original.with_name(foreign.name)
        self.assertTrue(original.is_relative_to(self.base) and backup.is_relative_to(self.base) and copied.is_relative_to(self.base))
        shutil.copytree(foreign, copied)
        original.rename(backup)
        try:
            completed = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(original), str(copied)],
                                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
            if completed.returncode != 0:
                self.skipTest("Actual directory junction creation unavailable: " + completed.stderr.decode(errors="replace"))
            self.assertTrue(original.is_junction())
            self.assert_unavailable(self.document()["regressionEvidence"][0]["baseline"])
        finally:
            if original.is_junction():
                original.rmdir()  # Remove only this owned junction, never its target tree.
            backup.rename(original)

    def test_canonical_evidence_symlink_is_not_followed_even_inside_the_same_case(self):
        evidence = Path(self.regression["samples"][0]["candidate"]["sourceEvidencePath"])
        original = evidence.read_bytes()
        target = evidence.with_name("symlink-copy.json")
        target.write_bytes(original)
        evidence.unlink()
        try:
            try:
                evidence.symlink_to(target)
            except OSError as error:
                self.skipTest(f"Actual file symlink creation unavailable: {error}")
            self.assert_unavailable(self.document()["regressionEvidence"][0]["candidate"])
        finally:
            if evidence.is_symlink():
                evidence.unlink()
            evidence.write_bytes(original)

    def test_unsupported_versions_are_catalog_errors_and_error_results_remain_read_only(self):
        data = deepcopy(self.regression)
        data["regressionComparisonFormatVersion"] = 2
        path = self.save(self.directory / "artifacts/unsupported-output.json", data)
        item, = [row for row in self.browser.catalog()["items"] if row["id"] == self.browser.reference(path)]
        self.assertEqual(item["kind"], "unknown")
        self.assertIn("Unsupported regressionComparisonFormatVersion", item["error"])
        error = {"regressionComparisonFormatVersion": 1, "status": "error", "exitCode": 2,
                 "modelCalled": False, "error": "<img src=x onerror=alert(1)>"}
        self.assertEqual(self.document(error)["data"], error)

    def test_browsing_preserves_all_source_bytes(self):
        def digests():
            return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                    for name in ("inputs", "experiments") for path in (self.directory / name).rglob("*") if path.is_file()}
        before = digests()
        self.document()
        self.browser.catalog()
        self.assertEqual(before, digests())


class RegressionResumeBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_experiment_resume as fixtures
        from dsh_eval.experiment_resume import plan_experiment_resume, resume_experiment
        cls.fixture = fixtures.ExperimentResumeTests()
        cls.addClassCleanup(cls.fixture.doCleanups)
        cls.fixture.setUp()
        cls.fixture.crash("saved-evaluation")
        first = cls.fixture.execute(stop_after=2)
        cls.first = Path(first["resumeDirectory"]) / "experiment-resume-result.json"
        cls.v1 = compare_baseline(cls.first, cls.first, baseline_config="candidate", candidate_config="candidate")
        plan = plan_experiment_resume(cls.first)
        second = resume_experiment(cls.first, cls.fixture.directory / "again", expected_plan_sha256=plan["planFingerprint"]["sha256"])
        cls.second = Path(second["resumeDirectory"]) / "experiment-resume-result.json"
        cls.v2 = compare_baseline(cls.second, cls.second, baseline_config="candidate", candidate_config="candidate")
        cls.browser = ArtifactBrowser(cls.fixture.directory, cls.fixture.directory)

    def document(self, data):
        path = self.fixture.directory / (self._testMethodName + ".json")
        path.write_text(json.dumps(data), encoding="utf-8")
        return self.browser.document(self.browser.reference(path))

    def test_v1_binds_reused_checkpoint_and_new_samples_to_their_own_batches(self):
        result = self.document(self.v1)
        self.assertEqual(result["regressionSources"]["candidate"]["status"], "available")
        self.assertEqual([pair["candidate"]["status"] for pair in result["regressionEvidence"]],
                         ["available", "not_recorded", "available", "not_recorded"])
        recovered = result["regressionEvidence"][0]["candidate"]
        self.assertIn("evaluationId", recovered)
        self.assertIn("assertionTrace", recovered)

    def test_v2_binds_three_batches_and_reuses_checkpoint_from_the_original_batch(self):
        result = self.document(self.v2)
        self.assertEqual(result["regressionSources"]["candidate"]["status"], "available")
        self.assertTrue(all(pair["candidate"]["status"] == "available" for pair in result["regressionEvidence"]))
        ids = [pair["candidate"]["evidenceId"] for pair in result["regressionEvidence"]]
        self.assertEqual(len(set(ids)), 4)
        self.assertTrue(all(pair["candidate"].get("evaluationId") and pair["candidate"].get("assertionTrace")
                            for pair in result["regressionEvidence"]))

    def test_v2_cycle_and_forged_batch_provenance_disable_evidence_links(self):
        before = self.second.read_bytes()
        try:
            saved = load_json(self.second)
            saved["sourceResumeResult"] = str(self.second)
            self.second.write_text(json.dumps(saved), encoding="utf-8")
            result = self.document(self.v2)
            self.assertEqual(result["regressionSources"]["candidate"]["status"], "unavailable")
        finally:
            self.second.write_bytes(before)
        data = deepcopy(self.v2)
        data["samples"][0]["candidate"]["sourceBatchResult"] = data["samples"][-1]["candidate"]["sourceBatchResult"]
        result = self.document(data)
        self.assertEqual(result["regressionEvidence"][0]["candidate"]["status"], "unavailable")

    def test_terminal_chain_can_bind_legitimately_recovered_running_ancestors(self):
        import test_experiment_resume as fixtures
        from test_experiment_resume_chain import ExperimentResumeChainTests
        from dsh_eval.batch import _checkpoint
        chain = ExperimentResumeChainTests()
        self.addCleanup(chain.doCleanups)
        chain.setUp()
        abrupt = []
        def crash(directory, report):
            _checkpoint(directory, report)
            if report["entries"][0]["status"] == "finished":
                abrupt.append(directory / "batch-result.json")
                raise fixtures.SimulatedCrash
        with patch("dsh_eval.batch._checkpoint", side_effect=crash), self.assertRaises(fixtures.SimulatedCrash):
            chain.execute()
        child = abrupt[0].parents[2] / "resume-result.json"
        ancestor = child.parents[2] / "experiment-resume-result.json"
        self.assertEqual(load_json(ancestor)["status"], "running")
        latest = chain.execute(ancestor)
        latest_path = Path(latest["resumeDirectory"]) / "experiment-resume-result.json"
        comparison = compare_baseline(latest_path, latest_path, baseline_config="candidate", candidate_config="candidate")
        path = chain.fixture.directory / "running-ancestor-comparison.json"
        path.write_text(json.dumps(comparison), encoding="utf-8")
        browser = ArtifactBrowser(chain.fixture.directory, chain.fixture.directory)
        result = browser.document(browser.reference(path))
        self.assertEqual(result["regressionSources"]["candidate"]["status"], "available")
        self.assertTrue(all(pair["candidate"]["status"] == "available" for pair in result["regressionEvidence"]))
        # A nonterminal top-level source is still not a completed comparison input.
        comparison["candidate"]["sourceResult"] = str(ancestor)
        path.write_text(json.dumps(comparison), encoding="utf-8")
        self.assertEqual(browser.document(browser.reference(path))["regressionSources"]["candidate"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
