"""Directory packages preserve raw experiment proofs while reading only listed payload files."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dsh_eval.archive_bundle import MANIFEST, export_archive, load_archive, verify_archive
from dsh_eval.archive_paths import archive_read_context
from dsh_eval.assertion_comparison import compare_assertions
from dsh_eval.environment import snapshot_digest
from dsh_eval.experiment import run_experiment
from dsh_eval.experiment_assertion_preview import preview_experiment_assertions
from dsh_eval.experiment_resume import plan_experiment_resume, resume_experiment
from dsh_eval.formats import load_json
from dsh_eval.report import _load_report_inputs, generate_report
from dsh_eval.runner import ROOT, save_json
import test_experiment_resume as resume_fixtures


def hashes(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


class ArchiveBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="dsh-package-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.base = Path(cls.temporary.name).resolve()
        inputs = cls.base / "inputs"
        inputs.mkdir()
        case = load_json(ROOT / "fixtures/evaluation/rename-confirmation.case.json")
        case["configRef"].update(provider="synthetic", model="scripted")
        save_json(inputs / "rename.case.json", case)
        manifest = {"experimentFormatVersion": 1, "experimentName": "portable synthetic experiment",
                    "repetitions": 1, "failurePolicy": "continue",
                    "cases": [{"entryId": "rename", "casePath": "rename.case.json"}],
                    "configurations": [{"configurationId": "scripted", "configRef": case["configRef"]}]}
        save_json(inputs / "experiment.json", manifest)
        result = run_experiment(inputs / "experiment.json", cls.base / "source",
                                _synthetic_replies={"sample-000001": "**done**"})
        cls.source = Path(result["experimentDirectory"])
        cls.entry = cls.source / "experiment-result.json"
        report = generate_report(cls.entry, cls.base / "reports")
        cls.report = Path(report["reportDirectory"]) / "report.json"
        artifacts = cls.base / "artifacts"
        artifacts.mkdir()
        saved_case = cls.source / result["samples"][0]["caseDirectory"] / "case.json"
        candidate = load_json(saved_case)
        next(row for row in candidate["assertions"] if row["id"] == "answer").pop("match")
        cls.candidate = artifacts / "strict.case.json"
        save_json(cls.candidate, candidate)
        evidence = cls.source / result["samples"][0]["evidencePath"]
        comparison = compare_assertions(evidence, cls.candidate)
        cls.comparison = artifacts / "assertion-comparison.json"
        save_json(cls.comparison, comparison)
        rules = artifacts / "rules.json"
        save_json(rules, {"assertionRuleMapFormatVersion": 1, "cases": {"rename": candidate["assertions"]}})
        preview = preview_experiment_assertions(cls.entry, rules)
        cls.preview = artifacts / "experiment-assertion-preview.json"
        save_json(cls.preview, preview)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsh-package-output-")
        self.addCleanup(temporary.cleanup)
        self.output_parent = Path(temporary.name)
        self.package = self.output_parent / "package"

    def export(self, artifacts=()):
        before = hashes(self.source)
        manifest = export_archive(self.entry, self.base, self.package, artifacts=artifacts)
        self.assertEqual(hashes(self.source), before)
        return manifest

    def test_ordinary_package_closure_preserves_bytes_and_excludes_process_private_content(self):
        manifest = self.export()
        self.assertEqual((manifest["archiveBundleFormatVersion"], manifest["modelCalled"]), (1, False))
        self.assertEqual(manifest["logicalSourceRoot"], str(self.base))
        self.assertEqual(manifest["entryPath"], "payload/" + self.entry.relative_to(self.base).as_posix())
        self.assertEqual(verify_archive(self.package)["status"], "verified")
        for row in manifest["files"]:
            original = self.base / row["path"].removeprefix("payload/")
            copied = self.package / row["path"]
            self.assertEqual(copied.read_bytes(), original.read_bytes())
            self.assertEqual(row["size"], len(copied.read_bytes()))
            self.assertFalse(any(part in ("home", "workspace", "node_modules", "private-notes")
                                 for part in Path(row["path"]).parts))
            self.assertFalse(row["path"].endswith((".log", "adapter.stdout.jsonl", "host-result.json", "synthetic.json")))
        self.assertTrue(any(row["path"].endswith("expanded.batch.json") for row in manifest["files"]))
        self.assertTrue(any(row["path"].endswith(".status.json") for row in manifest["files"]))

    def test_selected_report_comparison_preview_dependencies_survive_multiple_package_copies(self):
        manifest = self.export([self.report, self.comparison, self.preview])
        moved = self.output_parent / "moved-package"
        shutil.copytree(self.package, moved)
        again = self.output_parent / "second-copy"
        shutil.copytree(moved, again)
        hidden = self.base.with_name(self.base.name + "-unavailable")
        self.assertEqual(hidden.parent, self.base.parent)
        expected_id = load_json(self.entry)["experimentId"]
        self.base.rename(hidden)
        try:
            for selected in (moved, again):
                loaded, resolver = load_archive(selected)
                self.assertEqual(loaded, manifest)
                self.assertEqual(verify_archive(selected)["verifiedFiles"], len(manifest["files"]))
                with archive_read_context(resolver):
                    context = _load_report_inputs(resolver.payload_root / loaded["entryPath"].removeprefix("payload/"))
                    self.assertEqual(context[0]["experimentId"], expected_id)
                    self.assertEqual(context[3]["status"], "verified")
                for row in manifest["files"]:
                    self.assertEqual(hashlib.sha256((selected / row["path"]).read_bytes()).hexdigest(), row["sha256"])
        finally:
            hidden.rename(self.base)

    def test_missing_changed_and_unlisted_payload_files_or_directories_are_rejected(self):
        manifest = self.export()
        target = self.package / manifest["files"][0]["path"]
        original = target.read_bytes()
        target.write_bytes(original + b"changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            load_archive(self.package)
        target.write_bytes(original)
        target.unlink()
        with self.assertRaisesRegex(ValueError, "inventory"):
            load_archive(self.package)
        target.write_bytes(original)
        unexpected = self.package / "payload/extra.json"
        unexpected.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inventory"):
            load_archive(self.package)
        unexpected.unlink()
        extra = self.package / "payload/empty-extra"
        extra.mkdir()
        with self.assertRaisesRegex(ValueError, "inventory"):
            load_archive(self.package)

    def test_manifest_paths_versions_and_unknown_selected_artifacts_are_rejected(self):
        manifest = self.export()
        file = self.package / MANIFEST
        for change in ({"archiveBundleFormatVersion": True}, {"entryPath": "payload/../outside.json"},
                       {"logicalSourceRoot": "../old"}, {"entryPath": []}):
            with self.subTest(change=change):
                file.write_text(json.dumps({**manifest, **change}), encoding="utf-8")
                with self.assertRaises((ValueError, TypeError)):
                    load_archive(file)
        file.write_text(json.dumps(manifest), encoding="utf-8")
        invalid = self.output_parent / "unknown-package"
        with self.assertRaisesRegex(ValueError, "Unsupported selected"):
            export_archive(self.entry, self.base, invalid, artifacts=[self.candidate])
        self.assertFalse(invalid.exists())

    def test_output_conflicts_and_output_inside_source_archive_leave_source_unchanged(self):
        self.export()
        before = hashes(self.source)
        with self.assertRaisesRegex(ValueError, "already exists"):
            export_archive(self.entry, self.base, self.package)
        inside = self.source / "forbidden-new-package"
        with self.assertRaisesRegex(ValueError, "outside selected"):
            export_archive(self.entry, self.base, inside)
        self.assertFalse(inside.exists())
        self.assertEqual(hashes(self.source), before)

    def test_selected_artifact_wrong_identity_and_outside_dependency_fail_before_output(self):
        fake = self.base / (self.output_parent.name + "-wrong-report.json")
        self.addCleanup(fake.unlink, missing_ok=True)
        report = load_json(self.report)
        report["experimentId"] = "other-experiment"
        save_json(fake, report)
        with self.assertRaisesRegex(ValueError, "not bound"):
            export_archive(self.entry, self.base, self.package, artifacts=[fake])
        self.assertFalse(self.package.exists())
        comparison = load_json(self.comparison)
        comparison["candidate"]["casePath"] = str(self.output_parent / "outside.case.json")
        fake.unlink()
        save_json(fake, comparison)
        with self.assertRaisesRegex(ValueError, "outside source root"):
            export_archive(self.entry, self.base, self.package, artifacts=[fake])
        self.assertFalse(self.package.exists())

    def test_report_or_preview_cannot_pull_a_forged_sample_from_the_common_root(self):
        for source in (self.report, self.preview):
            data = load_json(source)
            data["samples"][0]["caseRunId"] = "other-case"
            fake = source.parent / (self.output_parent.name + "-forged.json")
            self.addCleanup(fake.unlink, missing_ok=True)
            save_json(fake, data)
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "selected|identity"):
                export_archive(self.entry, self.base, self.package, artifacts=[fake])
            self.assertFalse(self.package.exists())

    def test_comparison_baseline_and_non_assertion_candidate_changes_are_rejected(self):
        comparison = load_json(self.comparison)
        comparison["baseline"]["casePath"] = str(self.candidate)
        comparison["baseline"]["caseSha256"] = comparison["candidate"]["caseSha256"]
        fake = self.comparison.parent / (self.output_parent.name + "-comparison.json")
        self.addCleanup(fake.unlink, missing_ok=True)
        save_json(fake, comparison)
        with self.assertRaisesRegex(ValueError, "sibling case.json"):
            export_archive(self.entry, self.base, self.package, artifacts=[fake])
        fake.unlink()
        candidate = load_json(self.candidate)
        candidate["input"] += " changed task"
        changed = self.candidate.parent / (self.output_parent.name + "-changed.case.json")
        self.addCleanup(changed.unlink, missing_ok=True)
        save_json(changed, candidate)
        comparison = load_json(self.comparison)
        comparison["candidate"]["casePath"] = str(changed)
        comparison["candidate"]["caseSha256"] = snapshot_digest(candidate)
        save_json(fake, comparison)
        with self.assertRaisesRegex(ValueError, "only assertions"):
            export_archive(self.entry, self.base, self.package, artifacts=[fake])

    def test_missing_declared_recording_file_is_not_silently_omitted(self):
        sample = load_json(self.entry)["samples"][0]
        recording = self.source / sample["runDir"]
        trace, = recording.glob("*.jsonl")
        hidden = trace.with_suffix(".saved")
        trace.rename(hidden)
        try:
            with self.assertRaisesRegex(ValueError, "Missing archive dependency"):
                export_archive(self.entry, self.base, self.package)
            self.assertFalse(self.package.exists())
        finally:
            hidden.rename(trace)

    def test_report_batch_links_cannot_expand_the_selected_chain_with_another_copy(self):
        result = load_json(self.entry)
        batch = self.source / result["batchResultPath"]
        foreign = self.base / (self.output_parent.name + "-foreign-batch")
        shutil.copytree(batch.parent, foreign)
        self.addCleanup(shutil.rmtree, foreign, True)
        fake = self.report.parent / (self.output_parent.name + "-foreign-batch-report.json")
        self.addCleanup(fake.unlink, missing_ok=True)
        for key in ("sample", "all"):
            report = load_json(self.report)
            if key == "sample":
                report["samples"][0]["sourceBatchResult"] = str(foreign / "batch-result.json")
            else:
                report["batchResultPaths"] = [str(foreign / "batch-result.json")]
            fake.write_text(json.dumps(report), encoding="utf-8")
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "Report batch is outside"):
                export_archive(self.entry, self.base, self.package, artifacts=[fake])
            self.assertFalse(self.package.exists())

    def test_preview_keeps_the_original_verified_plan_and_exact_rule_map_contract(self):
        fake = self.preview.parent / (self.output_parent.name + "-preview.json")
        rules = self.preview.parent / (self.output_parent.name + "-rules.json")
        self.addCleanup(fake.unlink, missing_ok=True)
        self.addCleanup(rules.unlink, missing_ok=True)
        for mode, reason in (("plan", "plan fingerprint"), ("extra", "Unknown fields"), ("entries", "exactly")):
            data = load_json(self.preview)
            mapping = load_json(data["ruleMapPath"])
            if mode == "plan":
                data["planFingerprint"]["sha256"] = "0" * 64
            elif mode == "extra":
                mapping["unrelatedPrivateNote"] = "must not enter the package"
            else:
                mapping["cases"] = {}
            rules.write_text(json.dumps(mapping), encoding="utf-8")
            data["ruleMapPath"] = str(rules)
            data["ruleMapSha256"] = snapshot_digest(mapping)
            fake.write_text(json.dumps(data), encoding="utf-8")
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, reason):
                export_archive(self.entry, self.base, self.package, artifacts=[fake])
            self.assertFalse(self.package.exists())

    def test_changed_input_during_actual_copy_leaves_an_unpublished_output(self):
        copy = shutil.copyfileobj
        changed = []

        def change_after_copy(source, destination, *args, **kwargs):
            copy(source, destination, *args, **kwargs)
            if not changed:
                path = Path(source.name)
                changed.append((path, path.read_bytes()))
                path.write_bytes(changed[0][1] + b" ")

        try:
            with patch("dsh_eval.archive_bundle.shutil.copyfileobj", side_effect=change_after_copy):
                with self.assertRaisesRegex(ValueError, "changed after copy"):
                    export_archive(self.entry, self.base, self.package)
            self.assertTrue(self.package.is_dir())
            self.assertFalse((self.package / MANIFEST).exists())
        finally:
            for path, original in changed:
                path.write_bytes(original)

    def test_primary_mutation_after_initial_semantic_check_is_rejected_before_publication(self):
        from dsh_eval import archive_bundle as module
        original = module._Closure.context
        before = self.entry.read_bytes()
        changed = False

        def change_after_context(closure, path):
            nonlocal changed
            result = original(closure, path)
            if not changed:
                data = load_json(self.entry)
                data["experimentName"] += " invalid after validation"
                self.entry.write_text(json.dumps(data), encoding="utf-8")
                changed = True
            return result

        try:
            with patch.object(module._Closure, "context", change_after_context):
                with self.assertRaisesRegex(ValueError, "experimentName mismatch"):
                    export_archive(self.entry, self.base, self.package)
            self.assertTrue(changed)
            self.assertTrue(self.package.is_dir())
            self.assertFalse((self.package / MANIFEST).exists())
        finally:
            self.entry.write_bytes(before)

    def test_report_evaluation_cannot_pull_same_identity_evidence_from_a_different_location(self):
        report = load_json(self.report)
        evaluation = load_json(Path(report["reportDirectory"]) / report["samples"][0]["evaluationPath"])
        evidence = load_json(evaluation["association"]["evidencePath"])
        evidence["unrelatedPrivateNote"] = "must not enter the package"
        directory = self.base / (self.output_parent.name + "-foreign")
        directory.mkdir()
        self.addCleanup(shutil.rmtree, directory, True)
        save_json(directory / "evidence.json", evidence)
        evaluation["association"]["evidencePath"] = str(directory / "evidence.json")
        save_json(directory / "evaluation.json", evaluation)
        report["samples"][0]["evaluationPath"] = str(directory / "evaluation.json")
        fake = self.report.parent / (self.output_parent.name + "-foreign-report.json")
        self.addCleanup(fake.unlink, missing_ok=True)
        save_json(fake, report)
        with self.assertRaisesRegex(ValueError, "Evaluation evidence is outside"):
            export_archive(self.entry, self.base, self.package, artifacts=[fake])
        self.assertFalse(self.package.exists())

    def test_saved_evaluation_case_runtime_and_recording_must_follow_its_canonical_evidence(self):
        report = load_json(self.report)
        evaluation = load_json(Path(report["reportDirectory"]) / report["samples"][0]["evaluationPath"])
        directory = self.base / (self.output_parent.name + "-other-inputs")
        directory.mkdir()
        self.addCleanup(shutil.rmtree, directory, True)
        shutil.copyfile(evaluation["association"]["casePath"], directory / "case.json")
        runtime = load_json(evaluation["association"]["runtimeReport"])
        runtime["unrelatedPrivateNote"] = "must not enter the package"
        save_json(directory / "runtime.json", runtime)
        shutil.copytree(evaluation["association"]["runDir"], directory / "recording")
        fake = self.report.parent / (self.output_parent.name + "-other-inputs-report.json")
        self.addCleanup(fake.unlink, missing_ok=True)
        report["samples"][0]["evaluationPath"] = str(directory / "evaluation.json")
        save_json(fake, report)
        for key, target, reason in (("casePath", directory / "case.json", "case is outside"),
                                    ("runtimeReport", directory / "runtime.json", "runtime differs"),
                                    ("runDir", directory / "recording", "recording differs")):
            changed = deepcopy(evaluation)
            changed["association"][key] = str(target)
            (directory / "evaluation.json").write_text(json.dumps(changed), encoding="utf-8")
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, reason):
                export_archive(self.entry, self.base, self.package, artifacts=[fake])
            self.assertFalse(self.package.exists())

    def test_cli_verify_returns_explicit_failure_without_overwriting_payload(self):
        self.export()
        process = subprocess.run([sys.executable, "-m", "dsh_eval.archive_bundle", "verify", str(self.package)],
                                 cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=45)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertFalse(json.loads(process.stdout)["modelCalled"])
        (self.package / "payload/unlisted.json").write_text("{}", encoding="utf-8")
        process = subprocess.run([sys.executable, "-m", "dsh_eval.archive_bundle", "verify", str(self.package)],
                                 cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=45)
        self.assertEqual((process.returncode, json.loads(process.stdout)["status"]), (2, "error"))


class ArchiveContinuationTests(unittest.TestCase):
    def test_recovered_running_ancestor_keeps_canonical_saved_evidence_in_the_package(self):
        fixture = resume_fixtures.ExperimentResumeTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.manifest["configurations"] = fixture.manifest["configurations"][:1]
        fixture.manifest["repetitions"] = 2
        fixture.save(fixture.path, fixture.manifest)
        fixture.crash("saved-evaluation")
        self.assertIsNone(load_json(fixture.source)["batchResultPath"])
        plan = plan_experiment_resume(fixture.source)
        continued = resume_experiment(fixture.source, fixture.directory / "resumes",
                                      expected_plan_sha256=plan["planFingerprint"]["sha256"])
        entry = Path(continued["resumeDirectory"]) / "experiment-resume-result.json"
        before = hashes(fixture.directory)
        with tempfile.TemporaryDirectory(prefix="dsh-recovered-package-") as temporary:
            package = Path(temporary) / "package"
            manifest = export_archive(entry, fixture.directory, package)
            self.assertEqual(hashes(fixture.directory), before)
            hidden = fixture.directory.with_name(fixture.directory.name + "-unavailable")
            self.assertEqual(hidden.parent, fixture.directory.parent)
            fixture.directory.rename(hidden)
            try:
                self.assertEqual(verify_archive(package)["verifiedFiles"], len(manifest["files"]))
            finally:
                hidden.rename(fixture.directory)

    def test_selected_continuation_chain_keeps_raw_plans_claims_and_fingerprints_after_move(self):
        fixture = resume_fixtures.ExperimentResumeTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.manifest["configurations"] = fixture.manifest["configurations"][:1]
        fixture.manifest["repetitions"] = 2
        fixture.save(fixture.path, fixture.manifest)
        original = run_experiment(fixture.path, fixture.directory / "originals", stop_after=1)
        original_path = Path(original["experimentDirectory"]) / "experiment-result.json"
        first_plan = plan_experiment_resume(original_path)
        first = resume_experiment(original_path, fixture.directory / "first", stop_after=1,
                                  expected_plan_sha256=first_plan["planFingerprint"]["sha256"])
        first_path = Path(first["resumeDirectory"]) / "experiment-resume-result.json"
        second_plan = plan_experiment_resume(first_path)
        second = resume_experiment(first_path, fixture.directory / "second",
                                   expected_plan_sha256=second_plan["planFingerprint"]["sha256"])
        second_path = Path(second["resumeDirectory"]) / "experiment-resume-result.json"
        before = hashes(fixture.directory)
        package = fixture.directory.parent / (fixture.directory.name + "-package")
        self.addCleanup(shutil.rmtree, package, True)
        manifest = export_archive(second_path, fixture.directory, package)
        self.assertEqual(hashes(fixture.directory), before)
        self.assertEqual(sum(row["path"].endswith(".batch-resume-claim.json") for row in manifest["files"]), 2)
        fake_preview = fixture.directory / "invalid-experiment-preview.json"
        fixture.save(fake_preview, {"experimentAssertionPreviewFormatVersion": 1,
                                   "experimentId": original["experimentId"], "experimentPath": str(second_path)})
        with self.assertRaisesRegex(ValueError, "completed ordinary"):
            export_archive(second_path, fixture.directory, package.with_name(package.name + "-invalid"),
                           artifacts=[fake_preview])
        fake_preview.unlink()
        moved = package.with_name(package.name + "-moved")
        self.addCleanup(shutil.rmtree, moved, True)
        shutil.copytree(package, moved)
        hidden = fixture.directory.with_name(fixture.directory.name + "-unavailable")
        self.assertEqual(hidden.parent, fixture.directory.parent)
        fixture.directory.rename(hidden)
        try:
            self.assertEqual(verify_archive(moved)["status"], "verified")
            loaded, resolver = load_archive(moved)
            with archive_read_context(resolver):
                context = _load_report_inputs(resolver.payload_root / loaded["entryPath"].removeprefix("payload/"))
                self.assertEqual(context[5]["comparisonReportFormatVersion"], 3)
                self.assertEqual(len(list(context[4])), 4)
            self.assertEqual(hashes(hidden), before)
        finally:
            hidden.rename(fixture.directory)


if __name__ == "__main__":
    unittest.main()
