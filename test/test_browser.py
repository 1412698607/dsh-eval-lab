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
from dsh_eval.browser import ArtifactBrowser, create_server, TRACE_LINE_BYTES, MAX_DOCUMENT_BYTES
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

    def diagnostic_trace(self, events=None):
        session = "diagnostic-session"
        filename = hashlib.sha256(session.encode()).hexdigest() + ".jsonl"
        path = self.runs / "one/traces/recording" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = events if events is not None else [{"formatVersion": 1, "runId": "recording", "sessionId": session,
            "event": {"seq": index + 100, "type": "assistant/message", "data": {}}} for index in range(65)]
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        self.evaluation["association"].update(runId="recording", sessionId=session)
        self.write(self.runs / "one/evaluation.json", self.evaluation)
        return path, "runs:one/traces/recording/" + filename, session

    def test_assertion_trace_uses_associated_session_and_existing_allowed_file(self):
        path, identifier, session = self.diagnostic_trace()
        self.write(path.with_name("a" * 64 + ".jsonl"), {})
        before = self.digest()
        with patch("dsh_eval.evaluate.inspect_recording", side_effect=AssertionError("must not inspect")), \
                patch("dsh_eval.runner.run_case", side_effect=AssertionError("must not run")):
            document = self.browser.document("runs:one/evaluation.json")
            self.assertEqual(document["assertionTrace"], {"id": identifier, "runId": "recording", "sessionId": session})
        self.assertEqual(self.digest(), before)
        for association in ({}, {"runId": "recording", "sessionId": "missing", "runDir": "traces/recording"},
                            {"runId": "recording", "sessionId": session, "runDir": "home/recording"}):
            self.evaluation["association"] = association
            self.write(self.runs / "one/evaluation.json", self.evaluation)
            self.assertNotIn("assertionTrace", self.browser.document("runs:one/evaluation.json"))

    def test_http_event_focus_uses_identity_and_seq_not_file_line_without_writes(self):
        path, identifier, session = self.diagnostic_trace()
        self.server()
        before = self.digest()
        with patch("dsh_eval.evaluate.inspect_recording", side_effect=AssertionError("must not inspect")), \
                patch("dsh_eval.runner.run_case", side_effect=AssertionError("must not run")):
            status, _, body = self.request("/api/document?id=" + quote(identifier)
                                          + "&seq=160&runId=recording&sessionId=" + session)
            self.assertEqual(status, 200)
            result = json.loads(body)
            self.assertEqual(result["focus"]["line"], 61)
            self.assertEqual(result["offset"], 55)
            self.assertEqual(result["rows"][5]["data"]["event"]["seq"], 160)
            self.assertEqual(self.browser.document(identifier, seq=160, run_id="recording", session_id=session, limit=1)["rows"][0]["line"], 61)
            for suffix in ("&seq=", "&seq=160", "&seq=160&runId=&sessionId=" + session,
                           "&seq=-1&runId=recording&sessionId=" + session,
                           "&seq=999&runId=recording&sessionId=" + session,
                           "&seq=160&runId=other&sessionId=" + session,
                           "&seq=160&runId=recording&sessionId=other", "&seq=1&seq=2"):
                self.assertEqual(self.request("/api/document?id=" + quote(identifier) + suffix)[0], 400)
            self.assertEqual(self.request("/api/document?id=runs:one/evaluation.json&seq=160&runId=recording&sessionId=" + session)[0], 400)
        self.assertEqual(self.digest(), before)

    def test_focus_rejects_ambiguous_invalid_or_unpreviewable_events(self):
        path, identifier, session = self.diagnostic_trace()
        row = {"formatVersion": 1, "runId": "recording", "sessionId": session, "event": {"seq": 7}}
        for rows in ([row, row], [{**row, "formatVersion": True}], [{**row, "event": {"seq": True}}],
                     [{**row, "padding": "x" * TRACE_LINE_BYTES}]):
            self.diagnostic_trace(rows)
            with self.assertRaisesRegex(ValueError, "missing, ambiguous"):
                self.browser.document(identifier, seq=7, run_id="recording", session_id=session)
        self.diagnostic_trace([row])
        for seq in (True, -1, 1.5, 9007199254740992):
            with self.assertRaisesRegex(ValueError, "Invalid event locator"):
                self.browser.document(identifier, seq=seq, run_id="recording", session_id=session)
        path.write_bytes(b"x" * (MAX_DOCUMENT_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "8 MiB"):
            self.browser.document(identifier, seq=7, run_id="recording", session_id=session)

    def test_focus_keeps_malformed_rows_and_other_sessions_from_shifting_target(self):
        path, identifier, session = self.diagnostic_trace()
        row = {"formatVersion": 1, "runId": "recording", "sessionId": session, "event": {"seq": 7}}
        path.write_bytes(b"bad json\n" + b"x" * (TRACE_LINE_BYTES + 10) + b"\n"
                         + json.dumps({**row, "sessionId": "other"}).encode() + b"\n" + json.dumps(row).encode())
        result = self.browser.document(identifier, seq=7, run_id="recording", session_id=session)
        self.assertEqual(result["focus"]["line"], 4)
        self.assertIn("error", result["rows"][0])
        self.assertIn("error", result["rows"][1])
        self.assertEqual(result["rows"][3]["data"], row)
        raw = json.dumps(row).encode()
        for ending in (b"", b"\n"):
            path.write_bytes(raw + b" " * (TRACE_LINE_BYTES - len(raw) - len(ending)) + ending)
            result = self.browser.document(identifier, seq=7, run_id="recording", session_id=session)
            self.assertEqual(result["focus"]["line"], 1)
            self.assertEqual(result["rows"][0]["data"], row)

    def test_focus_refuses_a_row_changed_between_lookup_and_page_read(self):
        path, identifier, session = self.diagnostic_trace()
        def changed(*args):
            path.write_text('{"event":{"seq":160},"sessionId":"other"}\n', encoding="utf-8")
            return {"seq": 160, "line": 1, "runId": "recording", "sessionId": session}
        with patch.object(self.browser, "_trace_focus", side_effect=changed), self.assertRaisesRegex(ValueError, "changed during reading"):
            self.browser.document(identifier, seq=160, run_id="recording", session_id=session)

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

    def test_catalog_lists_both_resume_kinds_and_versions_without_reports_or_execution(self):
        saved = {}
        for name, version, filename, field in (
                ("batch", 1, "resume-result.json", "batchResumeResultFormatVersion"),
                ("first", 1, "experiment-resume-result.json", "experimentResumeResultFormatVersion"),
                ("chain", 2, "experiment-resume-result.json", "experimentResumeResultFormatVersion")):
            saved[f"runs:{name}/{filename}"] = {field: version, "resumeId": name + "-identity",
                "status": "completed", "outcome": "failed", "finishedAt": "2026-11-01T00:00:00Z"}
            self.write(self.runs / name / filename, saved[f"runs:{name}/{filename}"])
        before = self.digest()
        with patch("dsh_eval.evaluate.evaluate", side_effect=AssertionError("must not evaluate")), \
                patch("dsh_eval.runner.run_case", side_effect=AssertionError("must not run")):
            catalog = {item["id"]: item for item in self.browser.catalog()["items"]}
            for identifier, data in saved.items():
                with self.subTest(identifier=identifier):
                    item = catalog[identifier]
                    self.assertEqual(item["kind"], "batch_resume" if identifier.startswith("runs:batch/") else "experiment_resume")
                    self.assertEqual(item["title"], data["resumeId"])
                    self.assertEqual((item["status"], item["outcome"], item["time"]),
                                     (data["status"], data["outcome"], data["finishedAt"]))
                    self.assertEqual(item["sources"], ["unknown"])
                    self.assertEqual(self.browser.document(identifier)["data"], data)
        self.assertEqual(self.digest(), before)

    def test_resume_catalog_sources_use_saved_combined_or_new_and_reused_declarations(self):
        fixtures = [
            ("combined", {"batchResumeResultFormatVersion": 1,
                "combinedSummary": {"sourceCounts": {"live": 2, "unknown": 1, "synthetic": 0,
                    "negative": -1, "boolean": True, "float": 1.0}},
                "reusedEntries": [{"source": "synthetic"}]}, ["live", "unknown"]),
            ("experiment", {"experimentResumeResultFormatVersion": 1,
                "newlyExecutedSummary": {"sourceCounts": {"live": 2}},
                "samplePlan": [{"disposition": "reuse", "source": "synthetic"},
                    {"disposition": "reuse", "source": None},
                    {"disposition": "pending", "source": "stale-pending"}]}, ["live", "synthetic", "unknown"]),
            ("batch", {"batchResumeResultFormatVersion": 1,
                "newlyExecutedSummary": {"sourceCounts": {"synthetic": 2}},
                "reusedEntries": [{"source": "live"}, {}]}, ["live", "synthetic", "unknown"]),
            ("running", {"experimentResumeResultFormatVersion": 2, "status": "running",
                "combinedSummary": None, "newlyExecutedSummary": None,
                "samplePlan": [{"disposition": "reuse", "source": "live"}]}, ["live", "unknown"]),
            ("missing-history", {"batchResumeResultFormatVersion": 1,
                "newlyExecutedSummary": {"sourceCounts": {"live": 2}}}, ["live", "unknown"]),
        ]
        for name, data, expected in fixtures:
            filename = "resume-result.json" if "batchResumeResultFormatVersion" in data else "experiment-resume-result.json"
            self.write(self.runs / name / filename, data)
        catalog = {item["path"].split("/", 1)[0]: item for item in self.browser.catalog()["items"] if item["kind"].endswith("_resume")}
        for name, data, expected in fixtures:
            with self.subTest(name=name):
                self.assertEqual(catalog[name]["sources"], expected)
                self.assertNotIn("error", catalog[name])

    def test_resume_catalog_keeps_bad_files_isolated_and_private_results_pruned(self):
        for name in ("resume-result.json", "experiment-resume-result.json"):
            path = self.runs / "broken" / name
            path.parent.mkdir(exist_ok=True)
            path.write_text("{", encoding="utf-8")
            self.write(self.runs / "home" / name, {"batchResumeResultFormatVersion": 1})
        self.write(self.runs / "future/experiment-resume-result.json", {"experimentResumeResultFormatVersion": 3})
        self.write(self.runs / "bad-rows/resume-result.json", {"batchResumeResultFormatVersion": 1,
                   "reusedEntries": "not-an-array"})
        self.write(self.runs / "good/resume-result.json", {"batchResumeResultFormatVersion": 1,
                   "batchName": "Named continuation", "resumeId": "fallback", "reusedEntries": []})
        catalog = {item["id"]: item for item in self.browser.catalog()["items"]}
        self.assertTrue(all("error" in item for identifier, item in catalog.items()
                            if "/broken/" in identifier or "/future/" in identifier or "/bad-rows/" in identifier))
        self.assertFalse(any("/home/" in identifier for identifier in catalog))
        self.assertEqual(catalog["runs:good/resume-result.json"]["title"], "Named continuation")
        self.assertNotIn("error", catalog["runs:good/resume-result.json"])

    def test_http_catalog_and_documents_expose_saved_resumes_without_writes(self):
        identifier = "runs:resume/experiment-resume-result.json"
        saved = {"experimentResumeResultFormatVersion": 2, "resumeId": "saved-resume",
                 "combinedSummary": {"sourceCounts": {"live": 1, "unknown": 1}}, "status": "stopped",
                 "outcome": "unevaluable", "sourceResumeResult": "missing/experiment-resume-result.json"}
        self.write(self.runs / "resume/experiment-resume-result.json", saved)
        self.server()
        before = self.digest()
        with patch("dsh_eval.evaluate.evaluate", side_effect=AssertionError("must not evaluate")), \
                patch("dsh_eval.runner.run_case", side_effect=AssertionError("must not run")):
            status, _, body = self.request("/api/catalog")
            self.assertEqual(status, 200)
            item = next(item for item in json.loads(body)["items"] if item["id"] == identifier)
            self.assertEqual((item["kind"], item["sources"]), ("experiment_resume", ["live", "unknown"]))
            status, _, body = self.request("/api/document?id=" + quote(identifier))
            self.assertEqual(status, 200)
            document = json.loads(body)
            self.assertEqual(document["data"], saved)
            self.assertIsNone(next(link["id"] for link in document["links"] if link["label"] == "sourceResumeResult"))
            self.assertEqual(self.request("/api/catalog", method="POST")[0], 405)
        self.assertEqual(self.digest(), before)

    def test_version_two_report_and_explicit_continuation_links_are_read_only(self):
        original = self.write(self.runs / "original/experiment-result.json", {"experimentResultFormatVersion": 1})
        old_batch = self.write(self.runs / "old/batch-result.json", {"batchResultFormatVersion": 1})
        new_batch = self.write(self.runs / "new/batch-result.json", {"batchResultFormatVersion": 1})
        continuation = self.write(self.runs / "resume/experiment-resume-result.json", {"experimentResumeResultFormatVersion": 1,
            "batchResumeResultPath": "child/resume-result.json", "sourceBatchResult": str(old_batch)})
        child = self.write(continuation.parent / "child/resume-result.json", {"batchResumeResultFormatVersion": 1,
            "sourceBatchResult": str(old_batch), "batchResultPath": "../../new/batch-result.json"})
        report = {"comparisonReportFormatVersion": 2, "reportId": "resumed", "batchId": None,
            "batchIds": ["old", "new"], "sourceExperimentResult": str(original), "sourceResumeResult": str(continuation),
            "resumeVerification": {"status": "verified", "batchResumeResult": str(child)},
            "samples": [{"executionOrigin": "reused", "source": "synthetic", "sourceBatchResult": str(old_batch)},
                        {"executionOrigin": "new", "source": None, "sourceBatchResult": str(new_batch)}]}
        self.write(self.runs / "report/report.json", report)
        before = self.digest()
        with patch("dsh_eval.report.evaluate", side_effect=AssertionError("browse must not inspect")), \
                patch("dsh_eval.runner.run_case", side_effect=AssertionError("browse must not run")):
            item = next(item for item in self.browser.catalog()["items"] if item["id"] == "runs:report/report.json")
            self.assertEqual(item["kind"], "report")
            self.assertNotIn("error", item)
            self.assertEqual(item["sources"], ["synthetic", "unknown"])
            document = self.browser.document(item["id"])
            self.assertEqual(document["data"], report)
            links = {link["label"]: link["id"] for link in document["links"]}
            self.assertEqual(links["sourceResumeResult"], "runs:resume/experiment-resume-result.json")
            self.assertEqual(links["resumeVerification / batchResumeResult"], "runs:resume/child/resume-result.json")
            self.assertEqual(links["1 / sourceBatchResult"], "runs:old/batch-result.json")
            self.assertEqual(links["2 / sourceBatchResult"], "runs:new/batch-result.json")
            self.assertEqual(self.browser.document(links["sourceResumeResult"])["data"]["experimentResumeResultFormatVersion"], 1)
            child_document = self.browser.document(links["resumeVerification / batchResumeResult"])
            self.assertEqual(next(link["id"] for link in child_document["links"] if link["label"] == "batchResultPath"),
                             "runs:new/batch-result.json")
        self.assertEqual(self.digest(), before)

    def test_version_two_new_links_reject_external_unc_private_and_missing_targets(self):
        data = {"sourceResumeResult": str(self.directory / "outside/experiment-resume-result.json"),
                "resumeVerification": {"batchResumeResult": "//viewer-v2.invalid/share/resume-result.json"},
                "samples": [{"sourceBatchResult": str(self.runs / "home/batch-result.json")}]}
        with patch.object(Path, "resolve", side_effect=AssertionError("Reject external references before resolving")):
            links = self.browser._links(data, self.runs / "report")
        self.assertEqual(len(links), 3)
        self.assertTrue(all(link["id"] is None for link in links))
        self.write(self.runs / "report/report.json", {"comparisonReportFormatVersion": 2,
                   "sourceResumeResult": "missing/experiment-resume-result.json"})
        document = self.browser.document("runs:report/report.json")
        self.assertIsNone(next(link["id"] for link in document["links"] if link["label"] == "sourceResumeResult"))

    def test_http_running_experiment_binding_opens_refreshed_batch_checkpoints_without_execution(self):
        source = {"experimentResultFormatVersion": 1, "experimentId": "running-experiment", "status": "running",
                  "outcome": None, "batchResultPath": None,
                  "batchBinding": {"batchId": "bound-batch", "resultPath": "batches/bound/batch-result.json"}}
        source_path = self.write(self.runs / "active/experiment-result.json", source)
        batch_path = self.runs / "active/batches/bound/batch-result.json"
        checkpoint = {"batchResultFormatVersion": 1, "batchId": "bound-batch", "status": "running",
                      "entries": [{"entryId": "one", "status": "pending"}]}
        self.write(batch_path, checkpoint)
        self.server()
        with patch("dsh_eval.evaluate.inspect_recording", side_effect=AssertionError("must not inspect")), \
                patch("dsh_eval.runner.run_case", side_effect=AssertionError("must not run")):
            for stage in ("running", "stopped"):
                if stage == "stopped":
                    checkpoint.update(status="stopped", entries=[{"entryId": "one", "status": "finished"}])
                    self.write(batch_path, checkpoint)
                before = self.digest()
                status, _, body = self.request("/api/document?id=runs:active/experiment-result.json")
                self.assertEqual(status, 200)
                document = json.loads(body)
                self.assertEqual(document["data"], source)
                link = next(link for link in document["links"] if link["label"] == "batchBinding / resultPath")
                self.assertEqual(link["id"], "runs:active/batches/bound/batch-result.json")
                status, _, body = self.request("/api/document?id=" + quote(link["id"]))
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["data"], checkpoint)
                self.assertEqual(self.digest(), before)
        self.assertEqual(load_json(source_path), source)

    def test_unfinished_result_binding_fallback_accepts_missing_null_or_empty_explicit_path(self):
        self.write(self.runs / "batch/batch-result.json", {"batchResultFormatVersion": 1})
        for field in ("experimentResultFormatVersion", "batchResumeResultFormatVersion"):
            for values in ({}, {"batchResultPath": None}, {"batchResultPath": ""}):
                data = {field: 1, "status": "running", "batchBinding": {"resultPath": "batch/batch-result.json"}, **values}
                with self.subTest(field=field, values=values):
                    self.assertEqual(self.browser._links(data, self.runs), [{"label": "batchBinding / resultPath",
                        "id": "runs:batch/batch-result.json", "path": "batch/batch-result.json"}])

    def test_binding_fallback_preserves_external_private_missing_and_malformed_boundaries(self):
        for value in (str(self.directory / "outside/batch-result.json"), "//binding.invalid/share/batch-result.json",
                      str(self.runs / "home/batch-result.json")):
            with self.subTest(value=value), patch.object(Path, "resolve", side_effect=AssertionError("Reject before resolving")):
                links = self.browser._links({"batchBinding": {"resultPath": value}}, self.runs)
                self.assertEqual(links, [{"label": "batchBinding / resultPath", "id": None, "path": value}])
        self.assertEqual(self.browser._links({"batchBinding": {"resultPath": "missing/batch-result.json"}}, self.runs),
                         [{"label": "batchBinding / resultPath", "id": None, "path": "missing/batch-result.json"}])
        for binding in (None, [], "batch/batch-result.json", 1, {"resultPath": None}, {"resultPath": []}):
            with self.subTest(binding=binding):
                self.assertEqual(self.browser._links({"batchBinding": binding}, self.runs), [])

    def test_explicit_result_path_prevents_duplicate_binding_or_invalid_path_fallback(self):
        self.write(self.runs / "batch/batch-result.json", {"batchResultFormatVersion": 1})
        binding = {"resultPath": "batch/batch-result.json"}
        for explicit, expected in (("batch/batch-result.json", "runs:batch/batch-result.json"),
                                   ("missing/batch-result.json", None),
                                   (str(self.directory / "outside/batch-result.json"), None)):
            with self.subTest(explicit=explicit):
                links = self.browser._links({"status": "completed", "batchResultPath": explicit,
                                             "batchBinding": binding}, self.runs)
                self.assertEqual(links, [{"label": "batchResultPath", "id": expected, "path": explicit}])

    def test_invalid_explicit_path_types_do_not_fall_back_to_reserved_binding(self):
        self.write(self.runs / "batch/batch-result.json", {"batchResultFormatVersion": 1})
        for value in (False, 0, [], {}):
            with self.subTest(value=value):
                self.assertEqual(self.browser._links({"batchResultPath": value,
                    "batchBinding": {"resultPath": "batch/batch-result.json"}}, self.runs), [])

    def test_report_versions_one_to_three_are_supported_but_future_or_coerced_versions_are_not(self):
        path = self.runs / "report/report.json"
        for version in (1, 2, 3, 4, True, 2.0):
            self.write(path, {"comparisonReportFormatVersion": version})
            if type(version) is int and version in (1, 2, 3):
                self.assertEqual(self.browser.document("runs:report/report.json")["kind"], "report")
            else:
                with self.subTest(version=version), self.assertRaises(ValueError):
                    self.browser.document("runs:report/report.json")

    def test_version_three_links_include_every_batch_and_continuation_with_same_boundaries(self):
        batch = self.write(self.runs / "batch/batch-result.json", {"batchResultFormatVersion": 1})
        resumed = self.write(self.runs / "chain/experiment-resume-result.json", {"experimentResumeResultFormatVersion": 2})
        data = {"comparisonReportFormatVersion": 3, "batchResultPaths": [str(batch)],
                "resumeChain": [{"resultPath": str(resumed)}, {"resultPath": "//chain.invalid/private/result.json"}]}
        self.write(self.runs / "report/report.json", data)
        before = self.digest()
        links = {row["label"]: row["id"] for row in self.browser.document("runs:report/report.json")["links"]}
        self.assertEqual(links["批次 1 / batchResultPath"], "runs:batch/batch-result.json")
        self.assertEqual(links["续跑 1 / resultPath"], "runs:chain/experiment-resume-result.json")
        self.assertIsNone(links["续跑 2 / resultPath"])
        self.assertEqual(self.browser.document(links["续跑 1 / resultPath"])["kind"], "experiment_resume")
        self.assertEqual(self.digest(), before)

    def test_http_serves_saved_version_two_report_without_execution_or_writes(self):
        saved = {"comparisonReportFormatVersion": 2, "samples": [{"source": None, "executionOrigin": "new"}],
                 "newlyExecutedSummary": {"planned": 1, "sourceCounts": {"unknown": 1}}}
        self.write(self.runs / "report/report.json", saved)
        self.server()
        before = self.digest()
        with patch("dsh_eval.report.evaluate", side_effect=AssertionError("browse must not inspect")), \
                patch("dsh_eval.runner.run_case", side_effect=AssertionError("browse must not execute")):
            status, _, body = self.request("/api/document?id=runs:report/report.json")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["data"], saved)
            self.assertEqual(self.request("/api/document?id=runs:report/report.json", method="POST")[0], 405)
        self.assertEqual(self.digest(), before)

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
        with patch("dsh_eval.output_paths.check_output_root"), patch("dsh_eval.runner._prepare"), \
                patch("dsh_eval.runner.ADAPTER", ROOT / "scripts/fixtures/batch-adapter.js"):
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
