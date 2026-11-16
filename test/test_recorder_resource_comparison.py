"""Exercise paired resource comparison against real, independent recorder runs."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts import compare_recorder_resources as comparison


ROOT = Path(__file__).resolve().parents[1]


class RecorderResourceComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="dsh-recorder-compare-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name).resolve()
        for side in ("baseline", "candidate"):
            result = subprocess.run(["node", "scripts/measure-recorder.js", "--scenarios", "sessions-100",
                                     "--repeats", "2", "--output-dir", str(cls.directory / side)],
                                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=90)
            if result.returncode != 0:
                raise AssertionError(f"real measurement failed: {result.stdout}\n{result.stderr}")

    def setUp(self):
        self.case = self.directory / self._testMethodName
        self.case.mkdir()
        for side in ("baseline", "candidate"):
            shutil.copytree(self.directory / side, self.case / side)
        self.baseline = self.case / "baseline/summary.json"
        self.candidate = self.case / "candidate/summary.json"
        self.output = self.case / "comparison.json"
        # Each test owns real frozen copies, including the inspector's separate recorder dependency.
        for side, path in (("baseline", self.baseline), ("candidate", self.candidate)):
            def relocate(summary):
                for group, info in summary["provenance"].items():
                    directory = self.case / "sources" / side / group / "src"
                    directory.mkdir(parents=True)
                    for row in info["files"]:
                        target = (directory / row["name"]).resolve()
                        shutil.copyfile(row["path"], target)
                        row["path"] = str(target)
                for sample in summary["samples"]:
                    sample["provenance"] = deepcopy(summary["provenance"])
            self.change(path, relocate)

    def read(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def write(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def change(self, path, mutate):
        summary = self.read(path)
        mutate(summary)
        self.write(path, summary)
        for sample in summary["samples"]:
            self.write((path.parent / sample["runDirectory"]).parent / "measurement.json", sample)

    def invoke(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = comparison.main(["--baseline", str(self.baseline), "--candidate", str(self.candidate),
                                      "--output", str(self.output)])
        return status, stdout.getvalue(), stderr.getvalue()

    def reject(self, expected):
        status, _, stderr = self.invoke()
        self.assertEqual(status, 2, stderr)
        self.assertIn(expected, stderr)
        self.assertFalse(self.output.exists())

    def hashes(self):
        return {str(path.relative_to(self.case)): hashlib.sha256(path.read_bytes()).hexdigest()
                for side in ("baseline", "candidate", "sources") for path in (self.case / side).rglob("*") if path.is_file()}

    def test_real_pair_has_equal_normalized_content_preserves_raw_differences_and_sources(self):
        before = self.hashes()
        result = subprocess.run([sys.executable, str(ROOT / "scripts/compare_recorder_resources.py"),
                                 "--baseline", str(self.baseline), "--candidate", str(self.candidate),
                                 "--output", str(self.output)], cwd=ROOT, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = self.read(self.output)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(len(report["pairs"]), 2)
        self.assertTrue(report["sourceBytesUnchanged"])
        self.assertFalse(report["recorderSourceChanged"])
        self.assertEqual(self.hashes(), before)
        for pair in report["pairs"]:
            self.assertTrue(pair["normalizedFilesMatch"] and pair["normalizedInspectionMatch"])
            self.assertFalse(pair["rawBytesIdentical"])
            self.assertTrue(pair["rawFileHashDifferences"])
        metric = report["scenarios"][0]["metrics"]["closeMs"]
        self.assertEqual(metric["delta"]["count"], 2)

    def test_paired_statistics_zero_denominator_and_no_delay_samples_are_explicit(self):
        for path, values in ((self.baseline, [0, 20]), (self.candidate, [10, 10])):
            def mutate(summary):
                for sample, value in zip(summary["samples"], values):
                    sample["closeMs"] = value
                    delay = sample["eventLoop"]["delay"]
                    for field in delay:
                        if field not in ("count", "resolutionMs"):
                            delay[field] = None
                    delay["count"] = 0
            self.change(path, mutate)
        status, _, stderr = self.invoke()
        self.assertEqual(status, 0, stderr)
        report = self.read(self.output)
        pairs = report["pairs"]
        self.assertEqual([row["metrics"]["closeMs"]["delta"] for row in pairs], [10, -10])
        self.assertEqual([row["metrics"]["closeMs"]["percentChange"] for row in pairs], [None, -50])
        metrics = report["scenarios"][0]["metrics"]
        self.assertEqual(metrics["closeMs"]["delta"], {"count": 2, "median": 0.0, "min": -10, "max": 10})
        self.assertEqual(metrics["eventLoop.delay.p99Ms"]["delta"], {"count": 0, "median": None, "min": None, "max": None})

    def test_missing_duplicate_and_unfinished_samples_are_rejected(self):
        original = self.read(self.candidate)
        variants = [({**deepcopy(original), "samples": original["samples"][:-1]}, "missing scenario/repeat"),
                    ({**deepcopy(original), "samples": [original["samples"][0]] * 2}, "duplicate sample"),
                    ({**deepcopy(original), "status": "failed"}, "not completed")]
        for altered, expected in variants:
            with self.subTest(expected=expected):
                self.write(self.candidate, altered)
                self.reject(expected)

    def test_workload_sampling_environment_and_source_drift_are_rejected(self):
        original = self.read(self.candidate)
        original_bytes = {Path(info["files"][0]["path"]): Path(info["files"][0]["path"]).read_bytes()
                          for info in original["provenance"].values()}
        for field, expected in (("workload", "workload fingerprint mismatch"), ("samplingProtocol", "samplingProtocol mismatch"),
                                ("environment", "environment mismatch"), ("measurement", "measurement source mismatch"),
                                ("inspector", "inspector source mismatch")):
            with self.subTest(field=field):
                for source, data in original_bytes.items():
                    source.write_bytes(data)
                self.write(self.candidate, deepcopy(original))
                def mutate(summary):
                    if field == "workload":
                        summary["samples"][0]["workload"]["payloadBytes"] += 1
                    elif field in ("samplingProtocol", "environment"):
                        summary[field]["changed"] = True
                    else:
                        self.change_source(summary, field)
                self.change(self.candidate, mutate)
                self.reject(expected)

    @staticmethod
    def seal_source(summary, group):
        info = summary["provenance"][group]
        info["sha256"] = comparison.digest(comparison.compact([{key: row[key] for key in ("name", "sha256")} for row in info["files"]]))
        for sample in summary["samples"]:
            sample["provenance"][group] = deepcopy(info)

    def change_source(self, summary, group):
        row = summary["provenance"][group]["files"][0]
        path = Path(row["path"])
        path.write_bytes(path.read_bytes() + b"\n// Offline comparison source-difference fixture.\n")
        row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.seal_source(summary, group)

    def test_recorder_source_difference_is_allowed_and_listed(self):
        self.change(self.candidate, lambda summary: self.change_source(summary, "recorder"))
        status, _, stderr = self.invoke()
        self.assertEqual(status, 0, stderr)
        report = self.read(self.output)
        self.assertTrue(report["recorderSourceChanged"])
        self.assertEqual([row["file"] for row in report["recorderSourceDifferences"]], ["recorder.js"])
        self.assertNotEqual(report["provenance"]["baseline"]["recorder"], report["provenance"]["candidate"]["recorder"])

    def test_missing_actual_source_is_rejected(self):
        source = Path(self.read(self.candidate)["provenance"]["recorder"]["files"][0]["path"])
        source.unlink()
        status, _, stderr = self.invoke()
        self.assertEqual(status, 2, stderr)
        self.assertIn(source.name, stderr)
        self.assertFalse(self.output.exists())

    def test_changed_actual_source_with_unchanged_provenance_is_rejected(self):
        source = Path(self.read(self.candidate)["provenance"]["recorder"]["files"][0]["path"])
        source.write_bytes(source.read_bytes() + b"\n// This was not in the measurement.\n")
        self.reject("actual provenance source digest mismatch")

    def test_forged_source_hash_and_incomplete_dependency_set_are_rejected(self):
        original = self.read(self.candidate)
        def forge(summary):
            summary["provenance"]["recorder"]["files"][0]["sha256"] = "a" * 64
            self.seal_source(summary, "recorder")
        self.change(self.candidate, forge)
        self.reject("actual provenance source digest mismatch")
        self.write(self.candidate, original)
        def omit(summary):
            summary["provenance"]["recorder"]["files"].pop()
            self.seal_source(summary, "recorder")
        self.change(self.candidate, omit)
        self.reject("unexpected provenance dependency set")

    def test_counter_error_and_close_mismatches_are_rejected(self):
        original = self.read(self.candidate)
        for field, value in (("accepted", 99), ("rejected", 1), ("totals", {}),
                             ("errors", [{"code": "UNEXPECTED"}]), ("closeRejected", True)):
            with self.subTest(field=field):
                self.write(self.candidate, deepcopy(original))
                self.change(self.candidate, lambda summary: summary["samples"][0].__setitem__(field, value))
                self.reject(f"{field} mismatch")

    def test_actual_trace_tampering_is_detected_even_with_unchanged_summary(self):
        summary = self.read(self.candidate)
        run = self.candidate.parent / summary["samples"][0]["runDirectory"]
        trace = next(run.glob("*.jsonl"))
        original = trace.read_bytes()
        self.assertIn(b'"data":"x', original)
        trace.write_bytes(original.replace(b'"data":"x', b'"data":"y', 1))
        self.reject("status does not match actual trace")

    def test_validly_rehashed_inspection_change_is_still_rejected(self):
        def mutate(summary):
            sample = summary["samples"][0]
            sample["inspection"]["sessions"][0]["reasons"].append("unexpected inspection reason")
            normalized = deepcopy(sample["inspection"])
            normalized["runDir"] = "<run-directory>"
            traces = {row["file"]: row["normalizedSha256"] for row in sample["artifacts"]["files"]}
            for session in normalized["sessions"]:
                if "sha256" in session:
                    session["sha256"] = traces[session["traceFile"]]
            sample["artifacts"]["normalizedInspectionSha256"] = comparison.digest(comparison.compact(normalized))
        self.change(self.candidate, mutate)
        self.reject("normalized inspection mismatch")

    def test_existing_output_and_summary_measurement_divergence_are_rejected(self):
        self.output.write_text("preserve this file", encoding="utf-8")
        status, _, stderr = self.invoke()
        self.assertEqual(status, 2)
        self.assertIn("output already exists", stderr)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "preserve this file")
        self.output.unlink()
        summary = self.read(self.candidate)
        summary["samples"][0]["closeMs"] += 1
        self.write(self.candidate, summary)
        self.reject("summary/measurement mismatch")

    def test_invalid_metric_types_cannot_disappear_from_both_sides(self):
        originals = {path: self.read(path) for path in (self.baseline, self.candidate)}
        for keys in (("closeMs",), ("cpu", "total", "userUs")):
            for value in ("invalid", True, [1], {}, {"unexpected": 1}):
                with self.subTest(metric=".".join(keys), value=value):
                    for path, original in originals.items():
                        self.write(path, deepcopy(original))
                        def mutate(summary):
                            target = summary["samples"][0]
                            for key in keys[:-1]:
                                target = target[key]
                            target[keys[-1]] = value
                        self.change(path, mutate)
                    try:
                        self.reject("invalid metric: " + ".".join(keys))
                    finally:
                        self.output.unlink(missing_ok=True)

    def test_missing_memory_and_flush_cpu_members_propagate_null(self):
        def mutate(summary):
            sample = summary["samples"][0]
            sample["memory"]["baseline"]["rss"] = None
            sample["memory"]["sampledMax"]["heapUsed"] = None
            sample["flush"]["calls"] = [{"userUs": None, "systemUs": 2}, {"userUs": 7, "systemUs": 3}]
            sample["flush"]["summary"]["count"] = 2
        self.change(self.baseline, mutate)
        self.change(self.candidate, mutate)
        status, _, stderr = self.invoke()
        self.assertEqual(status, 0, stderr)
        report = self.read(self.output)
        metrics = report["pairs"][0]["metrics"]
        for name in ("memory.sampledMaxDelta.rss", "memory.afterCloseGCDelta.rss",
                     "memory.sampledMaxDelta.heapUsed", "flush.total.userUs"):
            self.assertEqual(metrics[name], {"baseline": None, "candidate": None, "delta": None, "percentChange": None})
            self.assertEqual(report["scenarios"][0]["metrics"][name]["delta"]["count"], 1)
        self.assertEqual(metrics["flush.total.systemUs"]["baseline"], 5)

    def test_invalid_generated_timestamps_are_rejected_before_normalization(self):
        original = self.read(self.candidate)
        sample = original["samples"][0]
        run = self.candidate.parent / sample["runDirectory"]
        status_name = next(row["file"] for row in sample["artifacts"]["files"] if row["file"].endswith(".status.json"))
        for name, field in (("run.json", "startedAt"), (status_name, "updatedAt")):
            file = run / name
            original_bytes = file.read_bytes()
            timestamp = self.read(file)[field]
            for invalid in ("x" * len(timestamp), "2026-02-30T00:00:00.000Z"):
                with self.subTest(field=field, invalid=invalid):
                    self.write(self.candidate, deepcopy(original))
                    changed = original_bytes.replace(timestamp.encode("utf-8"), invalid.encode("utf-8"))
                    self.assertEqual(len(original_bytes), len(changed))
                    file.write_bytes(changed)
                    def mutate(summary):
                        row = next(row for row in summary["samples"][0]["artifacts"]["files"] if row["file"] == name)
                        row["sha256"] = comparison.digest(changed)
                    self.change(self.candidate, mutate)
                    try:
                        self.reject(f"invalid generated timestamp: {field}")
                    finally:
                        file.write_bytes(original_bytes)
                        self.output.unlink(missing_ok=True)

    def test_nonfinite_values_and_derived_overflow_are_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                self.change(self.candidate, lambda summary: summary["samples"][0].__setitem__("closeMs", value))
                self.reject("nonfinite JSON")
        for path, value in ((self.baseline, 1e-300), (self.candidate, 1e300)):
            self.change(path, lambda summary: summary["samples"][0].__setitem__("closeMs", value))
        self.reject("nonfinite metric: closeMs.percentChange")
        self.change(self.candidate, lambda summary: summary["samples"][0].__setitem__("closeMs", 10 ** 400))
        self.reject("nonfinite metric: closeMs")


if __name__ == "__main__":
    unittest.main()
