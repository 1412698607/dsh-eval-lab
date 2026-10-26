"""External model routes stay explicit, frozen, and free of embedded keys."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dsh_eval.experiment import plan_experiment, run_experiment
from dsh_eval.formats import load_json, model_providers, validate_case
from dsh_eval.runner import ROOT, run_case


def providers():
    return {"bailian": {"api": "openai-completions",
                        "baseURL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        "apiKeyEnv": "DASHSCOPE_API_KEY",
                        "models": [{"id": "qwen3.7-plus", "contextWindow": 1000000, "maxTokens": 131072}]}}


class ModelProviderTests(unittest.TestCase):
    def test_python_and_node_reject_ambiguous_endpoints_consistently(self):
        addresses = [("https://example.com/v1", True), ("https://example.com:8443/v1", True),
                     ("https:///example.com/v1", False), ("https://%65xample.com/v1", False),
                     ("https://example.com/v1\u0085", False), ("https://example.com/v1\x00", False),
                     ("https://example.com:", False), ("https://example.com:0/v1", False),
                     ("https://example.com:65536/v1", False)]
        declarations = []
        python_results = []
        for address, _expected in addresses:
            declaration = providers()
            declaration["bailian"]["baseURL"] = address
            declarations.append(declaration)
            try:
                model_providers(declaration)
                python_results.append(True)
            except ValueError:
                python_results.append(False)
        script = ('import {validateModelProviders} from "./scripts/lib/model-providers.js"; '
                  'let text=""; for await(const part of process.stdin) text+=part; '
                  'console.log(JSON.stringify(JSON.parse(text).map(item=>{'
                  'try {validateModelProviders(item);return true;} catch {return false;}})));')
        result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT,
                                input=json.dumps(declarations), capture_output=True, text=True, encoding="utf-8", check=True)
        expected = [expected for _address, expected in addresses]
        self.assertEqual(python_results, expected)
        self.assertEqual(json.loads(result.stdout), expected)

    def test_optional_routes_are_preserved_without_mutating_both_case_versions(self):
        for version in (1, 2):
            for value in (None, {}, providers()):
                case = load_json(ROOT / "fixtures/evaluation/live-read.case.json")
                case["caseFormatVersion"] = version
                if value is not None:
                    case["modelProviders"] = value
                before = copy.deepcopy(case)
                self.assertEqual(validate_case(case), before)
                self.assertEqual(case, before)

    def test_invalid_routes_and_embedded_credentials_are_rejected(self):
        mutations = [lambda routes: routes.update({"deepseek-official": routes.pop("bailian")}),
                     lambda routes: routes.update({"bad route": routes.pop("bailian")}),
                     lambda routes: routes["bailian"].update(apiKey="must-not-be-saved"),
                     lambda routes: routes["bailian"].update(headers={"Authorization": "secret"}),
                     lambda routes: routes["bailian"].update(apiKeyEnv="literal-key-value"),
                     lambda routes: routes["bailian"].update(api="unknown"),
                     lambda routes: routes["bailian"].update(baseURL="https://user:secret@example.com/v1"),
                     lambda routes: routes["bailian"].update(baseURL="https://example.com/v1?key=secret"),
                     lambda routes: routes["bailian"].update(baseURL="http://example.com/v1"),
                     lambda routes: routes["bailian"].update(baseURL="https://example.com:99999/v1"),
                     lambda routes: routes["bailian"].update(models=[]),
                     lambda routes: routes["bailian"]["models"].append(copy.deepcopy(routes["bailian"]["models"][0]))]
        for field in ("contextWindow", "maxTokens"):
            for value in (True, 0, -1, 1.5, "100", 9007199254740992):
                mutations.append(lambda routes, field=field, value=value:
                                 routes["bailian"]["models"][0].update({field: value}))
        for index, mutate in enumerate(mutations):
            case = load_json(ROOT / "fixtures/evaluation/live-read.case.json")
            case["modelProviders"] = providers()
            mutate(case["modelProviders"])
            with self.subTest(index=index), self.assertRaises(ValueError):
                validate_case(case)
        for value in (None, [], True, {"bailian": None}):
            case["modelProviders"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_case(case)

    def test_invalid_routes_reject_before_run_identity_or_output(self):
        with tempfile.TemporaryDirectory(prefix="dsh-providers-") as temporary:
            directory = Path(temporary)
            case = load_json(ROOT / "fixtures/evaluation/live-read.case.json")
            case["modelProviders"] = {"bailian": {"apiKey": "must-not-be-saved"}}
            path = directory / "case.json"
            path.write_text(json.dumps(case), encoding="utf-8")
            with patch("dsh_eval.runner.uuid4", side_effect=AssertionError("must not create identity")), \
                    patch("dsh_eval.runner._prepare", side_effect=AssertionError("must not start host")):
                with self.assertRaises(ValueError):
                    run_case(path, directory / "outputs")
            self.assertFalse((directory / "outputs").exists())

    def test_route_changes_invalidate_plan_and_expanded_cases_freeze_the_same_declaration(self):
        with tempfile.TemporaryDirectory(prefix="dsh-providers-") as temporary:
            directory = Path(temporary)
            case = load_json(ROOT / "fixtures/evaluation/core/direct-read.case.json")
            case["modelProviders"] = providers()
            manifest = {"experimentFormatVersion": 1, "experimentName": "route-freeze", "repetitions": 1,
                        "failurePolicy": "stop", "cases": [{"entryId": "read", "casePath": "case.json"}],
                        "configurations": [{"configurationId": "baseline", "configRef": case["configRef"]},
                                           {"configurationId": "candidate", "configRef": {
                                               **case["configRef"], "provider": "bailian", "model": "qwen3.7-plus"}}]}
            path = directory / "experiment.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            case_path = directory / "case.json"
            case_path.write_text(json.dumps(case), encoding="utf-8")
            plan = plan_experiment(path, max_samples=2)
            digest = plan["planFingerprint"]["sha256"]
            self.assertTrue(all(row["modelProviders"] == providers() for row in plan["samples"]))
            for field, value in (("baseURL", "https://other.example/v1"), ("apiKeyEnv", "OTHER_API_KEY")):
                changed = copy.deepcopy(case)
                changed["modelProviders"]["bailian"][field] = value
                case_path.write_text(json.dumps(changed), encoding="utf-8")
                self.assertNotEqual(plan_experiment(path, max_samples=2)["planFingerprint"]["sha256"], digest)
                with patch("dsh_eval.experiment.uuid4", side_effect=AssertionError("must not create identity")):
                    with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
                        run_experiment(path, directory / "outputs", max_samples=2, expected_plan_sha256=digest)
            case_path.write_text(json.dumps(case), encoding="utf-8")

            def examine_frozen(batch_path, *_args, **options):
                batch = load_json(batch_path)
                snapshots = [load_json(batch_path.parent / row["casePath"]) for row in batch["cases"]]
                self.assertEqual([row["configRef"]["provider"] for row in snapshots], ["deepseek-official", "bailian"])
                self.assertTrue(all(row["modelProviders"] == providers() for row in snapshots))
                self.assertEqual(load_json(batch_path.parent / "plan-input.json")["cases"][0], case)
                self.assertEqual(load_json(batch_path.parent / "experiment-result.json")["batchBinding"]["batchId"], options["batch_id"])
                raise ValueError("stop before actual execution")

            with patch("dsh_eval.experiment.run_batch", side_effect=examine_frozen):
                with self.assertRaisesRegex(ValueError, "stop before actual execution"):
                    run_experiment(path, directory / "outputs", max_samples=2, expected_plan_sha256=digest)
