import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dsh_eval.__main__ import main
from dsh_eval.batch import run_batch
from dsh_eval.experiment import run_experiment
from dsh_eval.formats import load_json, validate_case
from dsh_eval.report import generate_report
from dsh_eval.runner import ROOT, run_case


class RecorderOptionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dsh-recorder-options-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.case = load_json(ROOT / "fixtures/evaluation/retry-read.case.json")
        self.case["configRef"].update(provider="synthetic", model="none")

    def save(self, name, value):
        path = self.directory / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_optional_field_is_validated_without_mutating_old_or_explicit_inputs(self):
        for version in (1, 2):
            case = copy.deepcopy(self.case)
            case["caseFormatVersion"] = version
            case["environment"].pop("stateful", None)
            for assertion in case["assertions"]:
                if assertion["type"] == "tool_result" and not assertion["arguments"]:
                    assertion["arguments"] = {"path": "project.md"}
            for options in ({}, {"maxEventBytes": 4194304}, {"maxPendingBytes": 1},
                            {"maxEventBytes": 1048576, "maxPendingBytes": 16777216},
                            {"maxEventBytes": 9007199254740991}):
                value = {**case, "recorder": options}
                original = copy.deepcopy(value)
                self.assertIs(validate_case(value), value)
                self.assertEqual(value, original)
            self.assertNotIn("recorder", validate_case(case))

    def test_invalid_values_and_route_configuration_mixing_are_rejected(self):
        for options in (None, [], "bad", {"outputDir": "elsewhere"}, *[
                {name: value} for name in ("maxEventBytes", "maxPendingBytes")
                for value in (True, False, None, "4", 0, -1, 1.5, 2 ** 53)]):
            with self.subTest(options=options), self.assertRaises(ValueError):
                validate_case({**self.case, "recorder": options})
        for name in ("maxEventBytes", "maxPendingBytes"):
            with self.assertRaises(ValueError):
                validate_case({**self.case, "configRef": {**self.case["configRef"], name: 4194304}})

    def test_single_case_freezes_declared_options_before_preparation(self):
        self.case["recorder"] = {"maxEventBytes": 4194304, "maxPendingBytes": 8388608}
        source = self.save("case.json", self.case)
        def prepare(directory, *_):
            self.assertEqual(load_json(directory / "case.json"), self.case)
            self.save("case.json", {"changed": True})
            raise ValueError("stop before any model")
        with patch("dsh_eval.runner._prepare", side_effect=prepare), redirect_stdout(io.StringIO()) as output:
            code = main(["--case", str(source), "--run", "--runs-root", str(self.directory / "outputs")])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(load_json(result["association"]["casePath"]), self.case)
        self.assertEqual(result["execution"]["status"], "runtime_error")

    def test_omitted_and_explicit_defaults_remain_distinct_frozen_inputs(self):
        for options in (None, {"maxEventBytes": 1048576, "maxPendingBytes": 16777216}):
            case = copy.deepcopy(self.case)
            if options is not None:
                case["recorder"] = options
            source = self.save("case.json", case)
            original = source.read_bytes()
            with patch("dsh_eval.runner._prepare", side_effect=ValueError("no model")):
                result = run_case(source, self.directory / "outputs")
            self.assertEqual(load_json(result["association"]["casePath"]), case)
            self.assertEqual(source.read_bytes(), original)

    def test_batch_freezes_distinct_recorder_inputs_before_any_case_runs(self):
        self.case["recorder"] = {"maxEventBytes": 4194304}
        self.save("first.json", self.case)
        other = {**self.case, "recorder": {"maxPendingBytes": 8388608}}
        self.save("second.json", other)
        manifest = {"batchFormatVersion": 1, "batchName": "recorder", "failurePolicy": "continue", "cases": [
            {"entryId": "first", "casePath": "first.json"}, {"entryId": "second", "casePath": "second.json"}]}
        def prepare(*_):
            self.save("second.json", {"changed": True})
            raise ValueError("no model")
        with patch("dsh_eval.runner._prepare", side_effect=prepare):
            report = run_batch(self.save("batch.json", manifest), self.directory / "outputs")
        base = Path(report["batchDirectory"])
        for row, expected in zip(report["entries"], (self.case, other)):
            self.assertEqual(load_json(base / row["casePath"]), expected)
            self.assertEqual(load_json(base / row["caseDirectory"] / "case.json"), expected)

    def test_experiment_model_overrides_preserve_recorder_and_report_checks_full_snapshots(self):
        self.case["recorder"] = {"maxEventBytes": 4194304, "maxPendingBytes": 8388608}
        self.save("case.json", self.case)
        configurations = [{"configurationId": model, "configRef": {**self.case["configRef"], "model": model}}
                          for model in ("one", "two")]
        manifest = {"experimentFormatVersion": 1, "experimentName": "recorder", "failurePolicy": "continue",
                    "repetitions": 1, "cases": [{"entryId": "case", "casePath": "case.json"}], "configurations": configurations}
        def prepare(*_):
            self.save("case.json", {"changed": True})
            raise ValueError("no model")
        with patch("dsh_eval.runner._prepare", side_effect=prepare):
            report = run_experiment(self.save("experiment.json", manifest), self.directory / "outputs")
        base = Path(report["experimentDirectory"])
        self.assertEqual(load_json(base / "inputs/0001.case.json"), self.case)
        for sample, configuration in zip(report["samples"], configurations):
            expected = {**self.case, "configRef": configuration["configRef"]}
            self.assertEqual(load_json(base / sample["casePath"]), expected)
            self.assertEqual(load_json(base / sample["caseDirectory"] / "case.json"), expected)
            self.assertEqual(sample["requestedConfiguration"], configuration["configRef"])
        # A preparation failure has no actual route; its valid snapshots can still
        # be independently rechecked. A changed recorder field must be rejected.
        first_report = generate_report(base / "experiment-result.json", self.directory / "reports")
        self.assertTrue(all(row["verification"] == "verified" for row in first_report["samples"]))
        snapshot = base / report["samples"][0]["caseDirectory"] / "case.json"
        altered = load_json(snapshot)
        altered["recorder"]["maxEventBytes"] = 1048576
        snapshot.write_text(json.dumps(altered), encoding="utf-8")
        changed_report = generate_report(base / "experiment-result.json", self.directory / "reports")
        self.assertEqual(changed_report["samples"][0]["verification"], "rejected")
        self.assertTrue(any("snapshot" in reason for reason in changed_report["samples"][0]["reasons"]))


if __name__ == "__main__":
    unittest.main()
