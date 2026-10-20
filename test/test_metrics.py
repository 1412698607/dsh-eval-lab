import copy
import json
import unittest

from dsh_eval.formats import load_json, parse_json
from dsh_eval.metrics import METRICS, number, recording_metrics, summarize
from dsh_eval.runner import ROOT


class MetricTests(unittest.TestCase):
    def setUp(self):
        self.events = load_json(ROOT / "fixtures/evaluation/read-project.events.json")
        self.task_input = self.events[1]["data"]["content"][0]["text"]

    def metrics(self, events=None):
        return recording_metrics(self.events if events is None else events, self.task_input)

    def test_calls_count_settled_attempts_instead_of_configuration_headers(self):
        events = copy.deepcopy(self.events)
        events[2:2] = [{"type": "request/header", "data": {}},
                       {"type": "assistant/attempt", "data": {"stream": []}},
                       {"type": "request/header", "data": {}}]
        for index, event in enumerate(events):
            event["seq"] = index
        metrics = self.metrics(events)
        self.assertEqual(metrics["modelCalls"], 2)
        self.assertEqual(metrics["toolCalls"], 1)
        self.assertIsNone(metrics["inputTokens"])

    def test_host_step_can_open_before_user_input_without_invalidating_metrics(self):
        self.events.insert(1, {"type": "step/start", "data": {"turn": 0, "step": 0}})
        for index, event in enumerate(self.events):
            event["seq"] = index
        metrics = self.metrics()
        self.assertEqual((metrics["modelCalls"], metrics["toolCalls"]), (1, 1))

    def test_reported_usage_sums_each_message_once_and_does_not_invent_total(self):
        self.events[4]["data"]["usage"] = {"inputTokens": 9, "outputTokens": 3, "totalTokens": 12}
        extra = copy.deepcopy(self.events[4])
        extra["data"]["usage"] = {"inputTokens": 5, "outputTokens": 0}
        self.events.insert(4, extra)
        for index, event in enumerate(self.events):
            event["seq"] = index
        metrics = self.metrics()
        self.assertEqual((metrics["modelCalls"], metrics["inputTokens"], metrics["outputTokens"]), (2, 14, 3))
        self.assertIsNone(metrics["totalTokens"])
        self.assertIsNone(metrics["cost"])

    def test_missing_invalid_and_partial_usage_remains_missing(self):
        for usage in (None, {}, {"inputTokens": True}, {"inputTokens": -1}, {"inputTokens": 1.5}):
            with self.subTest(usage=usage):
                self.events[4]["data"]["usage"] = usage
                self.assertIsNone(self.metrics()["inputTokens"])
        self.events[4]["data"]["usage"] = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}
        self.assertEqual(self.metrics()["totalTokens"], 0)
        self.events.insert(4, {"seq": 4, "type": "assistant/message", "data": {"message": {"content": []}}})
        for index, event in enumerate(self.events):
            event["seq"] = index
        self.assertIsNone(self.metrics()["inputTokens"])

    def test_number_rejects_values_outside_finite_range_without_raising(self):
        for value in (10 ** 400, -(10 ** 400), float("inf"), float("nan"), True, -1):
            with self.subTest(value=value):
                self.assertFalse(number(value))
        for value in (0, 3, 1e308):
            with self.subTest(value=value):
                self.assertTrue(number(value))

    def test_usage_overflow_keeps_other_fields_and_call_counts(self):
        for values in ((10 ** 400,), (10 ** 308, 10 ** 308)):
            with self.subTest(values=values):
                events = copy.deepcopy(self.events)
                events[4]["data"]["usage"] = {"inputTokens": values[0], "outputTokens": 1, "totalTokens": 2}
                if len(values) == 2:
                    extra = copy.deepcopy(events[4])
                    extra["data"]["usage"]["inputTokens"] = values[1]
                    events.insert(4, extra)
                for index, event in enumerate(events):
                    event["seq"] = index
                metrics = self.metrics(events)
                self.assertIsNone(metrics["inputTokens"])
                self.assertEqual(metrics["modelCalls"], len(values))
                self.assertEqual(metrics["outputTokens"], len(values))
                self.assertEqual(metrics["totalTokens"], 2 * len(values))
                self.assertEqual(parse_json(json.dumps(metrics, allow_nan=False)), metrics)

    def test_unclosed_wrong_task_gaps_and_outside_events_are_not_measured(self):
        outside = copy.deepcopy(self.events)
        outside.append({"seq": 6, "type": "assistant/message", "data": {}})
        gap = copy.deepcopy(self.events)
        gap[3]["seq"] = 99
        for events in (self.events[:-1], self.events[2:], gap, outside):
            with self.subTest(events=events), self.assertRaises(ValueError):
                self.metrics(events)
        self.events[1]["data"]["content"][0]["text"] = "different task"
        with self.assertRaises(ValueError):
            self.metrics()

    def test_denominators_keep_failures_cancellations_errors_and_skips_visible(self):
        rows = [
            {"caseRunId": "a", "status": "finished", "outcome": "passed", "metrics": {"modelCalls": 2, "inputTokens": 0}},
            {"caseRunId": "b", "status": "finished", "outcome": "failed", "metrics": {"modelCalls": 3}},
            {"caseRunId": "c", "status": "finished", "outcome": "unevaluable", "executionStatus": "cancelled"},
            {"caseRunId": "d", "status": "error", "outcome": "unevaluable"},
            {"caseRunId": None, "status": "skipped", "outcome": None},
        ]
        result = summarize(rows)
        self.assertEqual((result["planned"], result["attempted"], result["finished"], result["skipped"], result["errors"]), (5, 4, 3, 1, 1))
        self.assertEqual(result["evaluablePassRate"], {"numerator": 1, "denominator": 2, "value": 0.5})
        self.assertEqual(result["attemptedPassRate"]["value"], 0.25)
        self.assertEqual(result["evaluableCoverage"]["value"], 0.4)
        self.assertEqual(result["executionStatusCounts"]["cancelled"], 1)
        self.assertEqual(result["metrics"]["modelCalls"], {"observedSamples": 2, "missingSamples": 3, "observedTotal": 5, "observedMean": 2.5})
        self.assertEqual(result["metrics"]["inputTokens"]["observedTotal"], 0)
        self.assertIsNone(result["metrics"]["cost"]["observedTotal"])

    def test_empty_or_no_evaluable_samples_have_no_rate(self):
        for rows in ([], [{"caseRunId": None, "status": "skipped", "outcome": None}]):
            result = summarize(rows)
            self.assertIsNone(result["evaluablePassRate"]["value"])
            self.assertIsNone(result["attemptedPassRate"]["value"])
            for key in METRICS:
                self.assertIsNone(result["metrics"][key]["observedTotal"])

    def test_invalid_numeric_samples_are_missing_without_changing_denominators(self):
        rows = [{"caseRunId": str(index), "status": "finished", "outcome": "passed",
                 "metrics": {"elapsedSeconds": value}} for index, value in enumerate((10 ** 400, 0, 3))]
        result = summarize(rows)
        self.assertEqual(result["attemptedPassRate"], {"numerator": 3, "denominator": 3, "value": 1})
        self.assertEqual(result["metrics"]["elapsedSeconds"],
                         {"observedSamples": 2, "missingSamples": 1, "observedTotal": 3, "observedMean": 1.5})
        self.assertEqual(parse_json(json.dumps(result, allow_nan=False)), result)

    def test_summary_overflow_preserves_coverage_and_json_roundtrip(self):
        for values in ((1e308, 1e308), (10 ** 308, 10 ** 308), (10 ** 308, 10 ** 308, 1.0)):
            with self.subTest(values=values):
                rows = [{"caseRunId": str(index), "status": "finished", "outcome": "passed",
                         "metrics": {"elapsedSeconds": value, "toolCalls": 1}}
                        for index, value in enumerate(values)]
                result = summarize(rows)
                aggregate = result["metrics"]["elapsedSeconds"]
                self.assertEqual((aggregate["observedSamples"], aggregate["missingSamples"]), (len(values), 0))
                self.assertIsNone(aggregate["observedTotal"])
                self.assertIsNone(aggregate["observedMean"])
                self.assertTrue(aggregate["reason"])
                self.assertEqual(result["metrics"]["toolCalls"]["observedTotal"], len(values))
                self.assertEqual(result["evaluablePassRate"]["value"], 1)
                self.assertEqual(parse_json(json.dumps(result, allow_nan=False)), result)


if __name__ == "__main__":
    unittest.main()
