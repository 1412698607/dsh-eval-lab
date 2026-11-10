"""Exercise the real synthetic delivery, migration, CLI and viewer lifecycle."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from dsh_eval import delivery_check
from dsh_eval.archive_bundle import MANIFEST, verify_archive
from dsh_eval.formats import load_json
from dsh_eval.runner import ROOT


class DeliveryCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="dsh-delivery-check-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.base = Path(cls.temporary.name).resolve()  # Normalize actual NTFS 8.3 temporary roots.
        cls.directory = cls.base / "first"
        cls.result = delivery_check.generate_delivery_check(cls.directory)
        if cls.result["status"] != "completed":
            raise AssertionError(cls.result)

    def stage(self, step):
        return next(row for row in self.result["stages"] if row["step"] == step)

    def test_delivery_preserves_expected_negative_examples_and_original_sources(self):
        result = self.result
        self.assertEqual(load_json(self.directory / "delivery-result.json"), result)
        self.assertEqual((result["deliveryCheckFormatVersion"], result["source"], result["modelCalled"]),
                         (1, "synthetic", False))
        self.assertEqual(self.stage("generate-regression")["exitCodes"], [0, 1, 2])
        self.assertEqual(self.stage("generate-regression")["sourceFilesChecked"], 128)
        self.assertEqual(sum(row.get("syntheticTasks", 0) for row in result["stages"]), 13)
        self.assertTrue(all(result[key] for key in ("sourceBytesUnchanged", "packageBytesUnchanged",
                                                   "regressionSourceBytesUnchanged")))
        digests = load_json(self.directory / "delivery-sha256.json")
        for key, root in (("workflowSource", self.directory / "retired-source"),
                          ("regressionSource", self.directory / "regression-source"),
                          ("package", self.directory / "relocated/package")):
            self.assertEqual(delivery_check._hashes(delivery_check._bytes(root)), digests[key])

    def test_actual_renames_disconnect_original_source_and_recheck_four_samples(self):
        self.assertFalse(os.path.lexists(self.directory / "workflow-source"))
        self.assertFalse(os.path.lexists(self.directory / "export/package"))
        package = self.directory / "relocated/package"
        manifest = load_json(package / MANIFEST)
        self.assertEqual(manifest["logicalSourceRoot"], str(self.directory / "workflow-source"))
        self.assertFalse(Path(manifest["logicalSourceRoot"]).exists())
        self.assertEqual([row["kind"] for row in manifest["artifacts"]],
                         ["experiment", "report", "experiment_assertion_preview"])
        self.assertEqual(verify_archive(package)["status"], "verified")
        self.assertFalse(self.stage("verify-archive")["taskEvaluationPerformed"])
        report = load_json(self.stage("recheck-report")["reportPath"])
        self.assertEqual(report["verificationCounts"], {"verified": 4})
        self.assertEqual(report["summary"]["outcomes"], {"passed": 4, "failed": 0, "unevaluable": 0})
        self.assertEqual(report["summary"]["diagnosticSummary"]["passedSamplesWithFailures"], 1)
        self.assertTrue(all(row["source"] == "synthetic" and row["configurationMatch"] == "matched"
                            for row in report["samples"]))
        self.assertFalse(Path(report["reportDirectory"]).is_relative_to(package))

    def test_real_http_services_read_references_and_close_threads_and_sockets(self):
        stage = self.stage("read-only-browser")
        for key in ("regressionServer", "archiveServer"):
            self.assertEqual(stage[key], {"httpRequests": 2, "threadStopped": True, "socketClosed": True})
        self.assertFalse(any(row.name == "delivery-check-viewer" for row in threading.enumerate()))

    def test_http_request_failure_still_closes_the_real_server(self):
        servers = []
        actual = delivery_check.create_server

        def observe(*args):
            server = actual(*args)
            servers.append(server)
            return server

        with patch.object(delivery_check, "create_server", side_effect=observe):
            with self.assertRaisesRegex(ValueError, "HTTP request failed"):
                delivery_check._http_check(self.directory / "regression-source/inputs",
                                          self.directory / "regression-source", "invalid")
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0].socket.fileno(), -1)
        self.assertFalse(any(row.name == "delivery-check-viewer" for row in threading.enumerate()))
        self.assertTrue(all(not thread.is_alive() for thread in servers[0]._threads))

    def test_http_cleanup_waits_for_real_request_threads_to_finish(self):
        cases, runs = self.directory / "regression-source/inputs", self.directory / "regression-source"
        identifier = next(row["id"] for row in delivery_check.ArtifactBrowser(cases, runs).catalog()["items"]
                          if row["kind"] == "regression_comparison")
        for artifact_id in (identifier, "invalid"):
            release, entered, closing, done = (threading.Event() for _ in range(4))
            request_threads, errors, results = [], [], []
            actual = delivery_check.create_server

            def observe(*args):
                server = actual(*args)
                finish, close = server.RequestHandlerClass.finish, server.server_close

                def hold_finish(handler):
                    try:
                        finish(handler)
                    finally:
                        request_threads.append(threading.current_thread())
                        entered.set()
                        release.wait(timeout=10)

                def observe_close():
                    closing.set()
                    close()

                server.RequestHandlerClass.finish, server.server_close = hold_finish, observe_close
                return server

            def check():
                try:
                    results.append(delivery_check._http_check(cases, runs, artifact_id))
                except Exception as error:
                    errors.append(error)
                finally:
                    done.set()

            with self.subTest(artifact_id=artifact_id):
                worker = threading.Thread(target=check, name="delivery-cleanup-test")
                with patch.object(delivery_check, "create_server", side_effect=observe):
                    worker.start()
                    try:
                        self.assertTrue(entered.wait(timeout=10), "Real HTTP handler did not finish its response")
                        self.assertTrue(closing.wait(timeout=10), "HTTP server did not begin closing")
                        self.assertFalse(done.wait(timeout=0.2), "Cleanup returned while its request handler was held")
                    finally:
                        release.set()
                        worker.join(timeout=10)
                self.assertFalse(worker.is_alive())
                if artifact_id == "invalid":
                    self.assertEqual(len(errors), 1)
                    self.assertIsInstance(errors[0], ValueError)
                    self.assertIn("HTTP request failed", str(errors[0]))
                else:
                    self.assertEqual(errors, [])
                    self.assertEqual(results, [{"httpRequests": 2, "threadStopped": True, "socketClosed": True}])
                self.assertEqual(len(request_threads), 2)
                self.assertTrue(all(not thread.is_alive() for thread in request_threads))

    def test_existing_and_dangling_output_paths_are_not_overwritten(self):
        before = (self.directory / "delivery-result.json").read_bytes()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(delivery_check.main(["--output-dir", str(self.directory)]), 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "error")
        self.assertEqual((self.directory / "delivery-result.json").read_bytes(), before)
        link = self.base / "dangling-output"
        link.symlink_to(self.base / "missing-target", target_is_directory=True)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(delivery_check.main(["--output-dir", str(link)]), 2)
        self.assertTrue(link.is_symlink())
        self.assertFalse((self.base / "missing-target").exists())

    def test_move_guard_rejects_external_sources_destinations_and_existing_leaf(self):
        owned = self.base / "move-guard"
        owned.mkdir()
        inside, outside = owned / "inside", self.base / "outside"
        inside.mkdir()
        outside.mkdir()
        (inside / "keep").write_bytes(b"owned")
        (outside / "keep").write_bytes(b"outside")
        for source, destination in ((outside, owned / "target"), (inside, self.base / "external-target"),
                                    (owned, owned / "target"), (inside, outside)):
            with self.subTest(source=source, destination=destination):
                with self.assertRaisesRegex(ValueError, "inside this new delivery output"):
                    delivery_check._move_owned(owned, source, destination)
        occupied = owned / "occupied"
        occupied.mkdir()
        with self.assertRaisesRegex(ValueError, "already exists"):
            delivery_check._move_owned(owned, inside, occupied)
        dangling = owned / "dangling"
        dangling.symlink_to(owned / "absent", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "already exists"):
            delivery_check._move_owned(owned, inside, dangling)
        self.assertEqual((inside / "keep").read_bytes(), b"owned")
        self.assertEqual((outside / "keep").read_bytes(), b"outside")
        self.assertFalse((self.base / "external-target").exists())

    def test_source_read_error_and_interrupt_record_the_failing_step(self):
        for name, error, expected in (("read-error", OSError("runtime source read failed"), 2),
                                      ("interrupted", KeyboardInterrupt(), 130)):
            directory = self.base / name
            output = io.StringIO()
            with self.subTest(name=name), patch.object(delivery_check, "generate_workflow", side_effect=error):
                with redirect_stdout(output):
                    self.assertEqual(delivery_check.main(["--output-dir", str(directory)]), expected)
                result = json.loads(output.getvalue())
                self.assertEqual(result["failedStep"], "generate-workflow")
                self.assertEqual(load_json(directory / "delivery-result.json"), result)
                self.assertIn(type(error).__name__, result["error"])

    def test_cli_rebuilds_from_a_public_source_candidate_with_fresh_identities(self):
        checkout = self.base / "candidate-export"
        checkout.mkdir()
        for name in ("dsh_eval", "src", "scripts", "fixtures"):
            shutil.copytree(ROOT / name, checkout / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(ROOT / "package.json", checkout / "package.json")
        completed = subprocess.run([sys.executable, "-m", "dsh_eval.delivery_check", "--output-dir",
                                    str(self.base / "second")], cwd=checkout, capture_output=True,
                                   text=True, encoding="utf-8", timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(load_json(Path(result["outputDirectory"]) / "delivery-result.json"), result)
        old = load_json(self.directory / "relocated/package" / MANIFEST)
        new = load_json(Path(result["outputDirectory"]) / "relocated/package" / MANIFEST)
        self.assertNotEqual(old["archiveId"], new["archiveId"])
        self.assertNotEqual(old["entryPath"], new["entryPath"])
        self.assertFalse(result["modelCalled"])


if __name__ == "__main__":
    unittest.main()
