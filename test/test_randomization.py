"""Seeded scheduling and descriptive repeat distributions, without model calls."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from dsh_eval.experiment import ORDER, RANDOM_ORDER, plan_experiment, run_experiment
from dsh_eval.formats import load_json, validate_experiment
from dsh_eval.regression import compare_baseline
from dsh_eval.report import generate_report
from dsh_eval.runner import ROOT
from test_report import ReportFixture


class RandomizationTests(ReportFixture, unittest.TestCase):
    def preview(self):
        path = self.directory / "experiment.json"
        self.save(path, self.manifest)
        return plan_experiment(path)

    def test_optional_seed_is_strict_and_default_fingerprint_is_unchanged(self):
        original = copy.deepcopy(self.manifest)
        preview = self.preview()
        payload = {"version": 1, "manifest": original, "cases": [self.case], "maxSamples": None, "order": ORDER}
        expected = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        self.assertEqual(preview["planFingerprint"]["sha256"], expected)
        self.assertNotIn("randomSeed", preview)
        self.assertEqual([row["sampleId"] for row in preview["samples"]], [f"sample-{i:06}" for i in range(1, 5)])
        for seed in (0, 42, 9007199254740991):
            manifest = {**original, "randomSeed": seed}
            self.assertEqual(validate_experiment(manifest), manifest)
        for seed in (None, True, False, -1, 1.5, "42", 9007199254740992):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                validate_experiment({**original, "randomSeed": seed})
        self.assertEqual(self.manifest, original)

    def test_seeded_order_is_repeatable_and_preserves_canonical_sample_identity(self):
        self.manifest["cases"].append({"entryId": "second-case", "casePath": "case.json"})
        fixed = self.preview()
        fixed_identity = {row["sampleId"]: (row["caseEntryId"], row["configurationId"], row["repeatIndex"]) for row in fixed["samples"]}
        orders = []
        for seed in (0, 42):
            self.manifest["randomSeed"] = seed
            plan = self.preview()
            self.assertEqual(plan, self.preview())
            self.assertEqual((plan["order"], plan["randomSeed"]), (RANDOM_ORDER, seed))
            self.assertEqual({row["sampleId"]: (row["caseEntryId"], row["configurationId"], row["repeatIndex"]) for row in plan["samples"]}, fixed_identity)
            orders.append([row["sampleId"] for row in plan["samples"]])
        self.assertNotEqual(orders[0], orders[1])
        self.assertEqual(orders, [[f"sample-{index:06}" for index in indices]
                                 for indices in ([3, 5, 6, 1, 2, 8, 7, 4], [8, 3, 7, 4, 1, 6, 5, 2])])
        self.assertNotEqual(orders[0], [row["sampleId"] for row in fixed["samples"]])
        self.assertFalse((self.directory / "experiments").exists())

    def test_cli_seed_order_is_independent_of_python_hash_seed(self):
        self.manifest["randomSeed"] = 9007199254740991
        expected = self.preview()
        for hash_seed in ("1", "77"):
            process = subprocess.run([sys.executable, "-m", "dsh_eval", "--experiment", str(self.directory / "experiment.json"), "--plan"],
                                     cwd=ROOT, capture_output=True, encoding="utf-8", timeout=30,
                                     env={**os.environ, "PYTHONHASHSEED": hash_seed})
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout), expected)

    def test_seed_change_invalidates_preview_before_any_output_or_execution(self):
        self.manifest["randomSeed"] = 0
        plan = self.preview()
        self.manifest["randomSeed"] = 1
        self.save(self.directory / "experiment.json", self.manifest)
        with patch("dsh_eval.experiment.uuid4", side_effect=AssertionError("must not allocate")), \
                patch("dsh_eval.experiment.run_batch", side_effect=AssertionError("must not run")), \
                self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
            run_experiment(self.directory / "experiment.json", self.directory / "outputs", expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertFalse((self.directory / "outputs").exists())

    def test_execution_and_fresh_report_follow_the_preview_and_keep_exact_seed(self):
        self.manifest["randomSeed"] = 9007199254740991
        self.manifest["cases"].append({"entryId": "second-case", "casePath": "case.json"})
        preview = self.preview()
        self.experiment(expected_plan_sha256=preview["planFingerprint"]["sha256"])
        expected = [row["sampleId"] for row in preview["samples"]]
        self.assertEqual([row["sampleId"] for row in self.saved["samples"]], expected)
        self.assertEqual([row["entryId"] for row in self.batch["entries"]], expected)
        self.assertEqual(load_json(self.base / "experiment.json")["randomSeed"], self.manifest["randomSeed"])
        before = self.digest(self.base)
        report = generate_report(self.path, self.outputs)
        self.assertEqual(report["executionOrder"], {"order": RANDOM_ORDER, "randomSeed": self.manifest["randomSeed"]})
        self.assertEqual([row["sampleId"] for row in report["samples"]], expected)
        self.assertEqual(report["verificationCounts"], {"verified": 8})
        self.assertEqual(self.digest(self.base), before)
        text = (Path(report["reportDirectory"]) / "report.md").read_text(encoding="utf-8")
        self.assertIn("9007199254740991", text)
        self.assertIn("执行顺序与重复结果分布", text)

    def test_saved_seed_order_and_position_tampering_are_rejected(self):
        self.manifest["randomSeed"] = 42
        self.experiment()
        original = copy.deepcopy(self.saved)
        for change in ({"randomSeed": 43}, {"randomSeed": True}, {"order": ORDER}, {"order": "unknown-algorithm"}):
            self.save(self.path, {**original, **change})
            with self.subTest(change=change), self.assertRaises(ValueError):
                generate_report(self.path, self.outputs)
        missing = copy.deepcopy(original)
        missing.pop("randomSeed")
        self.save(self.path, missing)
        with self.assertRaises(ValueError):
            generate_report(self.path, self.outputs)
        self.saved = copy.deepcopy(original)
        self.saved["samples"].reverse()
        self.batch["entries"].reverse()
        self.persist()
        with self.assertRaisesRegex(ValueError, "position mismatch"):
            generate_report(self.path, self.outputs)
        self.assertFalse(self.outputs.exists())
        self.saved = copy.deepcopy(original)
        self.batch["entries"].reverse()
        replacement_id = self.saved["samples"][1]["sampleId"]
        self.saved["samples"][0].update(sampleId=replacement_id, entryId=replacement_id)
        self.batch["entries"][0]["entryId"] = replacement_id
        self.persist()
        with self.assertRaisesRegex(ValueError, "Randomized sample identity"):
            generate_report(self.path, self.outputs)

    def test_different_execution_seeds_are_visible_but_do_not_relabel_regression_pairs(self):
        self.manifest["randomSeed"] = 0
        self.experiment()
        baseline = self.path
        self.manifest["randomSeed"] = 42
        self.experiment()
        result = compare_baseline(baseline, self.path, baseline_config="first", candidate_config="first")
        self.assertEqual(result["exitCode"], 0)
        self.assertEqual(result["baseline"]["executionOrder"]["randomSeed"], 0)
        self.assertEqual(result["candidate"]["executionOrder"]["randomSeed"], 42)
        self.assertEqual([row["repeatIndex"] for row in result["samples"]], [1, 2])

    def test_two_continuations_keep_the_remaining_randomized_order(self):
        import test_experiment_resume as fixtures
        from dsh_eval.experiment_resume import plan_experiment_resume, resume_experiment
        fixture = fixtures.ExperimentResumeTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.manifest["randomSeed"] = 42
        fixture.save(fixture.path, fixture.manifest)
        preview = plan_experiment(fixture.path)
        expected = [row["sampleId"] for row in preview["samples"]]
        saved = run_experiment(fixture.path, fixture.directory / "original", stop_after=2,
                               expected_plan_sha256=preview["planFingerprint"]["sha256"])
        source = Path(saved["experimentDirectory"]) / "experiment-result.json"
        offset = 2
        for stop in (2, None):
            plan = plan_experiment_resume(source)
            self.assertEqual([row["sampleId"] for row in plan["samples"] if row["disposition"] == "pending"], expected[offset:])
            result = resume_experiment(source, fixture.directory / "resumes", stop_after=stop,
                                       expected_plan_sha256=plan["planFingerprint"]["sha256"])
            source = Path(result["resumeDirectory"]) / "experiment-resume-result.json"
            offset += stop or len(expected) - offset
        before = self.digest(fixture.directory)
        report = generate_report(source, fixture.directory / "reports")
        self.assertEqual(report["comparisonReportFormatVersion"], 3)
        self.assertEqual([row["sampleId"] for row in report["samples"]], expected)
        self.assertEqual(report["executionOrder"], {"order": RANDOM_ORDER, "randomSeed": 42})
        self.assertEqual(report["verificationCounts"], {"verified": 8})
        self.assertEqual(len(set(fixture.called)), 8)
        after = self.digest(fixture.directory)
        self.assertTrue(all(after[path] == digest for path, digest in before.items()))
        self.assertTrue(all(item["sourceSamples"] == 2 and item["eligiblePassed"] == 2 for item in report["repeatDistributions"]))

    def test_resume_seed_and_plan_tampering_reject_before_claim_and_remain_retryable(self):
        import test_experiment_resume as fixtures
        from dsh_eval.experiment_resume import plan_experiment_resume, resume_experiment
        from dsh_eval.resume import CLAIM_NAME
        fixture = fixtures.ExperimentResumeTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.manifest["randomSeed"] = 0
        fixture.save(fixture.path, fixture.manifest)
        saved = run_experiment(fixture.path, fixture.directory / "original", stop_after=1)
        base = Path(saved["experimentDirectory"])
        source = base / "experiment-result.json"
        plan = plan_experiment_resume(source)
        self.assertTrue(plan["eligibleForResume"], plan)
        payload_path = base / saved["planInputPath"]
        original_payload = payload_path.read_bytes()
        original_result = source.read_bytes()
        root = fixture.directory / "rejected-resume"
        claim = (base / saved["batchResultPath"]).parent / CLAIM_NAME
        for mutation in ("boolean-zero", "changed-plan-seed"):
            with self.subTest(mutation=mutation):
                source.write_bytes(original_result)
                payload_path.write_bytes(original_payload)
                if mutation == "boolean-zero":
                    self.save(source, {**saved, "randomSeed": False})
                else:
                    payload = load_json(payload_path)
                    payload["manifest"]["randomSeed"] = 1
                    self.save(payload_path, payload)
                before = self.digest(base)
                with patch("dsh_eval.experiment_resume.uuid4", side_effect=AssertionError("must not allocate")), \
                        self.assertRaises(ValueError):
                    resume_experiment(source, root, expected_plan_sha256=plan["planFingerprint"]["sha256"])
                self.assertFalse(claim.exists())
                self.assertFalse(root.exists())
                self.assertEqual(self.digest(base), before)
        source.write_bytes(original_result)
        payload_path.write_bytes(original_payload)
        restored = plan_experiment_resume(source)
        self.assertTrue(restored["eligibleForResume"])
        self.assertEqual(restored["planFingerprint"], plan["planFingerprint"])


class RepeatDistributionTests(ReportFixture, unittest.TestCase):
    def test_case_entries_sharing_a_case_id_keep_separate_denominators(self):
        self.manifest.update(randomSeed=0, repetitions=2)
        self.manifest["configurations"] = self.manifest["configurations"][:1]
        self.manifest["cases"].append({"entryId": "alias", "casePath": "case.json"})
        self.experiment()
        self.assertEqual(len({row["caseId"] for row in self.saved["samples"]}), 1)
        failed = next(i for i, row in enumerate(self.saved["samples"]) if row["caseEntryId"] == "alias" and row["repeatIndex"] == 1)
        def fail(events):
            row = next(event for event in reversed(events) if event["type"] == "assistant/message")
            row["data"]["message"]["content"] = [{"type": "text", "text": "WRONG"}]
        self.rerecord(failed, fail)
        missing = next(row for row in self.saved["samples"] if row["caseEntryId"] == "retry" and row["repeatIndex"] == 2)
        (self.base / missing["evidencePath"]).unlink()
        before = self.digest(self.base)
        report = generate_report(self.path, self.outputs)
        for entry_id in ("retry", "alias"):
            rows = [row for row in report["repeatDistributions"] if row["caseEntryId"] == entry_id]
            self.assertEqual(sum(row["sourceSamples"] for row in rows), 2)
            self.assertTrue(all(row["plannedRepetitions"] == 2 for row in rows))
            self.assertEqual(sorted(sample["repeatIndex"] for row in rows for sample in row["samples"]), [1, 2])
        alias = next(row for row in report["repeatDistributions"] if row["caseEntryId"] == "alias")
        self.assertEqual((alias["eligiblePassed"], alias["eligibleFailed"], alias["excludedSamples"]), (1, 1, 0))
        retry = [row for row in report["repeatDistributions"] if row["caseEntryId"] == "retry"]
        self.assertEqual(sum(row["eligiblePassed"] for row in retry), 1)
        self.assertEqual(sum(row["eligibleFailed"] for row in retry), 0)
        self.assertEqual(sum(row["excludedSamples"] for row in retry), 1)
        self.assertEqual(self.digest(self.base), before)

    def test_mixed_results_missing_evidence_and_sources_remain_separate(self):
        self.manifest.update(randomSeed=42, repetitions=3)
        self.experiment()
        def index(config, repeat):
            return next(i for i, row in enumerate(self.saved["samples"]) if row["configurationId"] == config and row["repeatIndex"] == repeat)
        def fail(events):
            final = next(event for event in reversed(events) if event["type"] == "assistant/message")
            final["data"]["message"]["content"] = [{"type": "text", "text": "WRONG"}]
        self.rerecord(index("first", 2), fail)
        (self.base / self.saved["samples"][index("first", 3)]["evidencePath"]).unlink()
        # Deliberately vary the saved source declaration; these remain synthetic test tasks.
        self.source(index("second", 2), "live")
        self.persist()
        report = generate_report(self.path, self.outputs)
        rows = {(item["configurationId"], item["source"]): item for item in report["repeatDistributions"]}
        first = rows[("first", "synthetic")]
        self.assertEqual(first["outcomes"], {"passed": 1, "failed": 1, "unevaluable": 0, "missing": 0})
        self.assertEqual((first["sourceSamples"], first["plannedRepetitions"], first["eligiblePassed"], first["eligibleFailed"]), (2, 3, 1, 1))
        self.assertEqual([sample["repeatIndex"] for sample in first["samples"]], [1, 2])
        missing = rows[("first", "unknown")]
        self.assertEqual((missing["sourceSamples"], missing["excludedSamples"], missing["outcomes"]["unevaluable"]), (1, 1, 1))
        self.assertEqual(rows[("second", "live")]["sourceSamples"], 1)
        self.assertEqual(rows[("second", "synthetic")]["sourceSamples"], 2)
        for item in rows.values():
            self.assertEqual(sum(item["outcomes"].values()), item["sourceSamples"])
            self.assertEqual(item["eligiblePassed"] + item["eligibleFailed"] + item["excludedSamples"], item["sourceSamples"])

    def test_skipped_and_route_mismatches_are_not_effective_passes_or_failures(self):
        self.experiment(stop_after=1)
        def route(events):
            next(event for event in events if event["type"] == "request/header")["data"]["header"]["config"]["model"] = "unexpected"
        self.rerecord(0, route)
        report = generate_report(self.path, self.outputs)
        distributions = report["repeatDistributions"]
        self.assertEqual(sum(item["eligiblePassed"] + item["eligibleFailed"] for item in distributions), 0)
        self.assertEqual(sum(item["excludedSamples"] for item in distributions), 4)
        self.assertEqual(sum(item["outcomes"]["missing"] for item in distributions), 3)
        self.assertEqual(sum(item["statusCounts"].get("skipped", 0) for item in distributions), 3)
        self.assertEqual(report["executionOrder"], {"order": ORDER})


if __name__ == "__main__":
    unittest.main()
