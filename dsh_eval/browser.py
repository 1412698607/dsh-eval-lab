"""Loopback-only, read-only viewer of saved evaluation artifacts. Never runs tasks."""
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
from urllib.parse import parse_qs, urlsplit

from .formats import parse_json, require


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
           "experimentResumeResultFormatVersion": ("experiment_resume", (1, 2)),
           "batchResumeResultFormatVersion": ("batch_resume", (1,)),
           "evaluationFormatVersion": ("evaluation", (1, 2)), "evidenceFormatVersion": ("evidence", (1, 2)),
           "runtimeFormatVersion": ("runtime", (1,)), "formatVersion": ("recording", (1, 2)),
           "statusFormatVersion": ("recording", (1,))}
RESULT_NAMES = {"batch-result.json", "experiment-result.json", "report.json", "evaluation.json",
                "resume-result.json", "experiment-resume-result.json"}
TRACE_NAME = re.compile(r"[0-9a-f]{64}\.jsonl\Z")


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

    def _resolve_reference(self, target):
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
            for directory, directories, files in os.walk(root, followlinks=False, onerror=walk_error):
                directories[:] = sorted(name for name in directories if not name.startswith(".")
                                         and name.casefold() not in BLOCKED
                                         and not (Path(directory) / name).is_symlink()
                                         and not (Path(directory) / name).is_junction()
                                         and (Path(directory) / name).resolve().is_relative_to(root))
                for name in sorted(files):
                    if not (name.endswith(".case.json") if label == "cases" else name in RESULT_NAMES):
                        continue
                    identifier = self.reference(Path(directory) / name)
                    if identifier is None:
                        continue
                    if len(items) >= MAX_CATALOG_ITEMS:
                        truncated = True
                        break
                    item = {"id": identifier, "path": identifier.split(":", 1)[1], "kind": "unknown"}
                    try:
                        kind, data = self._json(self.path(identifier))
                        item.update(kind=kind, title=data.get("experimentName") or data.get("batchName")
                                    or data.get("caseId") or data.get("reportId") or data.get("resumeId") or name,
                                    outcome=data.get("outcome"), status=data.get("status"), source=data.get("source"),
                                    time=data.get("generatedAt") or data.get("finishedAt") or data.get("evaluatedAt") or data.get("startedAt"))
                        summary = data.get("summary")
                        item["outcomes"] = summary.get("outcomes") if isinstance(summary, dict) else None
                        if kind == "evaluation" and isinstance(data.get("execution"), dict):
                            item["status"] = data["execution"].get("status")
                        rows = data.get("samples") or data.get("entries") or []
                        require(isinstance(rows, list), "Artifact samples/entries must be an array")
                        item["sources"] = sorted({row["source"] if isinstance(row.get("source"), str) and row["source"] else "unknown"
                                                  for row in rows if isinstance(row, dict)})
                        if kind in ("batch_resume", "experiment_resume"):
                            item["sources"] = _resume_sources(data, kind)
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
            path = Path(value.replace("\\", "/"))
            target = path if path.is_absolute() else directory / path
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
        binding = data.get("batchBinding")
        result_path = data.get("batchResultPath")
        if (result_path is None or result_path == "") and isinstance(binding, dict):
            add("batchBinding / resultPath", binding.get("resultPath"))
        collect(data.get("association"), "association / ")
        collect(data.get("resumeVerification"), "resumeVerification / ")
        for index, value in enumerate(data.get("batchResultPaths", []) if isinstance(data.get("batchResultPaths"), list) else [], 1):
            add(f"批次 {index} / batchResultPath", value)
        for index, row in enumerate(data.get("resumeChain", []) if isinstance(data.get("resumeChain"), list) else [], 1):
            if isinstance(row, dict):
                add(f"续跑 {index} / resultPath", row.get("resultPath"))
        for key in ("entries", "samples", "cases"):
            rows = data.get(key)
            if isinstance(rows, list):
                for index, row in enumerate(rows, 1):
                    collect(row, f"{index} / ")
        if "comparisonReportFormatVersion" in data:
            add("Markdown", "report.md")
        return links

    def _trace_focus(self, path, seq, run_id, session_id):
        require(type(seq) is int and 0 <= seq <= 9007199254740991
                and isinstance(run_id, str) and bool(run_id)
                and isinstance(session_id, str) and bool(session_id), "Invalid event locator")
        # A bounded search is separate from inspect: locating a row does not verify the recording.
        with path.open("rb") as stream:
            content = stream.read(MAX_DOCUMENT_BYTES + 1)
        require(len(content) <= MAX_DOCUMENT_BYTES, "Event lookup exceeds the 8 MiB viewer limit; browse the trace manually")
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
            with path.open("rb") as stream:
                index = 0
                while True:
                    line = stream.readline(TRACE_LINE_BYTES + 1)
                    if not line:
                        break
                    oversized = len(line) > TRACE_LINE_BYTES
                    if oversized and not line.endswith(b"\n"):
                        while (tail := stream.readline(TRACE_LINE_BYTES)) and not tail.endswith(b"\n"):
                            pass
                    if index >= offset:
                        if len(rows) == limit:
                            has_more = True
                            break
                        row = {"line": index + 1}
                        try:
                            require(not oversized, "Line exceeds the 64 KiB viewer limit; preview only")
                            row["data"] = _viewer_json(line.decode("utf-8"))
                        except (ValueError, UnicodeError) as error:
                            row.update(error=str(error), preview=line[:2048].decode("utf-8", errors="replace"))
                        rows.append(row)
                    index += 1
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
            return {"id": identifier, "kind": "markdown", "text": content.decode("utf-8"), "links": []}
        kind, data = self._json(path)
        links = self._links(data, path.parent)
        result = {"id": identifier, "kind": kind, "data": data, "links": links}
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
