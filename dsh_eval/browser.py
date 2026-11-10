"""Loopback-only, read-only viewer of saved evaluation artifacts. Never runs tasks."""
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import secrets
from urllib.parse import parse_qs, urlsplit

from .formats import parse_json, require, validate_evidence


ROOT = Path(__file__).resolve().parents[1]
WEB = Path(__file__).with_name("web")
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 128
MAX_CATALOG_ITEMS = 2000
TRACE_LINE_BYTES = 65536
BLOCKED = {"home", "workspace", "node_modules", "private-notes", "secrets", "credentials", "__pycache__"}
FORMATS = {"caseFormatVersion": ("case", (1, 2)), "batchFormatVersion": ("batch_manifest", (1,)),
           "experimentFormatVersion": ("experiment_manifest", (1,)), "batchResultFormatVersion": ("batch", (1,)),
           "experimentResultFormatVersion": ("experiment", (1,)), "comparisonReportFormatVersion": ("report", (1, 2, 3)),
           "assertionComparisonFormatVersion": ("assertion_comparison", (1,)),
           "experimentAssertionPreviewFormatVersion": ("experiment_assertion_preview", (1,)),
           "regressionComparisonFormatVersion": ("regression_comparison", (1,)),
           "assertionRuleMapFormatVersion": ("assertion_rule_map", (1,)),
           "workflowDemoFormatVersion": ("workflow_demo", (1,)),
           "archiveBundleFormatVersion": ("archive_bundle", (1,)),
           "experimentResumeResultFormatVersion": ("experiment_resume", (1, 2)),
           "batchResumeResultFormatVersion": ("batch_resume", (1,)),
           "evaluationFormatVersion": ("evaluation", (1, 2)), "evidenceFormatVersion": ("evidence", (1, 2)),
           "runtimeFormatVersion": ("runtime", (1,)), "formatVersion": ("recording", (1, 2)),
           "statusFormatVersion": ("recording", (1,))}
RESULT_NAMES = {"batch-result.json", "experiment-result.json", "report.json", "evaluation.json",
                "resume-result.json", "experiment-resume-result.json", "assertion-comparison.json",
                "experiment-assertion-preview.json", "workflow-index.json", "archive-manifest.json"}
TRACE_NAME = re.compile(r"[0-9a-f]{64}\.jsonl\Z")


def _same_json(left, right):
    return json.dumps(left, sort_keys=True, ensure_ascii=False) == json.dumps(right, sort_keys=True, ensure_ascii=False)


def _regression_key(row):
    require(isinstance(row, dict) and all(isinstance(row.get(key), str) and row[key]
                                        for key in ("caseEntryId", "configurationId", "sampleId", "caseId"))
            and type(row.get("repeatIndex")) is int and row["repeatIndex"] > 0,
            "Invalid source sample identity")
    return row["caseEntryId"], row["configurationId"], row["repeatIndex"]


def _case_component(value):
    return (isinstance(value, str) and bool(value) and value == value.strip() and ".." not in value
            and not any(char in value for char in "/\\:") and not any(ord(char) < 32 for char in value)
            and _allowed_parts((value,)))


def _allowed_parts(parts):
    return all(part not in ("", ".", "..") and not part.startswith(".") and part.casefold() not in BLOCKED
               for part in parts)


def _viewer_json(text):
    message = f"JSON nesting exceeds the viewer limit ({MAX_JSON_DEPTH} levels)"
    try:
        data = parse_json(text)
    except RecursionError as error:
        raise ValueError(message) from error
    pending = [(data, 1)]
    while pending:
        value, depth = pending.pop()
        if isinstance(value, (dict, list)):
            require(depth <= MAX_JSON_DEPTH, message)
            children = value.values() if isinstance(value, dict) else value
            pending.extend((child, depth + 1) for child in children if isinstance(child, (dict, list)))
    return data


def _kind(data):
    require(isinstance(data, dict), "Artifact must be a JSON object")
    for key, (kind, versions) in FORMATS.items():
        if key in data:
            require(type(data[key]) is int and data[key] in versions, f"Unsupported {key}")
            return kind
    raise ValueError("Not a supported evaluation artifact")


def _summary_sources(summary):
    counts = summary.get("sourceCounts") if isinstance(summary, dict) else None
    if not isinstance(counts, dict):
        return None
    return {source or "unknown" for source, count in counts.items() if type(count) is int and count > 0}


def _resume_sources(data, kind):
    combined = _summary_sources(data.get("combinedSummary"))
    if combined is not None:
        return sorted(combined)
    fresh = _summary_sources(data.get("newlyExecutedSummary"))
    sources = fresh if fresh is not None else {"unknown"}
    key = "reusedEntries" if kind == "batch_resume" else "samplePlan"
    rows = data.get(key)
    if rows is None:
        sources.add("unknown")
        return sorted(sources)
    require(isinstance(rows, list), f"Artifact {key} must be an array")
    for row in rows:
        if isinstance(row, dict) and (kind == "batch_resume" or row.get("disposition") == "reuse"):
            source = row.get("source")
            sources.add(source if isinstance(source, str) and source else "unknown")
    return sorted(sources)


class ArtifactBrowser:
    def __init__(self, cases_root=None, runs_root=None):
        configured = {"cases": Path(os.path.abspath(cases_root or ROOT / "fixtures/evaluation")),
                      "runs": Path(os.path.abspath(runs_root or ROOT / "runs"))}
        self.roots = {label: root.resolve() for label, root in configured.items()}
        # Only the explicitly configured spelling and its resolved root are trusted prefixes.
        self._root_prefixes = [(root, self.roots[label]) for label, root in configured.items()]
        self._root_prefixes.extend((root, root) for root in self.roots.values())
        self._archive = None
        self._archive_manifest = self.roots["runs"] / "archive-manifest.json"
        self._archive_files = {}
        if self._archive_manifest.is_symlink() or self._archive_manifest.exists():
            from .archive_bundle import load_archive
            manifest, self._archive = load_archive(self._archive_manifest)
            content = self._archive_manifest.read_bytes()
            require(json.dumps(parse_json(content.decode("utf-8")), sort_keys=True) == json.dumps(manifest, sort_keys=True),
                    "Archive manifest changed during loading")
            self._archive_manifest_sha256 = hashlib.sha256(content).hexdigest()
            self._archive_manifest_size = len(content)
            self._archive_files = {row["path"]: row for row in manifest["files"]}

    def _reference_target(self, value, directory):
        raw = value.replace("\\", "/")
        if self._archive is not None and self._archive.recognizes(raw):
            try:
                return self._archive.physical(raw)
            except (OSError, ValueError, RuntimeError):
                return None
        path = Path(raw)
        if self._archive is not None and PureWindowsPath(raw).is_absolute() and not path.is_absolute():
            return None
        target = path if path.is_absolute() else directory / path
        if self._archive is not None and (directory.is_relative_to(self._archive.payload_root)
                                          or directory == self.roots["runs"]):
            target = Path(os.path.abspath(target))
            if not self._archive.recognizes(target):
                return None
            try:
                return self._archive.physical(target)
            except (OSError, ValueError, RuntimeError):
                return None
        return target

    def _verify_archive_manifest(self):
        require(not self._archive_manifest.is_symlink() and not self._archive_manifest.is_junction(),
                "Archive manifest became a link")
        content = self._archive_manifest.read_bytes()
        require(len(content) == self._archive_manifest_size
                and hashlib.sha256(content).hexdigest() == self._archive_manifest_sha256,
                "Archive manifest changed after loading")

    def _verify_archive_digest(self, path, size, digest):
        if self._archive is None or not path.is_relative_to(self.roots["runs"]):
            return
        self._verify_archive_manifest()
        if path == self._archive_manifest:
            require(size == self._archive_manifest_size and digest == self._archive_manifest_sha256,
                    "Archive manifest changed during reading")
            return
        expected = self._archive_files.get(path.relative_to(self.roots["runs"]).as_posix())
        require(expected is not None, "Artifact is not a listed archive member")
        require(size == expected["size"], "Archive member size changed during reading")
        require(digest == expected["sha256"], "Archive member digest changed during reading")

    def _verify_archive_content(self, path, content):
        if self._archive is not None and path.is_relative_to(self.roots["runs"]):
            self._verify_archive_digest(path, len(content), hashlib.sha256(content).hexdigest())

    def _verify_archive_file(self, path):
        if self._archive is None or not path.is_relative_to(self.roots["runs"]):
            return
        self._verify_archive_manifest()
        if path == self._archive_manifest:
            return
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
                size += len(chunk)
        self._verify_archive_digest(path, size, digest.hexdigest())

    def _resolve_reference(self, target):
        if target is None:
            return None
        if self._archive is not None:
            if Path(target) == self._archive_manifest:
                if self._archive_manifest.is_symlink() or self._archive_manifest.is_junction():
                    return None
                target = self._archive_manifest
            elif self._archive.recognizes(target):
                try:
                    target = self._archive.physical(target)
                except (OSError, ValueError, RuntimeError):
                    return None
            elif PureWindowsPath(str(target)).is_absolute() and not Path(target).is_absolute():
                return None
            else:
                target = Path(os.path.abspath(target))
                for prefix, root in self._root_prefixes:
                    if target.is_relative_to(prefix):
                        target = root / target.relative_to(prefix)
                        break
                if self._archive.recognizes(target):
                    try:
                        target = self._archive.physical(target)
                    except (OSError, ValueError, RuntimeError):
                        return None
                elif target.is_relative_to(self.roots["runs"]):
                    if target != self._archive_manifest or target.is_symlink() or target.is_junction():
                        return None
        # abspath normalizes '..' without following links or querying the target's filesystem.
        target = Path(os.path.abspath(target))
        roots = [root for prefix, root in self._root_prefixes
                 if target.is_relative_to(prefix) and _allowed_parts(target.relative_to(prefix).parts)]
        if not roots:
            return None
        try:
            resolved = target.resolve()
        except (OSError, ValueError, RuntimeError):
            return None
        if self._archive is not None and target == self._archive_manifest and resolved != self._archive_manifest:
            return None
        return resolved if any(resolved.is_relative_to(root) and _allowed_parts(resolved.relative_to(root).parts)
                               for root in roots) else None

    def path(self, identifier):
        label, separator, value = identifier.partition(":")
        parts = value.split("/")
        require(separator and label in self.roots and value and "\\" not in value and ":" not in value
                and not PurePosixPath(value).is_absolute()
                and _allowed_parts(parts), "Artifact path is not allowed")
        root = self.roots[label]
        path = self._resolve_reference(root / value)
        require(path is not None and path.is_relative_to(root) and path.is_file(), "Artifact is missing or outside its configured root")
        require(_allowed_parts(path.relative_to(root).parts), "Resolved artifact path is not allowed")
        require(path.suffix == ".json" or TRACE_NAME.fullmatch(path.name) or path.name == "report.md",
                "Unsupported artifact file")
        self._verify_archive_file(path)
        return path

    def reference(self, target):
        target = self._resolve_reference(target)
        if target is None:
            return None
        for label, root in self.roots.items():
            if target.is_relative_to(root):
                identifier = label + ":" + target.relative_to(root).as_posix()
                try:
                    self.path(identifier)
                    return identifier
                except (OSError, ValueError):
                    pass
        return None

    def _json(self, path):
        with path.open("rb") as stream:
            content = stream.read(MAX_DOCUMENT_BYTES + 1)
        require(len(content) <= MAX_DOCUMENT_BYTES, "JSON exceeds the 8 MiB viewer limit")
        self._verify_archive_content(path, content)
        data = _viewer_json(content.decode("utf-8"))
        return _kind(data), data

    def catalog(self):
        items, warnings = [], []
        truncated = False
        for label, root in self.roots.items():
            if not root.is_dir():
                warnings.append(f"{label}: directory does not exist")
                continue
            def walk_error(error):
                warnings.append(str(error))
            inventory = ["archive-manifest.json", *sorted(self._archive_files)] if label == "runs" and self._archive is not None else None
            entries = ((root / Path(name).parent, [], [Path(name).name]) for name in inventory) if inventory is not None else os.walk(root, followlinks=False, onerror=walk_error)
            for directory, directories, files in entries:
                directories[:] = sorted(name for name in directories if not name.startswith(".")
                                         and name.casefold() not in BLOCKED
                                         and not (Path(directory) / name).is_symlink()
                                         and not (Path(directory) / name).is_junction()
                                         and (Path(directory) / name).resolve().is_relative_to(root))
                for name in sorted(files):
                    if name == "archive-manifest.json" and (label != "runs" or self._archive is None
                                                               or Path(directory) / name != self._archive_manifest):
                        continue
                    standard = name.endswith(".case.json") if label == "cases" else name in RESULT_NAMES
                    if not standard and not (label == "runs" and name.endswith(".json")):
                        continue
                    identifier = self.reference(Path(directory) / name)
                    if identifier is None:
                        if inventory is not None:
                            warnings.append(f"runs:{(Path(directory) / name).relative_to(root).as_posix()}: listed artifact is unavailable or changed")
                        continue
                    if len(items) >= MAX_CATALOG_ITEMS:
                        truncated = True
                        break
                    item = {"id": identifier, "path": identifier.split(":", 1)[1], "kind": "unknown"}
                    try:
                        candidate_path = self.path(identifier)
                        if not standard:
                            # Discover arbitrary --output names without adding unrelated raw JSON to the catalog.
                            with candidate_path.open("rb") as stream:
                                content = stream.read(MAX_DOCUMENT_BYTES + 1)
                            if len(content) > MAX_DOCUMENT_BYTES or b'"regressionComparisonFormatVersion"' not in content:
                                continue
                            self._verify_archive_content(candidate_path, content)
                            data = _viewer_json(content.decode("utf-8"))
                            if not isinstance(data, dict) or "regressionComparisonFormatVersion" not in data:
                                continue
                            kind = _kind(data)
                            if kind != "regression_comparison":
                                continue
                        else:
                            kind, data = self._json(candidate_path)
                        item.update(kind=kind, title=data.get("workflowName") or data.get("experimentName") or data.get("batchName")
                                    or data.get("caseId") or data.get("reportId") or data.get("resumeId") or data.get("workflowId") or data.get("experimentId") or data.get("archiveId") or name,
                                    outcome=data.get("outcome"), status=data.get("status"), source=data.get("source"),
                                    time=data.get("generatedAt") or data.get("finishedAt") or data.get("evaluatedAt") or data.get("startedAt"))
                        summary = data.get("summary")
                        item["outcomes"] = summary.get("outcomes") if isinstance(summary, dict) else None
                        if kind == "evaluation" and isinstance(data.get("execution"), dict):
                            item["status"] = data["execution"].get("status")
                        if kind == "assertion_comparison":
                            for key in ("baseline", "candidate"):
                                side = data.get(key)
                                item[key + "Outcome"] = side.get("outcome") if isinstance(side, dict) else None
                            item["outcome"] = item["candidateOutcome"]
                        rows = data.get("samples") or data.get("entries") or []
                        require(isinstance(rows, list), "Artifact samples/entries must be an array")
                        if kind == "experiment_assertion_preview":
                            item["previewSummary"] = summary
                            item["outcomes"] = {outcome: sum(row.get("candidateOutcome") == outcome for row in rows if isinstance(row, dict))
                                                for outcome in ("passed", "failed", "unevaluable")}
                        if kind == "regression_comparison":
                            item["regressionCounts"] = data.get("counts")
                        item["sources"] = sorted({row["source"] if isinstance(row.get("source"), str) and row["source"] else "unknown"
                                                  for row in rows if isinstance(row, dict)})
                        if kind in ("batch_resume", "experiment_resume"):
                            item["sources"] = _resume_sources(data, kind)
                        elif kind == "regression_comparison":
                            item["sources"] = sorted({side.get("source") or "unknown" for row in rows if isinstance(row, dict)
                                                      for key in ("baseline", "candidate")
                                                      if isinstance(side := row.get(key), dict)
                                                      and (side.get("source") is None or isinstance(side.get("source"), str))})
                        elif isinstance(item["source"], str) and item["source"]:
                            item["sources"] = [item["source"]]
                    except (OSError, ValueError) as error:
                        item["error"] = str(error)
                    items.append(item)
                if truncated:
                    break
            if truncated:
                break
        return {"browserFormatVersion": 1, "readAt": datetime.now(timezone.utc).isoformat(),
                "items": items, "warnings": warnings, "truncated": truncated}

    def _links(self, data, directory):
        links = []
        def add(label, value, trace_directory=False):
            if not isinstance(value, str) or not value:
                return
            target = self._reference_target(value, directory)
            if trace_directory:
                resolved = self._resolve_reference(target)
                if resolved is None:
                    links.append({"label": label, "id": None, "path": value})
                    return
                if resolved.is_dir():
                    for child in sorted(resolved.iterdir()):
                        if child.name == "run.json" or TRACE_NAME.fullmatch(child.name) or re.fullmatch(r"[0-9a-f]{64}\.status\.json", child.name):
                            add(label + " / " + child.name, str(child))
                    return
            links.append({"label": label, "id": self.reference(target), "path": value})
        path_keys = ("casePath", "evidencePath", "evaluationPath", "runtimeReport", "manifestPath", "batchResultPath",
                     "sourceExperimentResult", "sourceEvidencePath", "sourceResumeResult", "sourceBatchResult",
                     "batchResumeResultPath", "batchResumeResult")
        def collect(value, prefix=""):
            if not isinstance(value, dict):
                return
            for key in path_keys:
                add(prefix + key, value.get(key))
            add(prefix + "runDir", value.get("runDir"), True)
        collect(data)
        if "archiveBundleFormatVersion" in data:
            add("entryPath", data.get("entryPath"))
            for index, row in enumerate(data.get("artifacts", []) if isinstance(data.get("artifacts"), list) else [], 1):
                if isinstance(row, dict):
                    add(f"归档内容 {index} / path", row.get("path"))
        if "experimentAssertionPreviewFormatVersion" in data or "workflowDemoFormatVersion" in data:
            add("experimentPath", data.get("experimentPath"))
        if "experimentAssertionPreviewFormatVersion" in data:
            add("ruleMapPath", data.get("ruleMapPath"))
        if "workflowDemoFormatVersion" in data:
            add("reportPath", data.get("reportPath"))
            for index, row in enumerate(data.get("scenarios", []) if isinstance(data.get("scenarios"), list) else [], 1):
                if isinstance(row, dict):
                    add(f"场景 {index} / evaluationPath", row.get("evaluationPath"))
                    add(f"场景 {index} / previewPath", row.get("previewPath"))
        binding = data.get("batchBinding")
        result_path = data.get("batchResultPath")
        if (result_path is None or result_path == "") and isinstance(binding, dict):
            add("batchBinding / resultPath", binding.get("resultPath"))
        collect(data.get("association"), "association / ")
        collect(data.get("resumeVerification"), "resumeVerification / ")
        if "assertionComparisonFormatVersion" in data:
            collect(data.get("baseline"), "baseline / ")
            collect(data.get("candidate"), "candidate / ")
        for index, value in enumerate(data.get("batchResultPaths", []) if isinstance(data.get("batchResultPaths"), list) else [], 1):
            add(f"批次 {index} / batchResultPath", value)
        for index, row in enumerate(data.get("resumeChain", []) if isinstance(data.get("resumeChain"), list) else [], 1):
            if isinstance(row, dict):
                add(f"续跑 {index} / resultPath", row.get("resultPath"))
        for key in ("entries", "samples", "cases"):
            rows = data.get(key)
            if isinstance(rows, list):
                for index, row in enumerate(rows, 1):
                    if "experimentAssertionPreviewFormatVersion" not in data:
                        collect(row, f"{index} / ")
        if "comparisonReportFormatVersion" in data:
            add("Markdown", "report.md")
        return links

    def _regression_target(self, value, directory, within=None):
        if not isinstance(value, str) or not value:
            return None
        raw = value.replace("\\", "/")
        if self._archive is None and PureWindowsPath(raw).is_absolute() and not Path(raw).is_absolute():
            return None
        target = self._resolve_reference(self._reference_target(value, directory))
        return target if target is not None and (within is None or target.is_relative_to(within)) else None

    def _regression_json(self, value, directory, cache, *, kind=None, within=None):
        target = self._regression_target(value, directory, within)
        require(target is not None, "Reference is missing or outside the configured source directory")
        identifier = self.reference(target)
        require(identifier is not None, "Referenced source file is unavailable")
        path = self.path(identifier)
        if path not in cache:
            cache[path] = self._json(path)
        actual_kind, data = cache[path]
        require(kind is None or actual_kind == kind, "Referenced source has an unexpected artifact kind")
        return path, identifier, data

    def _regression_batch(self, value, directory, cache, *, expected_id=None, within=None):
        path, identifier, data = self._regression_json(value, directory, cache, kind="batch", within=within)
        require(_case_component(data.get("batchId"))
                and (expected_id is None or data["batchId"] == expected_id), "Source batch identity mismatch")
        require(isinstance(data.get("entries"), list), "Source batch entries are unavailable")
        rows = {}
        for row in data["entries"]:
            require(isinstance(row, dict) and isinstance(row.get("entryId"), str) and row["entryId"]
                    and row["entryId"] not in rows, "Duplicate or invalid source batch sample")
            rows[row["entryId"]] = row
        return path, data, rows

    def _regression_context(self, value, directory, cache, visited=None, resume_ids=None, depth=0):
        require(depth <= 32, "Source continuation chain exceeds the viewer limit")
        path, identifier, data = self._regression_json(value, directory, cache)
        visited, resume_ids = set(visited or ()), set(resume_ids or ())
        require(path not in visited, "Source continuation chain contains a cycle")
        visited.add(path)
        kind = cache[path][0]
        if kind == "experiment":
            require(isinstance(data.get("experimentId"), str) and data["experimentId"]
                    and isinstance(data.get("samples"), list)
                    and data.get("status") in (("running", "completed", "stopped", "error", "interrupted") if depth
                                              else ("completed", "stopped", "error", "interrupted")), "Invalid source experiment")
            _, _, manifest = self._regression_json(data.get("manifestPath"), path.parent, cache,
                                                   kind="experiment_manifest", within=path.parent)
            configurations = manifest.get("configurations")
            require(isinstance(configurations, list) and configurations and _same_json(configurations, data.get("configurations")),
                    "Source experiment configurations do not match its manifest")
            config_ids = [row.get("configurationId") for row in configurations if isinstance(row, dict)]
            require(len(config_ids) == len(configurations) and all(isinstance(item, str) and item for item in config_ids)
                    and len(set(config_ids)) == len(config_ids), "Duplicate or invalid source configurations")
            cases, repetitions = manifest.get("cases"), manifest.get("repetitions")
            require(isinstance(cases, list) and cases and type(repetitions) is int and repetitions > 0,
                    "Source experiment matrix is unavailable")
            case_ids = [row.get("entryId") for row in cases if isinstance(row, dict)]
            require(len(case_ids) == len(cases) and all(isinstance(item, str) and item for item in case_ids)
                    and len(set(case_ids)) == len(case_ids), "Duplicate or invalid source case entries")
            frozen_cases = {}
            for item in cases:
                _, _, frozen = self._regression_json(item.get("casePath"), path.parent, cache,
                                                     kind="case", within=path.parent)
                require(isinstance(frozen.get("caseId"), str) and frozen["caseId"], "Frozen source case identity is unavailable")
                frozen_cases[item["entryId"]] = frozen
            require(len(data["samples"]) == len(case_ids) * len(config_ids) * repetitions,
                    "Source experiment matrix count mismatch")
            binding = data.get("batchBinding")
            batch_value = data.get("batchResultPath") or (binding.get("resultPath") if isinstance(binding, dict) else None)
            batch_path, batch, batch_rows = self._regression_batch(batch_value, path.parent, cache,
                                                                  expected_id=data.get("batchId") or (binding.get("batchId") if isinstance(binding, dict) else None),
                                                                  within=path.parent)
            require(batch_path == path.parent / "batches" / batch["batchId"] / "batch-result.json",
                    "Source experiment batch is not in its canonical directory")
            require(len(batch_rows) == len(data["samples"]), "Source experiment/batch matrix count mismatch")
            rows, sample_ids = {}, set()
            seen = {field: set() for field in ("caseRunId", "runId", "sessionId")}
            for item in data["samples"]:
                key = _regression_key(item)
                require(key not in rows and item["sampleId"] not in sample_ids
                        and key[0] in case_ids and key[1] in config_ids and key[2] <= repetitions,
                        "Source experiment sample is duplicated or outside its matrix")
                sample_ids.add(item["sampleId"])
                require(item["caseId"] == frozen_cases[key[0]]["caseId"], "Source sample/frozen case identity mismatch")
                row = batch_rows.get(item["sampleId"])
                require(isinstance(row, dict) and all(_same_json(row.get(name), item.get(name)) for name in
                        ("caseId", "requestedConfiguration", "status", "caseRunId", "runId", "sessionId")
                        if data.get("status") != "running" or name in item),
                        "Source experiment/batch sample identity mismatch")
                for field, values in seen.items():
                    identity = row.get(field)
                    require(identity is None or isinstance(identity, str) and identity and identity not in values,
                            "Duplicate or invalid source execution identity")
                    if identity is not None:
                        values.add(identity)
                selected = next(config for config in configurations if config["configurationId"] == key[1])
                require(_same_json(row.get("requestedConfiguration"), selected.get("configRef")),
                        "Source sample requested configuration mismatch")
                for field in ("casePath", "caseDirectory", "evidencePath", "evaluationPath", "runtimeReport", "runDir"):
                    if data.get("status") == "running" and field not in item:
                        continue
                    left, right = item.get(field), row.get(field)
                    require((left is None) == (right is None), "Source experiment/batch artifact mismatch")
                    if left is not None:
                        target = self._regression_target(left, path.parent, batch_path.parent)
                        require(target is not None and target == self._regression_target(right, batch_path.parent, batch_path.parent),
                                "Source experiment/batch artifact path mismatch")
                rows[key] = {"row": {**row, **{name: item[name] for name in
                            ("sampleId", "caseEntryId", "configurationId", "repeatIndex", "caseId")},
                                       "requestedConfiguration": selected["configRef"]},
                             "base": batch_path.parent, "batchPath": batch_path, "batchId": batch["batchId"], "recovered": False}
            return {"id": identifier, "path": path, "data": data, "originalPath": path,
                    "experimentId": data["experimentId"], "configurations": configurations, "rows": rows,
                    "cases": frozen_cases,
                    "latestBatch": batch_path, "latestBatchId": batch["batchId"]}
        require(kind == "experiment_resume" and _case_component(data.get("resumeId"))
                and data["resumeId"] not in resume_ids
                and data.get("status") in (("running", "completed", "stopped", "error", "interrupted") if depth
                                          else ("completed", "stopped", "error", "interrupted")),
                "Invalid or nonterminal source continuation")
        resume_ids.add(data["resumeId"])
        version = data["experimentResumeResultFormatVersion"]
        previous_value = data.get("sourceResumeResult") if version == 2 else data.get("sourceExperimentResult")
        previous = self._regression_context(previous_value, path.parent, cache, visited, resume_ids, depth + 1)
        require((version == 1 and cache[previous["path"]][0] == "experiment")
                or (version == 2 and cache[previous["path"]][0] == "experiment_resume"
                    and data.get("sourceResumeId") == previous["data"].get("resumeId")),
                "Source continuation ancestry identity mismatch")
        require(data.get("sourceExperimentId") == previous["experimentId"]
                and self._regression_target(data.get("sourceExperimentResult"), path.parent) == previous["originalPath"]
                and self._regression_target(data.get("sourceBatchResult"), path.parent) == previous["latestBatch"]
                and data.get("sourceBatchId") == previous["latestBatchId"], "Source continuation origin mismatch")
        child_path, _, child = self._regression_json(data.get("batchResumeResultPath"), path.parent, cache,
                                                    kind="batch_resume", within=path.parent)
        require(_case_component(child.get("resumeId"))
                and child_path == path.parent / "continuations" / child["resumeId"] / "resume-result.json"
                and self._regression_target(child.get("sourceBatchResult"), child_path.parent) == previous["latestBatch"]
                and child.get("sourceBatchId") == previous["latestBatchId"]
                and (data["status"] == "running" or child.get("status") == data["status"]), "Source continuation child mismatch")
        binding = child.get("batchBinding")
        batch_value = child.get("batchResultPath") or (binding.get("resultPath") if isinstance(binding, dict) else None)
        batch_path, batch, entries = self._regression_batch(batch_value, child_path.parent, cache,
                                                          expected_id=binding.get("batchId") if isinstance(binding, dict) else None,
                                                          within=child_path.parent)
        require(batch_path == child_path.parent / "batches" / batch["batchId"] / "batch-result.json",
                "Continuation batch is not in its canonical directory")
        require(child.get("status") == "running" or batch.get("status") == child.get("status"),
                "Continuation child/batch scheduling state mismatch")
        require(isinstance(data.get("samplePlan"), list) and len(data["samplePlan"]) == len(previous["rows"]),
                "Continuation sample matrix is unavailable")
        rows, sample_ids, pending_ids = {}, set(), set()
        for item in data["samplePlan"]:
            key = _regression_key(item)
            prior = previous["rows"].get(key)
            require(prior is not None and key not in rows and item["sampleId"] not in sample_ids
                    and all(_same_json(item.get(name), prior["row"].get(name)) for name in
                            ("sampleId", "caseId", "requestedConfiguration")), "Continuation sample identity mismatch")
            sample_ids.add(item["sampleId"])
            if item.get("disposition") == "pending":
                row = entries.get(item["sampleId"])
                require(isinstance(row, dict) and row.get("caseId") == item["caseId"]
                        and _same_json(row.get("requestedConfiguration"), item["requestedConfiguration"]),
                        "Continuation new batch sample mismatch")
                pending_ids.add(item["sampleId"])
                current = {"row": {**row, **{name: item[name] for name in
                           ("sampleId", "caseEntryId", "configurationId", "repeatIndex", "caseId", "requestedConfiguration")}},
                           "base": batch_path.parent, "batchPath": batch_path, "batchId": batch["batchId"], "recovered": False}
            else:
                require(item.get("disposition") == "reuse" and item.get("caseRunId") == prior["row"].get("caseRunId"),
                        "Continuation reused sample mismatch")
                if version == 2:
                    require(self._regression_target(item.get("sourceBatchResult"), path.parent) == prior["batchPath"]
                            and item.get("sourceBatchId") == prior["batchId"], "Continuation reuse batch mismatch")
                current = {**prior, "row": dict(prior["row"])}
                if prior["row"].get("status") == "running":
                    require(item.get("recoveredCheckpoint") is True and item.get("verification") == "verified",
                            "Continuation checkpoint is not explicitly recovered")
                    current["row"].update(status="finished", source=item.get("source"))
                    current["recovered"] = True
            rows[key] = current
        require(pending_ids == set(entries), "Continuation batch has unrelated samples")
        for field in ("caseRunId", "runId", "sessionId"):
            identities = [item["row"][field] for item in rows.values() if item["row"].get(field) is not None]
            require(all(isinstance(item, str) and item for item in identities) and len(set(identities)) == len(identities),
                    "Duplicate or invalid continuation execution identity")
        return {**previous, "id": identifier, "path": path, "data": data, "rows": rows,
                "latestBatch": batch_path, "latestBatchId": batch["batchId"]}

    def _regression_side_evidence(self, row, pair, context, directory, cache):
        if row is None:
            return {"status": "missing_side", "reasonCode": "missing_side", "reason": "该侧没有对应的计划样本。"}
        if not isinstance(row, dict):
            return {"status": "unavailable", "reasonCode": "invalid_metadata", "reason": "该侧样本元数据不完整。"}
        if row.get("status") == "skipped":
            return {"status": "not_recorded", "reasonCode": "not_recorded", "reason": "该侧样本未执行，没有录制证据。"}
        try:
            require(context is not None, "来源归档缺失、越界或不完整。")
            key = _regression_key(row)
            require(isinstance(pair, dict) and type(pair.get("repeatIndex")) is int
                    and key[0] == pair.get("caseEntryId") and key[2] == pair["repeatIndex"]
                    and key[1] == context["selectedConfiguration"], "比较行与来源配对身份不一致。")
            selected = context["rows"].get(key)
            require(selected is not None, "来源没有唯一对应的样本。")
            source = selected["row"]
            require(row.get("status") == source.get("status") == "finished" and row.get("verification") == "verified"
                    and row.get("source") == source.get("source")
                    and all(isinstance(row.get(field), str) and row[field] for field in
                            ("sampleId", "caseId", "caseRunId", "runId", "sessionId"))
                    and all(_same_json(row.get(field), source.get(field)) for field in
                            ("sampleId", "caseId", "caseRunId", "requestedConfiguration")), "比较与来源样本身份不一致或未经复验。")
            for field in ("runId", "sessionId"):
                require(selected["recovered"] and source.get(field) is None or source.get(field) == row[field],
                        "比较与来源运行身份不一致。")
            if "sourceBatchResult" in row or "sourceBatchId" in row:
                require(self._regression_target(row.get("sourceBatchResult"), directory) == selected["batchPath"]
                        and row.get("sourceBatchId") == selected["batchId"], "比较与来源批次不一致。")
            require(_case_component(source.get("caseRunId")), "来源执行目录标识无效。")
            case_directory = selected["base"] / "cases" / source["caseRunId"]
            require(self._regression_target(source.get("caseDirectory"), selected["base"], selected["base"]) == case_directory,
                    "来源执行目录不是规范路径。")
            evidence_path = case_directory / "evidence.json"
            source_evidence = source.get("evidencePath")
            require((selected["recovered"] and source_evidence is None
                     or self._regression_target(source_evidence, selected["base"], case_directory) == evidence_path)
                    and self._regression_target(row.get("sourceEvidencePath"), directory, case_directory) == evidence_path,
                    "比较证据路径与来源规范位置不一致。")
            _, evidence_id, evidence = self._regression_json(str(evidence_path), case_directory, cache, kind="evidence", within=case_directory)
            expected_case = {**context["cases"][key[0]], "configRef": row.get("requestedConfiguration")}
            validate_evidence(evidence, expected_case)
            require(all(evidence.get(field) == row[field] for field in ("caseId", "caseRunId", "runId", "sessionId"))
                    and evidence.get("batchId") == selected["batchId"] and evidence.get("source") == row.get("source"),
                    "证据身份与来源运行不一致。")
            run_directory = self._regression_target(evidence.get("runDir"), case_directory, case_directory)
            expected_run = self._regression_target(source.get("runDir"), selected["base"], case_directory)
            require(_case_component(row["runId"]) and run_directory == case_directory / "traces" / row["runId"]
                    and (selected["recovered"] and source.get("runDir") is None or expected_run == run_directory),
                    "证据轨迹目录与来源运行不一致。")
            manifest_path, _, recording = self._regression_json(str(run_directory / "run.json"), run_directory, cache,
                                                               kind="recording", within=run_directory)
            require(manifest_path == run_directory / "run.json" and recording.get("runId") == row["runId"],
                    "录制目录标识与来源运行不一致。")
            if recording.get("formatVersion") == 2:
                sessions = recording.get("sessions")
                require(isinstance(sessions, list), "录制会话清单缺失。")
                selected_sessions = [item for item in sessions if isinstance(item, dict) and item.get("sessionId") == row["sessionId"]]
                name = hashlib.sha256(row["sessionId"].encode("utf-8")).hexdigest()
                require(len(selected_sessions) == 1 and selected_sessions[0].get("traceFile") == name + ".jsonl"
                        and selected_sessions[0].get("statusFile") == name + ".status.json", "录制会话清单与来源会话不一致。")
            if run_directory.is_dir():
                for child in run_directory.iterdir():
                    if child.name == "run.json" or TRACE_NAME.fullmatch(child.name) or re.fullmatch(r"[0-9a-f]{64}\.status\.json", child.name):
                        require(self._regression_target(str(child), run_directory, run_directory) == child,
                                "录制成员不在本次运行的规范位置。")
            runtime_path = case_directory / "runtime.json"
            for saved_path, base in ((evidence.get("runtimeReport"), case_directory),
                                     (source.get("runtimeReport"), selected["base"])):
                require(saved_path is None or self._regression_target(saved_path, base, case_directory) == runtime_path,
                        "运行报告不在本次执行的规范位置。")
            case_path, _, case = self._regression_json(str(case_directory / "case.json"), case_directory, cache, kind="case", within=case_directory)
            require(case_path == case_directory / "case.json" and _same_json(case, expected_case),
                    "保存用例与来源样本不一致。")
            result = {"status": "available", "evidenceId": evidence_id}
            unavailable = []
            evaluation_path = case_directory / "evaluation.json"
            try:
                source_evaluation = source.get("evaluationPath")
                require(selected["recovered"] and source_evaluation is None
                        or self._regression_target(source_evaluation, selected["base"], case_directory) == evaluation_path,
                        "保存评测位置不规范。")
                _, evaluation_id, evaluation = self._regression_json(str(evaluation_path), case_directory, cache,
                                                                     kind="evaluation", within=case_directory)
                association = evaluation.get("association")
                navigation = {"casePath", "evidencePath", "evaluationPath", "runtimeReport", "manifestPath", "batchResultPath",
                              "sourceExperimentResult", "sourceEvidencePath", "sourceResumeResult", "sourceBatchResult",
                              "batchResumeResultPath", "batchResumeResult", "runDir", "batchBinding", "resumeVerification",
                              "batchResultPaths", "resumeChain", "entries", "samples", "cases"}
                require(isinstance(association, dict) and evaluation.get("caseRunId") == row["caseRunId"]
                        and evaluation.get("caseId") == row["caseId"]
                        and not navigation.intersection(evaluation)
                        and set(association).issubset({"runId", "sessionId", "runDir", "casePath", "evidencePath", "runtimeReport"})
                        and all(association.get(field) == row[field] for field in ("runId", "sessionId"))
                        and self._regression_target(association.get("evidencePath"), case_directory, case_directory) == evidence_path
                        and self._regression_target(association.get("casePath"), case_directory, case_directory) == case_directory / "case.json"
                        and self._regression_target(association.get("runDir"), case_directory, case_directory) == run_directory
                        and ("runtimeReport" not in association or self._regression_target(association["runtimeReport"], case_directory, case_directory) == runtime_path),
                        "保存评测身份与证据不一致。")
                result["evaluationId"] = evaluation_id
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                unavailable.append("保存评测缺失或关联不一致。")
            trace_path = run_directory / (hashlib.sha256(row["sessionId"].encode("utf-8")).hexdigest() + ".jsonl")
            if self._regression_target(str(trace_path), run_directory, run_directory) == trace_path:
                trace = self.reference(trace_path)
                if trace:
                    result["assertionTrace"] = {"id": trace, "runId": row["runId"], "sessionId": row["sessionId"]}
            if "assertionTrace" not in result:
                unavailable.append("原始轨迹缺失或关联不一致。")
            if unavailable:
                result.update(reasonCode="partial_evidence", reason=" ".join(unavailable))
            return result
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            return {"status": "unavailable", "reasonCode": "evidence_unavailable", "reason": str(error)}

    def _regression_evidence(self, data, directory):
        cache, contexts, sources = {}, {}, {}
        if data.get("status") != "compared":
            return ({side: {"status": "unavailable", "reasonCode": "comparison_unavailable", "reason": "没有已完成的保存比较。"}
                     for side in ("baseline", "candidate")}, [])
        for side in ("baseline", "candidate"):
            try:
                value = data.get(side)
                require(isinstance(value, dict), "未保存该侧来源元数据。")
                context = self._regression_context(value.get("sourceResult"), directory, cache)
                require(value.get("experimentId") == context["experimentId"], "来源实验ID与比较不一致。")
                configuration = value.get("configuration")
                require(isinstance(configuration, dict) and sum(_same_json(configuration, item) for item in context["configurations"]) == 1,
                        "比较配置与来源实验不一致。")
                context["selectedConfiguration"] = configuration["configurationId"]
                contexts[side] = context
                sources[side] = {"status": "available", "id": context["id"]}
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                contexts[side] = None
                sources[side] = {"status": "unavailable", "reasonCode": "source_unavailable", "reason": str(error)}
        pairs = data.get("samples")
        pairs = pairs if isinstance(pairs, list) else []
        keys = [(row.get("caseEntryId"), row["repeatIndex"]) for row in pairs
                if isinstance(row, dict) and isinstance(row.get("caseEntryId"), str) and type(row.get("repeatIndex")) is int]
        observed, repeated = set(), set()
        for key in keys:
            if key in observed:
                repeated.add(key)
            observed.add(key)
        evidence = []
        for index, pair in enumerate(pairs, 1):
            key = ((pair.get("caseEntryId"), pair.get("repeatIndex")) if isinstance(pair, dict)
                   and isinstance(pair.get("caseEntryId"), str) and type(pair.get("repeatIndex")) is int else None)
            sides = {side: ({"status": "unavailable", "reasonCode": "invalid_metadata", "reason": "比较配对键重复，无法唯一定位。"}
                            if key in repeated else self._regression_side_evidence(pair.get(side) if isinstance(pair, dict) else {},
                                                                                  pair, contexts[side], directory, cache))
                     for side in ("baseline", "candidate")}
            evidence.append({"index": index, **sides})
        return sources, evidence

    def _preview_evidence(self, data, directory):
        """Offer only source evidence whose saved sample identity still matches."""
        rows = data.get("samples")
        if not isinstance(rows, list):
            return []
        links = []
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict) or not isinstance(row.get("evidencePath"), str) or not row["evidencePath"]:
                continue
            identifier = self.reference(self._reference_target(row["evidencePath"], directory))
            if identifier is None:
                continue
            try:
                kind, evidence = self._json(self.path(identifier))
                if kind != "evidence" or any(not isinstance(row.get(key), str) or not row[key]
                                             or evidence.get(key) != row[key]
                                             for key in ("caseRunId", "runId", "sessionId")):
                    continue
                link = {"index": index, "id": identifier}
                trace = self._comparison_trace(row, directory)
                if trace:
                    link["assertionTrace"] = trace
                links.append(link)
            except (OSError, ValueError):
                continue
        return links

    def _comparison_trace(self, data, directory):
        value = data.get("evidencePath")
        if not isinstance(value, str) or not value:
            return None
        identifier = self.reference(self._reference_target(value, directory))
        if identifier is None:
            return None
        try:
            evidence_path = self.path(identifier)
            kind, evidence = self._json(evidence_path)
            if kind != "evidence" or any(not isinstance(data.get(key), str) or not data[key]
                                         or evidence.get(key) != data[key]
                                         for key in ("caseRunId", "runId", "sessionId")):
                return None
            run_id, session_id, run_dir = evidence.get("runId"), evidence.get("sessionId"), evidence.get("runDir")
            if not all(isinstance(value, str) and value for value in (run_id, session_id, run_dir)):
                return None
            name = hashlib.sha256(session_id.encode("utf-8")).hexdigest() + ".jsonl"
            directory = self._reference_target(run_dir, evidence_path.parent)
            trace = self.reference(directory / name) if directory is not None else None
            if trace:
                return {"id": trace, "runId": run_id, "sessionId": session_id}
        except (OSError, ValueError):
            return None
        return None

    def _trace_focus(self, path, seq, run_id, session_id):
        require(type(seq) is int and 0 <= seq <= 9007199254740991
                and isinstance(run_id, str) and bool(run_id)
                and isinstance(session_id, str) and bool(session_id), "Invalid event locator")
        # A bounded search is separate from inspect: locating a row does not verify the recording.
        with path.open("rb") as stream:
            content = stream.read(MAX_DOCUMENT_BYTES + 1)
        require(len(content) <= MAX_DOCUMENT_BYTES, "Event lookup exceeds the 8 MiB viewer limit; browse the trace manually")
        self._verify_archive_content(path, content)
        matches = []
        for index, line in enumerate(io.BytesIO(content)):
            if len(line) > TRACE_LINE_BYTES:
                continue
            try:
                row = _viewer_json(line.decode("utf-8"))
            except (ValueError, UnicodeError):
                continue
            if not isinstance(row, dict) or not isinstance(row.get("event"), dict):
                continue
            event = row["event"]
            if (type(row.get("formatVersion")) is int and row["formatVersion"] == 1
                    and row.get("runId") == run_id and row.get("sessionId") == session_id
                    and type(event.get("seq")) is int and event["seq"] == seq):
                matches.append(index + 1)
        require(len(matches) == 1, "Event locator is missing, ambiguous or outside the preview limit; saved evidence may be stale")
        return {"seq": seq, "line": matches[0], "runId": run_id, "sessionId": session_id}

    def document(self, identifier, offset=0, limit=50, *, seq=None, run_id=None, session_id=None):
        path = self.path(identifier)
        focused = any(value is not None for value in (seq, run_id, session_id))
        require(not focused or path.suffix == ".jsonl", "Event lookup requires a trace")
        if path.suffix == ".jsonl":
            require(type(offset) is int and 0 <= offset <= 1000000 and type(limit) is int and 1 <= limit <= 200,
                    "Invalid trace page")
            focus = self._trace_focus(path, seq, run_id, session_id) if focused else None
            if focus:
                offset = max(0, focus["line"] - 1 - min(5, limit - 1))
            rows, has_more = [], False
            digest = hashlib.sha256() if self._archive is not None and path.is_relative_to(self.roots["runs"]) else None
            observed_size = 0
            def observe(content):
                nonlocal observed_size
                if digest is not None:
                    digest.update(content)
                    observed_size += len(content)
            with path.open("rb") as stream:
                index = 0
                while True:
                    line = stream.readline(TRACE_LINE_BYTES + 1)
                    if not line:
                        break
                    observe(line)
                    oversized = len(line) > TRACE_LINE_BYTES
                    if oversized and not line.endswith(b"\n"):
                        while tail := stream.readline(TRACE_LINE_BYTES):
                            observe(tail)
                            if tail.endswith(b"\n"):
                                break
                    if index >= offset:
                        if len(rows) == limit:
                            has_more = True
                            if digest is not None:
                                for tail in iter(lambda: stream.read(65536), b""):
                                    observe(tail)
                            break
                        row = {"line": index + 1}
                        try:
                            require(not oversized, "Line exceeds the 64 KiB viewer limit; preview only")
                            row["data"] = _viewer_json(line.decode("utf-8"))
                        except (ValueError, UnicodeError) as error:
                            row.update(error=str(error), preview=line[:2048].decode("utf-8", errors="replace"))
                        rows.append(row)
                    index += 1
            if digest is not None:
                self._verify_archive_digest(path, observed_size, digest.hexdigest())
            if focus:
                selected = next((row.get("data") for row in rows if row["line"] == focus["line"]), None)
                require(isinstance(selected, dict) and selected.get("runId") == run_id
                        and selected.get("sessionId") == session_id and isinstance(selected.get("event"), dict)
                        and type(selected["event"].get("seq")) is int and selected["event"]["seq"] == seq,
                        "Located event changed during reading; refresh a stable recording")
            result = {"id": identifier, "kind": "trace", "rows": rows, "offset": offset,
                      "nextOffset": offset + len(rows) if has_more else None, "links": []}
            if focus:
                result["focus"] = focus
            return result
        if path.name == "report.md":
            with path.open("rb") as stream:
                content = stream.read(MAX_DOCUMENT_BYTES + 1)
            require(len(content) <= MAX_DOCUMENT_BYTES, "Markdown exceeds the 8 MiB viewer limit")
            self._verify_archive_content(path, content)
            return {"id": identifier, "kind": "markdown", "text": content.decode("utf-8"), "links": []}
        kind, data = self._json(path)
        if kind == "archive_bundle":
            require(self._archive is not None and path == self._archive_manifest,
                    "Choose the archive bundle itself as --runs-root")
        links = [] if kind == "regression_comparison" else self._links(data, path.parent)
        result = {"id": identifier, "kind": kind, "data": data, "links": links}
        if kind == "regression_comparison":
            result["regressionSources"], result["regressionEvidence"] = self._regression_evidence(data, path.parent)
        if kind == "experiment_assertion_preview":
            result["sampleEvidence"] = self._preview_evidence(data, path.parent)
        if kind == "assertion_comparison":
            trace = self._comparison_trace(data, path.parent)
            if trace:
                result["assertionTrace"] = trace
        association = data.get("association")
        if kind == "evaluation" and isinstance(association, dict):
            run_id, session_id = association.get("runId"), association.get("sessionId")
            if all(isinstance(value, str) and value for value in (run_id, session_id)):
                name = hashlib.sha256(session_id.encode("utf-8")).hexdigest() + ".jsonl"
                link = next((link for link in links if link["label"] == "association / runDir / " + name), None)
                if link and link["id"]:
                    result["assertionTrace"] = {"id": link["id"], "runId": run_id, "sessionId": session_id}
        return result


def create_server(cases_root=None, runs_root=None, port=0):
    require(type(port) is int and 0 <= port <= 65535, "Port must be between 0 and 65535")
    browser = ArtifactBrowser(cases_root, runs_root)
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # The fragment token and artifact content must not enter access logs.

        def reply(self, status, content, content_type="application/json; charset=utf-8"):
            body = content if isinstance(content, bytes) else json.dumps(content, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            expected_host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != expected_host:
                return self.reply(403, {"error": "Invalid Host"})
            origin = self.headers.get("Origin")
            if origin is not None and origin != "http://" + expected_host:
                return self.reply(403, {"error": "Cross-origin access is not allowed"})
            url = urlsplit(self.path)
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if url.path in assets:
                name, mime = assets[url.path]
                return self.reply(200, (WEB / name).read_bytes(), mime)
            if url.path not in ("/api/catalog", "/api/document"):
                return self.reply(404, {"error": "Not found"})
            if not secrets.compare_digest(self.headers.get("Authorization", "").encode("utf-8"), ("Bearer " + token).encode("utf-8")):
                return self.reply(403, {"error": "Open the complete startup URL to authorize this viewer"})
            try:
                query = parse_qs(url.query, strict_parsing=True, keep_blank_values=True)
                require(all(len(values) == 1 for values in query.values()), "Duplicate query parameter")
                if url.path == "/api/catalog":
                    require(not query, "Catalog does not take parameters")
                    result = browser.catalog()
                else:
                    require(set(query) <= {"id", "offset", "limit", "seq", "runId", "sessionId"} and "id" in query, "Invalid document query")
                    result = browser.document(query["id"][0], int(query.get("offset", [0])[0]), int(query.get("limit", [50])[0]),
                                              seq=int(query["seq"][0]) if "seq" in query else None,
                                              run_id=query.get("runId", [None])[0], session_id=query.get("sessionId", [None])[0])
                self.reply(200, result)
            except (OSError, ValueError) as error:
                self.reply(400, {"error": str(error)})

        def do_POST(self):
            self.reply(405, {"error": "This viewer is read-only"})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.browser_url = f"http://127.0.0.1:{server.server_port}/#token={token}"
    return server


def serve(cases_root=None, runs_root=None, port=0):
    with create_server(cases_root, runs_root, port) as server:
        print(json.dumps({"browserFormatVersion": 1, "url": server.browser_url, "readOnly": True}, ensure_ascii=False), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
