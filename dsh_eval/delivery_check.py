"""Check the fixed synthetic delivery workflow, relocation and read-only browser."""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import sys
import threading
from urllib.parse import quote, urlsplit
from uuid import uuid4

from .archive_bundle import MANIFEST, export_archive, verify_archive
from .browser import ArtifactBrowser, create_server
from .formats import load_json, require
from .regression_demo import generate_regression_demo
from .report import generate_report
from .runner import ROOT, save_json
from .workflow_demo import generate_workflow


def _bytes(directory):
    return {path.relative_to(directory).as_posix(): path.read_bytes()
            for path in sorted(directory.rglob("*")) if path.is_file()}


def _hashes(snapshot):
    return {name: hashlib.sha256(content).hexdigest() for name, content in snapshot.items()}


def _move_owned(directory, source, destination):
    """Validate both absolute targets immediately before moving an owned directory."""
    root, source, destination = directory.resolve(), Path(source), Path(destination)
    resolved_source, resolved_destination = source.resolve(), destination.resolve()
    require(resolved_source.is_absolute() and resolved_destination.is_absolute()
            and resolved_source != root and resolved_destination != root
            and resolved_source.is_relative_to(root) and resolved_destination.is_relative_to(root),
            "Directory move must stay inside this new delivery output")
    require(not source.is_symlink() and not source.is_junction() and source.is_dir(),
            "Directory move source must be an owned ordinary directory")
    require(not os.path.lexists(destination), "Directory move destination already exists")
    source.rename(destination)
    require(not os.path.lexists(source), "Directory move left the old source available")


def _http_check(cases, runs, identifier):
    server = create_server(cases, runs)
    server.daemon_threads = False  # server_close must join this check's request threads too.
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02},
                              name="delivery-check-viewer")
    try:
        thread.start()
        token = urlsplit(server.browser_url).fragment.removeprefix("token=")
        for endpoint in ("/api/catalog", "/api/document?id=" + quote(identifier, safe="")):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            try:
                connection.request("GET", endpoint, headers={"Authorization": "Bearer " + token})
                response = connection.getresponse()
                data = json.loads(response.read().decode("utf-8"))
                require(response.status == 200 and isinstance(data, dict), "Browser HTTP request failed")
                require("items" in data if endpoint == "/api/catalog" else data.get("id") == identifier,
                        "Browser HTTP response did not contain the requested artifact")
            finally:
                connection.close()
    finally:
        if thread.ident is not None:
            server.shutdown()
        server.server_close()
        if thread.ident is not None:
            thread.join(timeout=10)
    require(not thread.is_alive() and server.socket.fileno() == -1, "Browser server did not close")
    return {"httpRequests": 2, "threadStopped": True, "socketClosed": True}


def _browse(regression, package):
    browser = ArtifactBrowser(regression / "inputs", regression)
    items = [row for row in browser.catalog()["items"] if row["kind"] == "regression_comparison"]
    require(len(items) == 3, "Browser lost the three regression comparisons")
    for item in items:
        document = browser.document(item["id"])
        for side in ("baseline", "candidate"):
            descriptor = document["regressionSources"][side]
            require(descriptor["status"] == "available", "Regression source descriptor is unavailable")
            browser.document(descriptor["id"])
        for pair in document["regressionEvidence"]:
            for side in ("baseline", "candidate"):
                descriptor = pair[side]
                if descriptor["status"] == "not_recorded":
                    require(document["data"]["exitCode"] == 2 and side == "candidate",
                            "Unexpected unrecorded regression sample")
                    continue
                require(descriptor["status"] == "available", "Regression evidence descriptor is unavailable")
                browser.document(descriptor["evaluationId"])
                browser.document(descriptor["evidenceId"])
                browser.document(descriptor["assertionTrace"]["id"])
    regression_http = _http_check(regression / "inputs", regression, items[0]["id"])
    browser = ArtifactBrowser(package / "payload/inputs", package)
    items = browser.catalog()["items"]
    report, = [row for row in items if row["kind"] == "report"]
    document = browser.document(report["id"])
    links = [link for link in document["links"] if link["id"]]
    required = {f"{index} / {field}" for index in range(1, 5)
                for field in ("evaluationPath", "sourceEvidencePath")}
    require(required.issubset({link["label"] for link in links}),
            "Archive report lost one of its four evaluation or evidence references")
    for link in links:
        browser.document(link["id"])
    preview, = [row for row in items if row["kind"] == "experiment_assertion_preview"]
    evidence = browser.document(preview["id"])["sampleEvidence"]
    require(len(evidence) == 4 and all(row.get("assertionTrace") for row in evidence),
            "Archive preview lost its four trace references")
    for row in evidence:
        browser.document(row["id"])
        browser.document(row["assertionTrace"]["id"])
    return {"regressionComparisons": 3, "archiveSamples": 4, "regressionServer": regression_http,
            "archiveServer": _http_check(package / "payload/inputs", package, report["id"])}


def generate_delivery_check(output_dir=None):
    """Own a fresh output leaf; never move or overwrite any pre-existing run."""
    directory = Path(output_dir if output_dir is not None else ROOT / "runs/delivery-check" / str(uuid4()))
    directory.mkdir(parents=True, exist_ok=False)  # Check the original leaf, including dangling links.
    directory = directory.resolve()
    result = {"deliveryCheckFormatVersion": 1, "status": "running", "source": "synthetic",
              "modelCalled": False, "outputDirectory": str(directory), "stages": []}
    step = "generate-workflow"
    try:
        workflow_root, regression_root = directory / "workflow-source", directory / "regression-source"
        workflow = generate_workflow(workflow_root)
        original_report = load_json(workflow["reportPath"])
        require(workflow["sourceArchivesUnchanged"] and workflow["modelCalled"] is False,
                "Workflow did not preserve its synthetic source archives")
        result["stages"].append({"step": step, "status": "passed", "syntheticTasks": 6,
                                 "matrixPassed": 4, "strictRuleFlips": 1})
        step = "generate-regression"
        regression = generate_regression_demo(regression_root)
        codes = [row["actualExitCode"] for row in regression["scenarios"]]
        require(codes == [0, 1, 2] and regression["sourceArchivesUnchanged"]
                and regression["archiveFilesChecked"] == 128 and regression["modelCalled"] is False,
                "Regression examples did not retain their expected gates and 128 source hashes")
        result["stages"].append({"step": step, "status": "passed", "syntheticTasks": 7,
                                 "exitCodes": codes, "sourceFilesChecked": 128})
        step = "export-archive"
        source_before, regression_before = _bytes(workflow_root), _bytes(regression_root)
        package = directory / "export/package"
        preview = next(row["previewPath"] for row in workflow["scenarios"] if row["id"] == "rule-impact")
        manifest = export_archive(workflow["experimentPath"], workflow_root, package,
                                  artifacts=[workflow["reportPath"], preview])
        package_before = _bytes(package)
        require(_bytes(workflow_root) == source_before, "Archive export changed its source bytes")
        save_json(directory / "delivery-sha256.json", {"workflowSource": _hashes(source_before),
                  "regressionSource": _hashes(regression_before), "package": _hashes(package_before)})
        result["stages"].append({"step": step, "status": "passed", "payloadFiles": len(manifest["files"]),
                                 "manifestSha256": _hashes(package_before)[MANIFEST]})
        step = "move-source"
        retired = directory / "retired-source"
        _move_owned(directory, workflow_root, retired)
        require(_bytes(retired) == source_before and not Path(workflow["experimentPath"]).exists(),
                "Retired source differs or the original experiment remains available")
        result["stages"].append({"step": step, "status": "passed", "oldSourceUnavailable": True})
        step = "move-package"
        relocated = directory / "relocated/package"
        relocated.parent.mkdir()
        _move_owned(directory, package, relocated)
        require(_bytes(relocated) == package_before, "Package relocation changed its bytes")
        result["stages"].append({"step": step, "status": "passed", "packageDirectory": str(relocated)})
        step = "verify-archive"
        verification = verify_archive(relocated)
        require(verification["status"] == "verified" and verification["taskEvaluationPerformed"] is False,
                "Archive verification unexpectedly performed task evaluation")
        result["stages"].append({"step": step, **verification})
        step = "recheck-report"
        report = generate_report(relocated / MANIFEST, directory / "rechecked")
        require(report["verificationCounts"] == {"verified": 4}
                and all((row["outcome"], row["verification"], row["configurationMatch"], row["source"])
                        == ("passed", "verified", "matched", "synthetic") for row in report["samples"]),
                "Relocated report did not independently verify four synthetic passes")
        for key in ("summary", "planVerification", "verificationCounts", "groups"):
            require(report[key] == original_report[key], "Relocated report changed " + key)
        for old, new in zip(original_report["samples"], report["samples"], strict=True):
            for key in ("sampleId", "outcome", "changedFields", "diagnosticSummary", "assertionCauses"):
                require(old[key] == new[key], "Relocated sample changed " + key)
        require(_bytes(retired) == source_before and _bytes(relocated) == package_before,
                "Report recheck modified source or package bytes")
        result["stages"].append({"step": step, "status": "passed", "verifiedSamples": 4,
                                 "reportPath": str(Path(report["reportDirectory"]) / "report.json"),
                                 "summary": report["summary"]})
        step = "read-only-browser"
        browser_checks = _browse(regression_root, relocated)
        require(_bytes(retired) == source_before and _bytes(relocated) == package_before
                and _bytes(regression_root) == regression_before, "Browser checks modified source or package bytes")
        result["stages"].append({"step": step, "status": "passed", **browser_checks})
        result.update(status="completed", sourceBytesUnchanged=True, packageBytesUnchanged=True,
                      regressionSourceBytesUnchanged=True)
    except (Exception, KeyboardInterrupt) as error:
        result.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "error",
                      failedStep=step, error=f"{type(error).__name__}: {error}")
    save_json(directory / "delivery-result.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check fixed synthetic delivery examples; never calls a model")
    parser.add_argument("--output-dir", help="New output directory; existing paths are never overwritten")
    args = parser.parse_args(argv)
    try:
        result = generate_delivery_check(args.output_dir)
    except (Exception, KeyboardInterrupt) as error:
        result = {"deliveryCheckFormatVersion": 1, "status": "interrupted" if isinstance(error, KeyboardInterrupt) else "error",
                  "source": "synthetic", "modelCalled": False, "failedStep": "allocate-or-save-output",
                  "error": f"{type(error).__name__}: {error}"}
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return {"completed": 0, "interrupted": 130}.get(result["status"], 2)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
