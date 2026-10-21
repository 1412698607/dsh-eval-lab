from contextlib import redirect_stderr, redirect_stdout
import hashlib
import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import quote, urlsplit

from dsh_eval.__main__ import main
from dsh_eval.browser import ArtifactBrowser, create_server, TRACE_LINE_BYTES
from dsh_eval.experiment import run_experiment
from dsh_eval.formats import load_json
from dsh_eval.report import generate_report
from dsh_eval.runner import ROOT


class BrowserTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsh-browser-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.cases = self.directory / "cases"
        self.runs = self.directory / "runs"
        self.browser = ArtifactBrowser(self.cases, self.runs)
        self.case = load_json(ROOT / "fixtures/evaluation/retry-read.case.json")
        self.write(self.cases / "中文.case.json", self.case)
        self.evaluation = {"evaluationFormatVersion": 2, "caseId": self.case["caseId"], "caseRunId": "one",
                           "source": "synthetic", "outcome": "unevaluable", "configuration": None,
                           "execution": {"status": "cancelled"}, "recording": {"outcome": "complete"},
                           "assertions": {"outcome": "not_run"}, "association": {"runDir": "traces/recording"}}
        self.write(self.runs / "one/evaluation.json", self.evaluation)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def digest(self):
        return {str(path.relative_to(self.directory)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.directory.rglob("*") if path.is_file()}

    def server(self):
        server = create_server(self.cases, self.runs)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def close():
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.addCleanup(close)
        self.token = urlsplit(server.browser_url).fragment.split("=", 1)[1]
        self.port = server.server_port
        return server

    def request(self, path, *, method="GET", auth=True, headers=None):
        values = {"Authorization": "Bearer " + self.token} if auth else {}
        values.update(headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(connection.close)
        connection.request(method, path, headers=values)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()

    def test_catalog_preserves_saved_outcomes_and_prunes_private_directories(self):
        for directory in ("home", "workspace", "private-notes", ".git", "node_modules", "secrets"):
            self.write(self.runs / directory / "evaluation.json", self.evaluation)
        self.write(self.runs / "one/credentials.json", {"password": "not-an-artifact"})
        catalog = self.browser.catalog()
        self.assertEqual({item["kind"] for item in catalog["items"]}, {"case", "evaluation"})
        self.assertEqual(len(catalog["items"]), 2)
        self.assertEqual(catalog["items"][1]["outcome"], "unevaluable")
        self.assertEqual(catalog["items"][1]["source"], "synthetic")
        self.assertEqual(catalog["items"][1]["status"], "cancelled")
        self.assertEqual(catalog["items"][1]["sources"], ["synthetic"])
        self.assertFalse(catalog["truncated"])

    def test_reading_saved_conclusions_does_not_evaluate_or_mutate_files(self):
        self.write(self.runs / "report/report.json", {"comparisonReportFormatVersion": 1,
                   "summary": {"outcomes": {"passed": 2, "failed": 0, "unevaluable": 1}}})
        before = self.digest()
        with patch("dsh_eval.evaluate.evaluate", side_effect=AssertionError("must not evaluate")), \
                patch("dsh_eval.runner.run_case", side_effect=AssertionError("must not run")):
            document = self.browser.document("runs:one/evaluation.json")
        self.assertEqual(document["data"], self.evaluation)
        self.assertEqual(document["data"]["execution"]["status"], "cancelled")
        self.assertEqual(document["data"]["assertions"]["outcome"], "not_run")
        report = next(item for item in self.browser.catalog()["items"] if item["kind"] == "report")
        self.assertIsNone(report["outcome"])
        self.assertEqual(report["outcomes"], {"passed": 2, "failed": 0, "unevaluable": 1})
        self.assertEqual(self.digest(), before)

    def test_catalog_keeps_missing_sources_in_mixed_results(self):
        self.write(self.runs / "mixed/report.json", {"comparisonReportFormatVersion": 1,
                   "samples": [{"source": "live"}, {"source": "synthetic"}, {"source": None}, {}]})
        self.write(self.runs / "missing/experiment-result.json", {"experimentResultFormatVersion": 1,
                   "samples": [{"source": None}, {}]})
        catalog = {item["id"]: item for item in self.browser.catalog()["items"]}
        self.assertEqual(catalog["runs:mixed/report.json"]["sources"], ["live", "synthetic", "unknown"])
        self.assertEqual(catalog["runs:missing/experiment-result.json"]["sources"], ["unknown"])
        self.assertEqual(catalog["runs:one/evaluation.json"]["sources"], ["synthetic"])

    def test_missing_and_malformed_files_are_visible_and_refresh_finds_new_files(self):
        catalog = ArtifactBrowser(self.cases, self.directory / "absent").catalog()
        self.assertEqual(len(catalog["warnings"]), 1)
        path = self.runs / "broken/report.json"
        path.parent.mkdir()
        path.write_text("{", encoding="utf-8")
        item = next(item for item in self.browser.catalog()["items"] if "broken" in item["id"])
        self.assertIn("error", item)
        self.write(path, {"comparisonReportFormatVersion": 1, "reportId": "new"})
        item = next(item for item in self.browser.catalog()["items"] if "broken" in item["id"])
        self.assertEqual(item["kind"], "report")
        path.unlink()
        with self.assertRaises(ValueError):
            self.browser.document(item["id"])

    def test_paths_cannot_escape_roots_or_read_other_local_files(self):
        for identifier in ("runs:../cases/中文.case.json", "runs:/etc/passwd", "runs:C:/secret.json",
                           "runs:one/../one/evaluation.json", "runs:one\\evaluation.json", "runs:one//evaluation.json",
                           "other:one/evaluation.json", "runs:one/evaluation.json:stream", "runs:one/home/evaluation.json",
                           "runs:one/.credentials.json", "runs:one/stdout.txt"):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                self.browser.document(identifier)
        self.write(self.runs / "credentials.json", {"secret": "not served"})
        with self.assertRaises(ValueError):
            self.browser.document("runs:credentials.json")
        self.assertIsNone(self.browser.reference(self.cases.parent / "outside.json"))

    def test_symbolic_directory_cannot_expose_outside_or_private_paths(self):
        # Windows directory junctions require no developer-mode symlink privilege.
        import os
        import subprocess
        outside = self.directory / "outside"
        self.write(outside / "evaluation.json", self.evaluation)
        self.write(self.runs / "home/evaluation.json", self.evaluation)
        for name, destination in (("escaped", outside), ("aliased", self.runs / "home"), ("cycle", self.runs)):
            link = self.runs / name
            if os.name == "nt":
                subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(destination)],
                               capture_output=True, check=True)
            else:
                link.symlink_to(destination, target_is_directory=True)
            if name != "cycle":
                with self.subTest(name=name), self.assertRaises(ValueError):
                    self.browser.document(f"runs:{name}/evaluation.json")
        self.assertEqual(len(self.browser.catalog()["items"]), 2)

    def test_links_reject_external_and_private_paths_before_filesystem_resolution(self):
        outside = self.directory / "outside/evaluation.json"
        data = {"casePath": str(outside), "evidencePath": "../../outside/evidence.json",
                "association": {"runtimeReport": str(self.runs / "home/runtime.json"),
                                "runDir": "//m5-review.invalid/share/recording"},
                "samples": [{"sourceEvidencePath": str(self.runs / "../outside/evidence.json")}]}
        with patch.object(Path, "resolve", side_effect=AssertionError("Must reject before filesystem resolution")):
            self.assertIsNone(self.browser.reference(outside))
            links = self.browser._links(data, self.runs / "one")
        self.assertEqual(len(links), 5)
        self.assertTrue(all(link["id"] is None for link in links))

    def test_configured_root_alias_keeps_absolute_links_readable(self):
        import os
        import subprocess
        alias = self.directory / "runs-alias"
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(self.runs)], capture_output=True, check=True)
        else:
            alias.symlink_to(self.runs, target_is_directory=True)
        self.write(self.runs / "one/runtime.json", {"runtimeFormatVersion": 1})
        self.evaluation["association"]["runtimeReport"] = str(alias / "one/runtime.json")
        self.write(self.runs / "one/evaluation.json", self.evaluation)
        browser = ArtifactBrowser(self.cases, alias)
        links = browser.document("runs:one/evaluation.json")["links"]
        self.assertEqual(next(link["id"] for link in links if link["label"] == "association / runtimeReport"),
                         "runs:one/runtime.json")
        self.assertEqual(browser.reference(browser.roots["runs"] / "one/runtime.json"), "runs:one/runtime.json")
        with patch.object(Path, "resolve", side_effect=AssertionError("Must still reject external paths before resolving")):
            self.assertIsNone(browser.reference(self.directory / "outside/runtime.json"))

    def test_links_resolve_snapshots_runtime_trace_and_report_with_missing_markers(self):
        directory = self.runs / "one"
        trace = directory / "traces/recording" / ("a" * 64 + ".jsonl")
        trace.parent.mkdir(parents=True)
        trace.write_text('{"event":{"type":"turn/end"}}\n', encoding="utf-8")
        self.write(trace.parent / "run.json", {"formatVersion": 1})
        self.write(directory / "runtime.json", {"runtimeFormatVersion": 1})
        self.evaluation["association"]["runtimeReport"] = str(directory / "runtime.json")
        self.write(directory / "evaluation.json", self.evaluation)
        document = self.browser.document("runs:one/evaluation.json")
        self.assertTrue(any(link["id"] and link["id"].endswith(".jsonl") for link in document["links"]))
        self.assertTrue(any(link["id"] == "runs:one/runtime.json" for link in document["links"]))
        report = {"comparisonReportFormatVersion": 1, "samples": [{"evaluationPath": "../one/evaluation.json",
                  "sourceEvidencePath": str(self.directory / "outside.json")}], "sourceExperimentResult": "gone.json"}
        self.write(self.runs / "report/report.json", report)
        (self.runs / "report/report.md").write_text("# <script>原样显示</script>", encoding="utf-8")
        links = self.browser.document("runs:report/report.json")["links"]
        self.assertEqual(next(link["id"] for link in links if link["label"] == "1 / evaluationPath"), "runs:one/evaluation.json")
        self.assertIsNone(next(link["id"] for link in links if link["label"] == "1 / sourceEvidencePath"))
        self.assertEqual(self.browser.document("runs:report/report.md")["text"], "# <script>原样显示</script>")

    def test_trace_pagination_keeps_line_numbers_errors_and_oversized_previews(self):
        trace = self.runs / ("b" * 64 + ".jsonl")
        trace.write_bytes(b'{"event":{"type":"tool/call"}}\n' + b'{bad\n' + b'x' * (TRACE_LINE_BYTES * 2) + b'\n' + b'{"ok":true}\n')
        before = self.digest()
        identifier = "runs:" + trace.name
        first = self.browser.document(identifier, limit=2)
        self.assertEqual([row["line"] for row in first["rows"]], [1, 2])
        self.assertIn("error", first["rows"][1])
        self.assertEqual(first["nextOffset"], 2)
        second = self.browser.document(identifier, offset=2, limit=2)
        self.assertIn("64 KiB", second["rows"][0]["error"])
        self.assertLessEqual(len(second["rows"][0]["preview"]), 2048)
        self.assertEqual(second["rows"][1], {"line": 4, "data": {"ok": True}})
        self.assertIsNone(second["nextOffset"])
        self.assertEqual(self.browser.document(identifier, offset=10)["rows"], [])
        self.assertEqual(self.digest(), before)
        for options in ({"offset": -1}, {"limit": 201}, {"limit": 0}, {"offset": 1000001}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.browser.document(identifier, **options)

    def test_unsupported_versions_duplicate_keys_and_size_limits_are_explicit(self):
        for content in ('{"evaluationFormatVersion":true}', '{"evaluationFormatVersion":9}',
                        '{"evaluationFormatVersion":2,"a":1,"a":2}', '{"evaluationFormatVersion":2,"a":NaN}'):
            (self.runs / "one/evaluation.json").write_text(content, encoding="utf-8")
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.browser.document("runs:one/evaluation.json")
        with patch("dsh_eval.browser.MAX_DOCUMENT_BYTES", 10), self.assertRaisesRegex(ValueError, "8 MiB"):
            self.browser.document("cases:中文.case.json")
        with patch("dsh_eval.browser.MAX_CATALOG_ITEMS", 1):
            self.assertTrue(self.browser.catalog()["truncated"])
        self.write(self.runs / "one/evaluation.json", {"evaluationFormatVersion": 2, "samples": 123})
        self.assertIn("error", self.browser.catalog()["items"][1])

    def test_deep_json_is_isolated_in_catalog_and_http(self):
        path = self.runs / "deep/evaluation.json"
        path.parent.mkdir()
        self.server()
        for depth in (256, 1500):
            with self.subTest(depth=depth):
                path.write_text('{"evaluationFormatVersion":2,"deep":' + '[' * depth + '0' + ']' * depth + '}',
                                encoding="utf-8")
                before = self.digest()
                with self.assertRaisesRegex(ValueError, "nesting"):
                    self.browser.document("runs:deep/evaluation.json")
                status, _, body = self.request("/api/catalog")
                self.assertEqual(status, 200)
                items = {item["id"]: item for item in json.loads(body)["items"]}
                self.assertIn("nesting", items["runs:deep/evaluation.json"]["error"])
                self.assertNotIn("error", items["runs:one/evaluation.json"])
                status, _, body = self.request("/api/document?id=runs:deep/evaluation.json")
                self.assertEqual(status, 400)
                self.assertIn("nesting", json.loads(body)["error"])
                self.assertEqual(self.request("/api/document?id=runs:one/evaluation.json")[0], 200)
                self.assertEqual(self.digest(), before)

    def test_deep_trace_rows_keep_previews_and_following_rows(self):
        trace = self.runs / ("c" * 64 + ".jsonl")
        self.server()
        for depth in (256, 1500):
            with self.subTest(depth=depth):
                trace.write_text('{"event":{"type":"viewer/check","data":' + '[' * depth + '0' + ']' * depth
                                 + '}}\n{"event":{"type":"turn/end"}}\n', encoding="utf-8")
                before = self.digest()
                status, _, body = self.request("/api/document?id=" + quote("runs:" + trace.name))
                self.assertEqual(status, 200)
                document = json.loads(body)
                self.assertIn("nesting", document["rows"][0]["error"])
                self.assertLessEqual(len(document["rows"][0]["preview"].encode("utf-8")), 2048)
                self.assertEqual(document["rows"][1], {"line": 2, "data": {"event": {"type": "turn/end"}}})
                self.assertIsNone(document["nextOffset"])
                self.assertEqual(self.digest(), before)

    def test_http_authentication_origin_host_and_write_rejection(self):
        server = self.server()
        self.assertEqual(server.server_address[0], "127.0.0.1")
        self.assertNotIn(self.token, urlsplit(server.browser_url).query)
        for options in ({"auth": False}, {"headers": {"Authorization": "Bearer wrong"}},
                        {"headers": {"Authorization": "Bearer é"}}, {"headers": {"Host": "attacker.invalid"}},
                        {"headers": {"Origin": "https://attacker.invalid"}}):
            with self.subTest(options=options):
                self.assertEqual(self.request("/api/catalog", **options)[0], 403)
        status, headers, body = self.request("/api/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["items"][0]["title"], self.case["caseId"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        before = self.digest()
        self.assertEqual(self.request("/api/document", method="POST")[0], 405)
        self.assertEqual(self.digest(), before)

    def test_http_document_errors_and_assets_are_returned_without_execution(self):
        self.server()
        with patch("dsh_eval.evaluate.evaluate", side_effect=AssertionError("must not evaluate")):
            status, _, body = self.request("/api/document?id=" + quote("runs:one/evaluation.json"))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["data"], self.evaluation)
        for path in ("/api/document", "/api/document?id=x&id=y", "/api/document?id=x&offset=bad", "/api/catalog?run=true"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 400)
        for path, mime in (("/", "text/html"), ("/app.js", "text/javascript"), ("/style.css", "text/css")):
            status, headers, body = self.request(path, auth=False)
            self.assertEqual(status, 200)
            self.assertIn(mime, headers["Content-Type"])
            self.assertGreater(len(body), 100)
        self.assertEqual(self.request("/../private-notes/handoff.md")[0], 404)

    def test_cli_accepts_browse_roots_but_rejects_execution_flags(self):
        with patch("dsh_eval.browser.serve") as serve:
            self.assertEqual(main(["--browse", "--cases-root", str(self.cases), "--runs-root", str(self.runs), "--port", "0"]), 0)
        serve.assert_called_once_with(str(self.cases), str(self.runs), 0)
        for arguments in (["--browse", "--run"], ["--browse", "--evidence", "x"], ["--browse", "--reports-root", "x"],
                          ["--browse", "--output", "x"], ["--case", "x", "--port", "0"]):
            with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(arguments)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--browse", "--port", "-1"]), 2)
        self.assertEqual(json.loads(output.getvalue())["browserFormatVersion"], 1)

    def test_real_synthetic_experiment_report_and_evidence_browse_without_rewriting(self):
        self.case["configRef"].update(provider="synthetic", model="first")
        self.write(self.cases / "中文.case.json", self.case)
        manifest = {"experimentFormatVersion": 1, "experimentName": "中文合成浏览验收", "repetitions": 1,
                    "failurePolicy": "continue", "cases": [{"entryId": "retry", "casePath": "中文.case.json"}],
                    "configurations": [{"configurationId": model, "configRef": {**self.case["configRef"], "model": model}}
                                       for model in ("first", "second")]}
        path = self.write(self.cases / "experiment.json", manifest)
        with patch("dsh_eval.runner._prepare"), patch("dsh_eval.runner.ADAPTER", ROOT / "scripts/fixtures/batch-adapter.js"):
            experiment = run_experiment(path, self.runs / "experiments")
        directory = Path(experiment["experimentDirectory"])
        batch = load_json(directory / experiment["batchResultPath"])
        for sample, row in zip(experiment["samples"], batch["entries"]):
            evidence_path = directory / sample["evidencePath"]
            evidence = load_json(evidence_path)
            evidence["source"] = sample["source"] = row["source"] = "synthetic"
            self.write(evidence_path, evidence)
        self.write(directory / "experiment-result.json", experiment)
        self.write(directory / experiment["batchResultPath"], batch)
        report = generate_report(directory / "experiment-result.json", self.runs / "reports")
        before = self.digest()
        catalog = self.browser.catalog()
        self.assertTrue({"case", "experiment", "batch", "evaluation", "report"} <= {item["kind"] for item in catalog["items"]})
        visited = set()
        pending = [item["id"] for item in catalog["items"]]
        with patch("dsh_eval.evaluate.evaluate", side_effect=AssertionError("browse must not recheck")):
            while pending:
                identifier = pending.pop()
                if identifier in visited:
                    continue
                visited.add(identifier)
                document = self.browser.document(identifier)
                pending.extend(link["id"] for link in document["links"] if link["id"])
        self.assertTrue(any(identifier.endswith(".jsonl") for identifier in visited))
        self.assertEqual(report["summary"]["planned"], 2)
        self.assertEqual(report["comparisons"][0]["pairedSamples"], 1)
        self.assertEqual(self.digest(), before)


if __name__ == "__main__":
    unittest.main()
