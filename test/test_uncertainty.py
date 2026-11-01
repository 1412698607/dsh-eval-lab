"""Reference values, numerical limits and complete-pair reporting without model calls."""
import json
import math
from decimal import Decimal, localcontext
from pathlib import Path
from statistics import NormalDist
import unittest
from unittest.mock import patch

from dsh_eval.report import generate_report
from dsh_eval.uncertainty import _t_critical_95, paired_binary_interval, paired_mean_interval, wilson_interval
from test_report import ReportFixture


class IntervalTests(unittest.TestCase):
    def test_large_offset_small_spread_preserves_variance_and_float_endpoint_precision(self):
        critical = 1 / math.tan(math.pi / 40)  # Analytic df=1 quantile, independent of the beta solver.
        for values in ([1e16, 1e16 + 2], [10**16, 10**16 + 1], [1e12, 1e12 + 1]):
            with self.subTest(values=values), localcontext() as context:
                context.prec = 80
                a, b = (Decimal(value) for value in values)
                mean = (a + b) / 2
                half = abs(b - a) * Decimal(critical) / 2
                result = paired_mean_interval(values)
                self.assertEqual(result["status"], "available")
                self.assertEqual(result["lower"], float(mean - half))
                self.assertEqual(result["upper"], float(mean + half))
        result = paired_mean_interval([10**18, 10**18 + 1])
        self.assertEqual((result["status"], result["reason"]), ("unavailable", "precision_loss"))
        large = paired_mean_interval([-1e308] * 50 + [1e308] * 50)
        self.assertEqual(large["status"], "available")
        self.assertEqual(large["estimate"], 0)
        self.assertTrue(math.isfinite(large["lower"]) and math.isfinite(large["upper"]))
        cancellation = paired_mean_interval([-1e308] + [7e307] * 9)
        self.assertEqual(cancellation["status"], "available")
        with localcontext() as context:
            context.prec = 80
            a, b = Decimal(-1e308), Decimal(7e307)
            mean = (a + 9 * b) / 10
            half = (b - a) * Decimal(_t_critical_95(9)) / 10
            self.assertAlmostEqual(cancellation["lower"] / float(mean - half), 1, places=12)
            self.assertAlmostEqual(cancellation["upper"] / float(mean + half), 1, places=12)

    def test_wilson_reference_and_boundary_samples(self):
        interval = wilson_interval(5, 10)
        self.assertAlmostEqual(interval["lower"], 0.236593090512564, places=12)
        self.assertAlmostEqual(interval["upper"], 0.763406909487436, places=12)
        z = NormalDist().inv_cdf(0.975)
        for n in (1, 2, 20, 1000):
            low, high = wilson_interval(0, n), wilson_interval(n, n)
            self.assertEqual(low["lower"], 0)
            self.assertAlmostEqual(low["upper"], z * z / (n + z * z), places=12)
            self.assertAlmostEqual(high["lower"], n / (n + z * z), places=12)
            self.assertEqual(high["upper"], 1)
            self.assertGreater(high["upper"] - high["lower"], 0)

    def test_wilson_zero_and_invalid_counts_never_become_zero_width_success(self):
        result = wilson_interval(0, 0)
        self.assertEqual(result["status"], "unavailable")
        self.assertTrue(all(result[key] is None for key in ("estimate", "lower", "upper")))
        for successes, n in ((True, 1), (0, False), (-1, 2), (3, 2), (1.0, 2), (0, 9007199254740992)):
            with self.subTest(successes=successes, n=n), self.assertRaises(ValueError):
                wilson_interval(successes, n)
        for n in (1, 2, 7, 30):
            for successes in range(n + 1):
                value = wilson_interval(successes, n)
                self.assertTrue(0 <= value["lower"] <= value["estimate"] <= value["upper"] <= 1)
                self.assertEqual("small_sample" in value["warnings"], n < 30)

    def test_paired_binary_bound_is_symmetric_and_not_degenerate_for_concordant_pairs(self):
        values = [1] * 20 + [-1] * 10 + [0] * 10
        result = paired_binary_interval(values)
        half = math.sqrt(2 * math.log(40) / 40)
        self.assertEqual(result["estimate"], 0.25)
        self.assertAlmostEqual(result["lower"], 0.25 - half)
        self.assertEqual(result["discordantPairs"], 30)
        reverse = paired_binary_interval([-value for value in values])
        self.assertEqual(reverse["lower"], -result["upper"])
        self.assertEqual(reverse["upper"], -result["lower"])
        for values in ([0], [0] * 10, [1], [-1]):
            result = paired_binary_interval(values)
            self.assertTrue(-1 <= result["lower"] < result["upper"] <= 1)
        self.assertEqual(paired_binary_interval([])["status"], "unavailable")
        for values in ([True], [2], [0.5]):
            with self.assertRaises(ValueError):
                paired_binary_interval(values)

    def test_t_quantiles_match_analytic_cases_and_nist_reference_table(self):
        self.assertAlmostEqual(_t_critical_95(1), 1 / math.tan(math.pi / 40), places=10)
        self.assertAlmostEqual(_t_critical_95(2), 0.95 * math.sqrt(2 / (1 - 0.95 ** 2)), places=10)
        # NIST/SEMATECH eda3672, probability .975 column, rounded to three decimals.
        for df, critical in ((3, 3.182), (5, 2.571), (9, 2.262), (10, 2.228), (20, 2.086), (30, 2.042), (100, 1.984)):
            self.assertAlmostEqual(_t_critical_95(df), critical, delta=0.0005)
        values = [_t_critical_95(df) for df in (1, 2, 5, 30, 1000, 1000000)]
        self.assertTrue(all(a > b for a, b in zip(values, values[1:])))
        self.assertGreater(values[-1], NormalDist().inv_cdf(0.975))
        self.assertAlmostEqual(values[-1], NormalDist().inv_cdf(0.975), delta=0.000005)

    def test_paired_t_uses_difference_variance_and_reverses_sign(self):
        result = paired_mean_interval([1, 2, 3])
        half = _t_critical_95(2) / math.sqrt(3)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["estimate"], 2)
        self.assertAlmostEqual(result["lower"], 2 - half, places=12)
        self.assertAlmostEqual(result["upper"], 2 + half, places=12)
        reverse = paired_mean_interval([-1, -2, -3])
        self.assertEqual(reverse["lower"], -result["upper"])
        self.assertEqual(reverse["upper"], -result["lower"])
        self.assertEqual(result, paired_mean_interval([1, 2, 3]))

    def test_t_insufficient_degenerate_overflow_and_tiny_values_have_explicit_statuses(self):
        for values, reason in (([], "no_metric_pairs"), ([2], "insufficient_pairs"), ([0, 0], "zero_observed_variance"),
                               ([3, 3, 3], "zero_observed_variance"), ([-1e308, 1e308], "numeric_unavailable")):
            with self.subTest(values=values):
                result = paired_mean_interval(values)
                self.assertEqual((result["status"], result["reason"]), ("unavailable", reason))
                self.assertIsNone(result["lower"])
                self.assertIsNone(result["upper"])
                json.dumps(result, allow_nan=False)
        tiny = paired_mean_interval([-1e-308, 1e-308])
        self.assertEqual(tiny["status"], "available")
        self.assertAlmostEqual(tiny["upper"] / 1e-308, _t_critical_95(1), places=10)
        for values in ([True, 2], [math.inf, 1], [math.nan, 1]):
            with self.assertRaises(ValueError):
                paired_mean_interval(values)
        with patch("dsh_eval.uncertainty._t_critical_95", side_effect=ArithmeticError("not converged")):
            self.assertEqual(paired_mean_interval([1, 2])["reason"], "numeric_unavailable")


class ReportIntervalTests(ReportFixture, unittest.TestCase):
    def index(self, config, repeat):
        return next(i for i, row in enumerate(self.saved["samples"]) if row["configurationId"] == config and row["repeatIndex"] == repeat)

    def test_all_pass_small_samples_keep_nonzero_uncertainty_and_sources_unchanged(self):
        self.experiment()
        before = self.digest(self.base)
        report = self.report()
        for distribution in report["repeatDistributions"]:
            interval = distribution["passRateInterval"]
            self.assertEqual((interval["n"], interval["successes"], interval["estimate"]), (2, 2, 1))
            self.assertLess(interval["lower"], 1)
            self.assertIn("small_sample", interval["warnings"])
        binary = report["comparisons"][0]["uncertainty"]["passRateDifference"]
        self.assertEqual((binary["n"], binary["estimate"], binary["lower"], binary["upper"]), (2, 0, -1, 1))
        self.assertEqual(self.digest(self.base), before)
        text = (Path(report["reportDirectory"]) / "report.md").read_text(encoding="utf-8")
        self.assertIn("95% 区间", text)
        self.assertIn("zero_observed_variance", text.replace("\\_", "_"))
        self.assertFalse(report["uncertaintyPolicy"]["independenceVerified"])

    def test_complete_pair_subset_and_per_metric_missingness_are_explicit(self):
        self.manifest["repetitions"] = 3
        self.experiment()
        for repeat in (1, 2, 3):
            self.runtime(self.saved["samples"][self.index("first", repeat)], elapsedSeconds=1000 * repeat)
            self.runtime(self.saved["samples"][self.index("second", repeat)], elapsedSeconds=1000 * repeat + repeat)
        report = self.report()
        interval = report["comparisons"][0]["uncertainty"]["metrics"]["elapsedSeconds"]
        self.assertEqual(interval["estimate"], 2)
        self.assertAlmostEqual(interval["upper"], 4.48413771175033, places=10)
        self.assertEqual(interval["repeatIndices"], [1, 2, 3])
        # One missing metric excludes just that metric's pair, not its pass/fail observation.
        self.runtime(self.saved["samples"][self.index("second", 2)], elapsedSeconds=None)
        report = self.report()
        uncertainty = report["comparisons"][0]["uncertainty"]
        self.assertEqual(uncertainty["passRateDifference"]["n"], 3)
        interval = uncertainty["metrics"]["elapsedSeconds"]
        self.assertEqual((interval["n"], interval["excludedPairs"]), (2, 1))
        self.assertEqual(interval["excludedReasons"], {"missing_metric": 1})
        self.assertEqual(interval["repeatIndices"], [1, 3])
        self.assertEqual(interval["estimate"], 2)
        self.assertIn("incomplete_coverage", interval["warnings"])
        self.assertEqual(uncertainty["metrics"]["cost"]["reason"], "no_metric_pairs")

    def test_missing_evidence_and_non_evaluable_samples_do_not_become_binary_failures(self):
        self.manifest["repetitions"] = 3
        self.experiment()
        index = self.index("second", 2)
        self.rerecord(index, lambda events: events.__setitem__(slice(None), [event for event in events if event["type"] not in ("tool/call", "tool/result")]))
        missing = self.saved["samples"][self.index("second", 3)]
        (self.base / missing["evidencePath"]).unlink()
        report = self.report()
        interval = report["comparisons"][0]["uncertainty"]["passRateDifference"]
        self.assertEqual((interval["n"], interval["estimate"], interval["excludedPairs"]), (1, 0, 2))
        self.assertEqual(interval["excludedReasons"], {"not_jointly_evaluable": 1, "missing_verified_matched_pair": 1})
        self.assertEqual(interval["repeatIndices"], [1])
        distribution = next(item for item in report["repeatDistributions"] if item["configurationId"] == "second" and item["source"] == "synthetic")
        single = distribution["passRateInterval"]
        self.assertEqual((single["n"], single["successes"], single["excludedSamples"], single["otherSourceSamples"]), (1, 1, 1, 1))

    def test_pairing_respects_repeat_source_and_configuration_not_marginal_counts(self):
        self.experiment()
        def fail(events):
            row = next(row for row in reversed(events) if row["type"] == "assistant/message")
            row["data"]["message"]["content"] = [{"type": "text", "text": "WRONG"}]
        self.rerecord(self.index("first", 1), fail)
        self.rerecord(self.index("second", 2), fail)
        interval = self.report()["comparisons"][0]["uncertainty"]["passRateDifference"]
        self.assertEqual((interval["estimate"], interval["discordantPairs"]), (0, 2))
        self.source(self.index("second", 2), "live")
        self.persist()
        report = self.report()
        synthetic = next(row for row in report["comparisons"] if row["source"] == "synthetic")["uncertainty"]["passRateDifference"]
        self.assertEqual((synthetic["n"], synthetic["estimate"], synthetic["repeatIndices"]), (1, 1, [1]))
        live = next(row for row in report["comparisons"] if row["source"] == "live")["uncertainty"]["passRateDifference"]
        self.assertEqual((live["n"], live["status"]), (0, "unavailable"))

    def test_identical_configurations_and_skipped_pairs_are_unavailable(self):
        self.manifest["configurations"][1]["configRef"] = self.manifest["configurations"][0]["configRef"].copy()
        self.experiment()
        interval = self.report()["comparisons"][0]["uncertainty"]["passRateDifference"]
        self.assertEqual((interval["status"], interval["reason"]), ("unavailable", "same_configuration"))
        self.assertEqual(interval["excludedReasons"], {"same_configuration": 2})
        self.manifest["configurations"][1]["configRef"]["model"] = "second"
        self.experiment(stop_after=1)
        interval = self.report()["comparisons"][0]["uncertainty"]["passRateDifference"]
        self.assertEqual((interval["n"], interval["excludedPairs"]), (0, 2))
        for row in self.report()["repeatDistributions"]:
            if row["source"] == "unknown":
                self.assertEqual(row["passRateInterval"]["status"], "unavailable")

    def test_continuation_intervals_use_original_repeats_once_and_recheck_deterministically(self):
        import test_experiment_resume_chain as fixtures
        fixture = fixtures.ExperimentResumeChainTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        result = fixture.execute()
        source = Path(result["resumeDirectory"]) / "experiment-resume-result.json"
        before = self.digest(fixture.fixture.directory)
        with patch("dsh_eval.resume.run_batch", side_effect=AssertionError("must not execute")), \
                patch("dsh_eval.batch.run_case", side_effect=AssertionError("must not run")):
            first = generate_report(source, self.outputs)
            second = generate_report(source, self.outputs)
        self.assertEqual(first["comparisonReportFormatVersion"], 3)
        self.assertTrue(all(row["passRateInterval"]["n"] == 2 for row in first["repeatDistributions"]))
        self.assertTrue(all(row["uncertainty"]["passRateDifference"]["n"] == 2 for row in first["comparisons"]))
        self.assertEqual(first["repeatDistributions"], second["repeatDistributions"])
        self.assertEqual([row["uncertainty"] for row in first["comparisons"]], [row["uncertainty"] for row in second["comparisons"]])
        self.assertEqual(self.digest(fixture.fixture.directory), before)

    def test_metric_interval_overflow_does_not_emit_infinite_bounds_or_drop_observed_pairs(self):
        self.experiment()
        for config, values in (("first", [1e308, 0]), ("second", [0, 1e308])):
            for repeat, value in enumerate(values, 1):
                self.runtime(self.saved["samples"][self.index(config, repeat)], elapsedSeconds=value)
        report = self.report()
        interval = report["comparisons"][0]["uncertainty"]["metrics"]["elapsedSeconds"]
        self.assertEqual((interval["status"], interval["reason"]), ("unavailable", "numeric_unavailable"))
        self.assertEqual((interval["n"], interval["excludedPairs"], interval["estimate"]), (2, 0, 0))
        self.assertIsNone(interval["lower"])
        self.assertIsNone(interval["upper"])
        json.dumps(report, allow_nan=False)

    def test_mixed_exclusions_are_disjoint_and_zero_metric_values_stay_observed(self):
        self.manifest["repetitions"] = 4
        self.experiment()
        self.runtime(self.saved["samples"][self.index("first", 1)], elapsedSeconds=0)
        self.runtime(self.saved["samples"][self.index("second", 1)], elapsedSeconds=2)
        self.runtime(self.saved["samples"][self.index("second", 2)], elapsedSeconds=True)
        self.rerecord(self.index("second", 3), lambda events: events.__setitem__(slice(None), [event for event in events
            if event["type"] not in ("tool/call", "tool/result")]))
        (self.base / self.saved["samples"][self.index("second", 4)]["evidencePath"]).unlink()
        report = self.report()
        uncertainty = report["comparisons"][0]["uncertainty"]
        binary = uncertainty["passRateDifference"]
        self.assertEqual((binary["includedPairs"], binary["excludedPairs"], binary["plannedPairs"]), (2, 2, 4))
        metric = uncertainty["metrics"]["elapsedSeconds"]
        self.assertEqual((metric["n"], metric["estimate"], metric["repeatIndices"]), (1, 2, [1]))
        self.assertEqual(metric["reason"], "insufficient_pairs")
        self.assertEqual(metric["excludedReasons"], {"not_jointly_evaluable": 1, "missing_verified_matched_pair": 1, "missing_metric": 1})
        for interval in [binary, *uncertainty["metrics"].values()]:
            self.assertEqual(interval["n"] + interval["excludedPairs"], interval["plannedPairs"])
            self.assertEqual(sum(interval["excludedReasons"].values()), interval["excludedPairs"])
        for row in report["repeatDistributions"]:
            interval = row["passRateInterval"]
            self.assertEqual(interval["n"] + interval["excludedSamples"], interval["sourceSamples"])
            self.assertEqual(interval["sourceSamples"] + interval["otherSourceSamples"], interval["plannedSamples"])


if __name__ == "__main__":
    unittest.main()
