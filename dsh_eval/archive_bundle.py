"""Copy a validated, explicit offline dependency graph without rewriting saved bytes."""
import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sys
from uuid import UUID, uuid4

from .archive_paths import ArchivePaths, archive_read_context
from .environment import snapshot_digest
from .formats import fields, load_json, require, validate_case
from .report import _load_report_inputs
from .resume import CLAIM_NAME


MANIFEST = "archive-manifest.json"
BLOCKED = {"home", "workspace", "node_modules", "private-notes", "secrets", "credentials", "__pycache__"}
FORMATS = {
    "experimentResultFormatVersion": ("experiment", (1,)),
    "experimentResumeResultFormatVersion": ("experiment_resume", (1, 2)),
    "comparisonReportFormatVersion": ("report", (1, 2, 3)),
    "assertionComparisonFormatVersion": ("assertion_comparison", (1,)),
    "experimentAssertionPreviewFormatVersion": ("experiment_assertion_preview", (1,)),
    "batchResultFormatVersion": ("batch", (1,)),
    "batchResumeResultFormatVersion": ("batch_resume", (1,)),
    "experimentResumePlanFormatVersion": ("experiment_resume_plan", (1, 2)),
    "batchResumePlanFormatVersion": ("batch_resume_plan", (1,)),
    "resumeClaimFormatVersion": ("claim", (1,)),
    "experimentFormatVersion": ("experiment_manifest", (1,)),
    "batchFormatVersion": ("batch_manifest", (1,)),
    "caseFormatVersion": ("case", (1, 2)),
    "evidenceFormatVersion": ("evidence", (1, 2)),
    "evaluationFormatVersion": ("evaluation", (1, 2)),
    "runtimeFormatVersion": ("runtime", (1,)),
}
PRIMARY = {"experiment", "experiment_resume"}
INCLUDES = {"report", "assertion_comparison", "experiment_assertion_preview"}


def _kind(data):
    require(isinstance(data, dict), "Archive JSON input must be an object")
    found = [(kind, key, versions) for key, (kind, versions) in FORMATS.items() if key in data]
    require(len(found) == 1, "Unknown or ambiguous archive artifact format")
    kind, key, versions = found[0]
    require(type(data[key]) is int and data[key] in versions, f"Unsupported {key}")
    return kind


def _member(name):
    require(isinstance(name, str) and bool(name.strip()) and "\\" not in name and ":" not in name
            and not any(ord(char) < 32 for char in name), "Invalid archive member path")
    parts = name.split("/")
    require(all(part not in ("", ".", "..") and part.casefold() not in BLOCKED
                and (not part.startswith(".") or index == len(parts) - 1 and part == CLAIM_NAME)
                for index, part in enumerate(parts)), "Forbidden archive member path")
    return name


def _no_links(path):
    for part in (path, *path.parents):
        require(not part.is_symlink() and not part.is_junction(), "Archive inputs cannot contain links or junctions")


def _absolute(path):
    require(isinstance(os.fspath(path), str), "Archive path must be text")
    target = Path(os.path.abspath(path))
    _no_links(target)
    return target.resolve()


def _digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _identity(data):
    require(isinstance(data, dict), "Invalid archived execution identity")
    association = data.get("association") if isinstance(data.get("association"), dict) else {}
    value = tuple(data.get(key, association.get(key)) for key in ("caseRunId", "runId", "sessionId"))
    require(all(item is None or isinstance(item, str) and item for item in value), "Invalid archived execution identity")
    return value


def _payload_inventory(payload):
    actual, directories = set(), {""}
    for directory, children, files in os.walk(payload, followlinks=False):
        current = Path(directory)
        _no_links(current)
        for name in children:
            child = current / name
            _no_links(child)
            directories.add(_member(child.relative_to(payload).as_posix()))
        for name in files:
            child = current / name
            _no_links(child)
            actual.add(_member(child.relative_to(payload).as_posix()))
    return actual, directories


def _directories(members):
    return {"", *("" if str(parent) == "." else parent.as_posix()
                  for name in members for parent in PurePosixPath(name).parents)}


class _Closure:
    def __init__(self, root, resolver=None):
        self.root, self.resolver = root, resolver
        self.files, self.kinds, self.protected = set(), {}, set()
        self.pending, self.visited = deque(), set()
        self.allowed_sources, self.identities, self.experiment_id = set(), set(), None
        self.evidence_by_identity = {}
        self.case_paths_by_identity = {}
        self.batch_paths, self.child_resume_paths = set(), set()
        self.original_experiment = None

    def reference(self, directory, value):
        require(isinstance(value, str) and bool(value.strip()), "Missing archive dependency path")
        text = value.replace("\\", "/")
        candidate = Path(text)
        if candidate.is_absolute() or PureWindowsPath(text).is_absolute():
            if self.resolver is not None:
                candidate = self.resolver.physical(value)
            else:
                require(candidate.is_absolute(), "Archive dependency uses a foreign absolute path")
        else:
            candidate = directory / candidate
        return self.safe(candidate)

    def safe(self, path):
        candidate = Path(os.path.abspath(path))
        require(candidate.is_relative_to(self.root), "Archive dependency is outside source root")
        relative = candidate.relative_to(self.root).as_posix()
        if relative != ".":
            _member(relative)
        _no_links(candidate)
        require(candidate.exists(), f"Missing archive dependency: {relative}")
        resolved = candidate.resolve()
        require(resolved.is_relative_to(self.root), "Archive dependency escaped source root")
        return resolved

    def add(self, path, kind=None):
        path = self.safe(path)
        require(path.is_file(), "Archive dependency must be a regular file")
        self.files.add(path)
        if kind is None and (path.name in ("run.json", "plan-input.json")
                             or path.name.endswith((".jsonl", ".status.json", ".tmp"))):
            kind = "raw"
        if kind not in ("raw", "recording"):
            self.pending.append(path)
        return path

    def ref(self, directory, value, kind=None):
        return self.add(self.reference(directory, value), kind)

    def run(self, directory):
        directory = self.safe(directory)
        require(directory.is_dir(), "Recording dependency must be a directory")
        self.protected.add(directory)
        manifest = self.add(directory / "run.json", "recording")
        data = load_json(manifest)
        require(isinstance(data, dict) and type(data.get("formatVersion")) is int
                and data["formatVersion"] in (1, 2), "Unsupported recording manifest")
        for row in data.get("sessions", []):
            require(isinstance(row, dict), "Invalid recording session member")
            for key in ("traceFile", "statusFile"):
                name = row.get(key)
                require(isinstance(name, str) and "/" not in name and "\\" not in name,
                        "Recording member must be flat")
                self.ref(directory, name, "recording")
        # Include every flat input inspected by Node, including invalid names or pending state.
        for path in directory.iterdir():
            if path.name.endswith((".jsonl", ".status.json", ".tmp")):
                self.add(path, "recording")

    def row(self, directory, row):
        require(isinstance(row, dict), "Invalid archived sample")
        for key in ("casePath", "evidencePath", "evaluationPath", "runtimeReport"):
            if row.get(key) is not None:
                self.ref(directory, row[key])
        if row.get("caseDirectory") is not None:
            case_directory = self.reference(directory, row["caseDirectory"])
            self.protected.add(case_directory)
            self.add(case_directory / "case.json")
        if row.get("runDir") is not None:
            self.run(self.reference(directory, row["runDir"]))

    def context(self, path):
        result = _load_report_inputs(path)
        samples = list(result[4])
        return (*result[:4], samples, result[5])

    def primary(self, path):
        kind = _kind(load_json(path))
        require(kind in PRIMARY, "Archive entry must be an ordinary experiment or selected experiment continuation")
        context = self.context(path)
        self.experiment_id = context[0]["experimentId"]
        self.allowed_sources = {path}
        metadata = context[5] or {}
        for key in ("sourceExperimentResult", "sourceResumeResult"):
            if metadata.get(key):
                self.allowed_sources.add(self.reference(path.parent, metadata[key]))
        for row in metadata.get("resumeChain", []):
            self.allowed_sources.add(self.reference(path.parent, row["resultPath"]))
        self.original_experiment = self.reference(path.parent, metadata["sourceExperimentResult"]) if metadata.get("sourceExperimentResult") else path
        for source in self.allowed_sources:
            header = load_json(source)
            if _kind(header) == "experiment":
                value = header.get("batchResultPath") or header.get("batchBinding", {}).get("resultPath")
                self.batch_paths.add(self.reference(source.parent, value))
            else:
                child = self.reference(source.parent, header["batchResumeResultPath"])
                self.child_resume_paths.add(child)
                saved_child = load_json(child)
                value = saved_child.get("batchResultPath") or saved_child.get("batchBinding", {}).get("resultPath")
                self.batch_paths.add(self.reference(child.parent, value))
        self.identities = {_identity(row)
                           for row, _base, _batch, _origin in context[4] if row.get("caseRunId") is not None}
        self.evidence_by_identity = {_identity(row): self.reference(base, row["evidencePath"])
                                     for row, base, _batch, _origin in context[4] if row.get("evidencePath") is not None}
        for row, base, _batch, _origin in context[4]:
            if row.get("caseRunId") is not None:
                identity = _identity(row)
                self.case_paths_by_identity[identity] = {self.reference(base, row["casePath"])}
                if identity in self.evidence_by_identity:
                    self.case_paths_by_identity[identity].add(self.evidence_by_identity[identity].parent / "case.json")
            self.row(base, row)
        return kind

    def artifact(self, path):
        path = self.safe(path)
        data = load_json(path)
        kind = _kind(data)
        require(kind in INCLUDES, "Unsupported selected archive artifact")
        if kind in ("report", "experiment_assertion_preview"):
            key = ("experimentPath" if kind == "experiment_assertion_preview" else
                   "sourceResumeResult" if data.get("sourceResumeResult") is not None else "sourceExperimentResult")
            source = self.reference(path.parent, data.get(key))
            require(source in self.allowed_sources and data.get("experimentId") == self.experiment_id,
                    "Selected artifact is not bound to the selected experiment chain")
            self.context(source)
            if kind == "experiment_assertion_preview":
                saved = load_json(source)
                require(type(saved.get("experimentResultFormatVersion")) is int
                        and saved["experimentResultFormatVersion"] == 1 and saved.get("status") == "completed",
                        "Experiment preview requires a completed ordinary experiment")
        else:
            require(_identity(data) in self.identities,
                    "Selected comparison is not bound to a selected experiment sample")
        self.add(path)
        return kind

    def hashes(self, directory, data):
        values = data.get("sourceFilesSha256")
        if values is not None:
            require(isinstance(values, dict), "Invalid source file hashes")
            key = "sourceBatchResult" if "batchResumePlanFormatVersion" in data else "sourceExperimentResult"
            base = self.reference(directory, data[key]).parent
            for name, digest in values.items():
                require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest), "Invalid source file digest")
                self.ref(base, name)
        for plan in data.get("batchPlans", []):
            require(isinstance(plan, dict), "Invalid nested batch plan")
            self.hashes(directory, plan)

    def visit(self):
        while self.pending:
            path = self.pending.popleft()
            if path in self.visited:
                continue
            self.visited.add(path)
            directory, data = path.parent, load_json(path)
            kind = _kind(data)
            self.kinds[path] = kind
            if kind in ("experiment", "experiment_resume", "batch", "batch_resume", "report", "assertion_comparison",
                        "experiment_assertion_preview"):
                self.protected.add(directory)
            if kind == "experiment":
                self.ref(directory, data["manifestPath"])
                batch_path = data.get("batchResultPath")
                if batch_path is None:
                    binding = data.get("batchBinding")
                    require(isinstance(binding, dict), "Missing original experiment batch binding")
                    batch_path = binding.get("resultPath")
                self.ref(directory, batch_path)
                if data.get("planInputPath") is not None:
                    self.ref(directory, data["planInputPath"], "raw")
                expanded = directory / "expanded.batch.json"
                if expanded.exists():
                    self.add(expanded)
                for row in data["samples"]:
                    self.row(directory, row)
            elif kind in ("experiment_manifest", "batch_manifest"):
                for row in data["cases"]:
                    self.ref(directory, row["casePath"])
            elif kind == "batch":
                self.ref(directory, data["manifestPath"])
                for row in data["entries"]:
                    self.row(directory, row)
            elif kind in ("experiment_resume", "batch_resume"):
                self.add(directory / "resume-plan.json")
                for key in ("sourceExperimentResult", "sourceResumeResult", "sourceBatchResult", "batchResumeResultPath",
                            "batchResultPath"):
                    if data.get(key) is not None:
                        self.ref(directory, data[key])
                if kind == "batch_resume":
                    self.add(directory / "remaining.batch.json")
                    source_batch = self.reference(directory, data["sourceBatchResult"])
                    self.add(source_batch.parent / CLAIM_NAME)
                binding = data.get("batchBinding")
                if binding is not None:
                    self.ref(directory, binding["resultPath"])
            elif kind in ("experiment_resume_plan", "batch_resume_plan"):
                for key in ("sourceExperimentResult", "sourceResumeResult", "sourceBatchResult"):
                    if data.get(key) is not None:
                        self.ref(directory, data[key])
                self.hashes(directory, data)
            elif kind == "case":
                validate_case(data)
            elif kind == "evidence":
                self.add(directory / "case.json")
                if data.get("runtimeReport") is not None:
                    self.ref(directory, data["runtimeReport"])
                if data.get("runDir") is not None:
                    self.run(self.reference(directory, data["runDir"]))
            elif kind == "evaluation":
                association = data.get("association")
                require(isinstance(association, dict), "Missing saved evaluation association")
                identity = _identity(data)
                evidence_path = self.reference(directory, association["evidencePath"])
                require(evidence_path == self.evidence_by_identity.get(identity),
                        "Evaluation evidence is outside the selected experiment chain")
                evidence = load_json(evidence_path)
                require(identity == _identity(evidence), "Evaluation/evidence identity mismatch")
                case_path = self.reference(directory, association["casePath"])
                require(case_path in self.case_paths_by_identity.get(identity, set()),
                        "Evaluation case is outside the selected experiment inputs")
                self.add(evidence_path)
                self.add(case_path)
                if association.get("runtimeReport") is not None:
                    runtime_path = self.reference(directory, association["runtimeReport"])
                    require(evidence.get("runtimeReport") is not None
                            and runtime_path == self.reference(evidence_path.parent, evidence["runtimeReport"]),
                            "Evaluation runtime differs from canonical evidence")
                    self.add(runtime_path)
                if association.get("runDir") is not None:
                    run_directory = self.reference(directory, association["runDir"])
                    require(evidence.get("runDir") is not None
                            and run_directory == self.reference(evidence_path.parent, evidence["runDir"]),
                            "Evaluation recording differs from canonical evidence")
                    self.run(run_directory)
            elif kind == "report":
                for key in ("sourceExperimentResult", "sourceResumeResult"):
                    if data.get(key) is not None:
                        source = self.ref(directory, data[key])
                        require(source == self.original_experiment if key == "sourceExperimentResult" else
                                source in self.allowed_sources and _kind(load_json(source)) == "experiment_resume",
                                "Report source is outside the selected experiment chain")
                self.add(directory / "report.md", "raw")
                for row in data["samples"]:
                    identity = _identity(row)
                    require(identity == (None, None, None) or identity in self.identities,
                            "Report sample is outside the selected experiment chain")
                    for key in ("evaluationPath", "sourceEvidencePath", "sourceBatchResult"):
                        if row.get(key) is not None:
                            dependency = self.ref(directory, row[key])
                            if key in ("evaluationPath", "sourceEvidencePath"):
                                require(_identity(load_json(dependency)) == identity,
                                        "Report sample dependency identity mismatch")
                            if key == "sourceEvidencePath":
                                require(dependency == self.evidence_by_identity.get(identity),
                                        "Report evidence is outside the selected experiment chain")
                            if key == "sourceBatchResult":
                                require(dependency in self.batch_paths, "Report batch is outside the selected experiment chain")
                for value in data.get("batchResultPaths", []):
                    require(self.ref(directory, value) in self.batch_paths,
                            "Report batch is outside the selected experiment chain")
                for row in data.get("resumeChain", []):
                    source = self.ref(directory, row["resultPath"])
                    require(source in self.allowed_sources and _kind(load_json(source)) == "experiment_resume",
                            "Report continuation is outside the selected experiment chain")
                verification = data.get("resumeVerification") or {}
                if verification.get("batchResumeResult") is not None:
                    require(self.ref(directory, verification["batchResumeResult"]) in self.child_resume_paths,
                            "Report child continuation is outside the selected experiment chain")
            elif kind == "assertion_comparison":
                evidence = self.ref(directory, data["evidencePath"])
                saved = load_json(evidence)
                require(_identity(data) == _identity(saved) and evidence == self.evidence_by_identity.get(_identity(data)),
                        "Comparison/evidence identity mismatch")
                for key in ("source", "batchId"):
                    if key in data:
                        require(data[key] == saved.get(key), "Comparison/evidence source or batch mismatch")
                cases = []
                for key in ("baseline", "candidate"):
                    case = self.ref(directory, data[key]["casePath"])
                    require(data[key].get("caseSha256") == snapshot_digest(load_json(case)), "Comparison case changed")
                    cases.append(load_json(case))
                    if key == "baseline":
                        require(case == evidence.parent / "case.json", "Comparison baseline must be the evidence's sibling case.json")
                require(snapshot_digest({key: value for key, value in cases[0].items() if key != "assertions"})
                        == snapshot_digest({key: value for key, value in cases[1].items() if key != "assertions"}),
                        "Comparison candidate may change only assertions")
            elif kind == "experiment_assertion_preview":
                source = self.ref(directory, data["experimentPath"])
                context = self.context(source)
                require(context[3]["status"] == "verified" and data.get("planFingerprint") == context[3]["fingerprint"],
                        "Preview plan fingerprint is not bound to the frozen experiment")
                rule_map = self.ref(directory, data["ruleMapPath"], "raw")
                rules = load_json(rule_map)
                require(snapshot_digest(rules) == data.get("ruleMapSha256"), "Preview rule map changed")
                fields(rules, ("assertionRuleMapFormatVersion", "cases"))
                require(type(rules["assertionRuleMapFormatVersion"]) is int and rules["assertionRuleMapFormatVersion"] == 1
                        and isinstance(rules["cases"], dict) and rules["cases"].keys() == context[2].keys(),
                        "Preview rule map must cover exactly the frozen case entries")
                for key, case in context[2].items():
                    validate_case({**case, "assertions": rules["cases"][key]})
                for row in data["samples"]:
                    if row.get("evidencePath") is not None:
                        evidence = self.ref(directory, row["evidencePath"])
                        saved = load_json(evidence)
                        require(_identity(row) in self.identities and _identity(row) == _identity(saved)
                                and evidence == self.evidence_by_identity.get(_identity(row)),
                                "Preview/evidence identity mismatch")
            elif kind not in ("runtime", "claim"):
                raise ValueError("Unsupported archive dependency")


def _closure(entry, source_root, artifacts=(), resolver=None):
    graph = _Closure(source_root, resolver)
    entry = graph.safe(entry)
    primary_kind = graph.primary(entry)
    graph.add(entry)
    selected = [{"path": entry, "kind": primary_kind}]
    seen = {entry}
    for path in artifacts:
        path = graph.safe(path)
        require(path not in seen, "Duplicate selected archive artifact")
        seen.add(path)
        selected.append({"path": path, "kind": graph.artifact(path)})
    graph.visit()
    return graph, selected


def export_archive(entry, source_root, output, artifacts=()):
    """Create a new directory package; only the final manifest publishes a complete copy."""
    root, output = _absolute(source_root), _absolute(output)
    require(root.is_dir(), "Archive source root must be a directory")
    require(not output.exists(), "Archive output already exists")
    entry = _absolute(entry)
    graph, selected = _closure(entry, root, [_absolute(path) for path in artifacts])
    require(all(not output.is_relative_to(directory) for directory in graph.protected),
            "Archive output must be outside selected artifact directories")
    before = {path: (path.stat().st_size, _digest(path)) for path in sorted(graph.files)}
    output.mkdir(parents=True, exist_ok=False)
    payload = output / "payload"
    payload.mkdir()
    records = []
    for path, (size, digest) in before.items():
        relative = _member(path.relative_to(root).as_posix())
        target = payload / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        graph.safe(path)
        with path.open("rb") as source, target.open("xb") as destination:
            shutil.copyfileobj(source, destination)
        require(target.stat().st_size == size and _digest(target) == digest, "Archive input changed during copy")
        records.append({"path": "payload/" + relative, "size": size, "sha256": digest})
    members = {row["path"].removeprefix("payload/") for row in records}
    resolver = ArchivePaths(str(root), payload, members)
    with archive_read_context(resolver):
        copied, copied_selected = _closure(payload / entry.relative_to(root), payload,
                                            [payload / item["path"].relative_to(root) for item in selected[1:]], resolver)
    require({path.relative_to(payload).as_posix() for path in copied.files} == members,
            "Copied archive dependency closure differs from its inventory")
    descriptors = [{"path": "payload/" + item["path"].relative_to(root).as_posix(), "kind": item["kind"]}
                   for item in selected]
    require([{"path": "payload/" + item["path"].relative_to(payload).as_posix(), "kind": item["kind"]}
             for item in copied_selected] == descriptors, "Copied archive artifact bindings changed")
    require(_payload_inventory(payload) == (members, _directories(members))
            and {path.name for path in output.iterdir()} == {"payload"}, "Copied archive inventory changed")
    require(all(resolver.physical(output / row["path"]).stat().st_size == row["size"]
                and _digest(output / row["path"]) == row["sha256"] for row in records), "Copied archive input changed")
    require(all(graph.safe(path).stat().st_size == size and _digest(path) == digest
                for path, (size, digest) in before.items()), "Archive input changed after copy")
    manifest = {"archiveBundleFormatVersion": 1, "archiveId": str(uuid4()),
                "createdAt": datetime.now(timezone.utc).isoformat(), "logicalSourceRoot": str(root),
                "entryPath": "payload/" + entry.relative_to(root).as_posix(),
                "artifacts": descriptors, "files": records, "modelCalled": False}
    with (output / MANIFEST).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def load_archive(manifest_or_dir):
    """Verify package inventory and bytes without reading any original source location."""
    path = _absolute(manifest_or_dir)
    manifest_path = path / MANIFEST if path.is_dir() else path
    require(manifest_path.name == MANIFEST, "Expected archive-manifest.json or its directory")
    _no_links(manifest_path)
    manifest = load_json(manifest_path)
    fields(manifest, ("archiveBundleFormatVersion", "archiveId", "createdAt", "logicalSourceRoot", "entryPath",
                      "artifacts", "files", "modelCalled"))
    require(type(manifest["archiveBundleFormatVersion"]) is int and manifest["archiveBundleFormatVersion"] == 1
            and manifest["modelCalled"] is False, "Unsupported archive bundle format")
    require(isinstance(manifest["archiveId"], str) and str(UUID(manifest["archiveId"])) == manifest["archiveId"],
            "Invalid archive identity")
    require(isinstance(manifest["createdAt"], str) and datetime.fromisoformat(manifest["createdAt"]).tzinfo is not None,
            "Invalid archive creation time")
    require(isinstance(manifest["files"], list) and bool(manifest["files"]), "Archive file inventory is missing")
    members, expected_directories = {}, {""}
    for row in manifest["files"]:
        fields(row, ("path", "size", "sha256"))
        name = _member(row["path"])
        require(name.startswith("payload/") and len(name) > len("payload/"), "Archive files must be in payload")
        relative = name[len("payload/"):]
        require(relative not in members and type(row["size"]) is int and row["size"] >= 0
                and isinstance(row["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]),
                "Invalid or duplicate archive file inventory")
        members[relative] = row
        expected_directories.update("" if str(parent) == "." else parent.as_posix() for parent in PurePosixPath(relative).parents)
    payload = manifest_path.parent / "payload"
    resolver = ArchivePaths(manifest["logicalSourceRoot"], payload, members)
    actual, actual_directories = _payload_inventory(payload)
    require(actual == members.keys() and actual_directories == expected_directories, "Archive payload inventory differs from manifest")
    require({child.name for child in manifest_path.parent.iterdir()} == {MANIFEST, "payload"}, "Unlisted archive root content")
    for name, row in members.items():
        path = resolver.physical(payload / name)
        require(path.is_file() and path.stat().st_size == row["size"] and _digest(path) == row["sha256"],
                f"Archive file missing or changed: {name}")
    require(isinstance(manifest["artifacts"], list) and bool(manifest["artifacts"]), "Archive artifacts are missing")
    selected = set()
    for artifact in manifest["artifacts"]:
        fields(artifact, ("path", "kind"))
        name = _member(artifact["path"])
        require(name.startswith("payload/") and name[len("payload/"):] in members
                and name not in selected and isinstance(artifact["kind"], str)
                and artifact["kind"] in PRIMARY | INCLUDES, "Invalid archive artifact")
        selected.add(name)
    require(isinstance(manifest["entryPath"], str) and manifest["entryPath"] in selected
            and next(item["kind"] for item in manifest["artifacts"]
            if item["path"] == manifest["entryPath"]) in PRIMARY, "Archive entry is not a primary experiment")
    return manifest, resolver


def verify_archive(manifest_or_dir):
    manifest, resolver = load_archive(manifest_or_dir)
    entry = resolver.payload_root / manifest["entryPath"][len("payload/"):]
    artifacts = [resolver.payload_root / item["path"][len("payload/"):]
                 for item in manifest["artifacts"] if item["path"] != manifest["entryPath"]]
    with archive_read_context(resolver):
        graph, selected = _closure(entry, resolver.payload_root, artifacts, resolver)
    require({path.relative_to(resolver.payload_root).as_posix() for path in graph.files} == resolver.members,
            "Archive inventory contains files outside its dependency closure")
    observed = [{"path": "payload/" + item["path"].relative_to(resolver.payload_root).as_posix(), "kind": item["kind"]}
                for item in selected]
    require(observed == manifest["artifacts"], "Archive artifact kind or order mismatch")
    return {"archiveVerificationFormatVersion": 1, "archiveId": manifest["archiveId"], "status": "verified",
            "modelCalled": False, "taskEvaluationPerformed": False, "entryPath": manifest["entryPath"],
            "verifiedFiles": len(resolver.members), "artifacts": manifest["artifacts"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export or verify an immutable directory archive; never calls a model")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--entry", required=True)
    export.add_argument("--source-root", required=True)
    export.add_argument("--output", required=True)
    export.add_argument("--include", action="append", default=[])
    verify = commands.add_parser("verify")
    verify.add_argument("archive")
    args = parser.parse_args(argv)
    try:
        result = (export_archive(args.entry, args.source_root, args.output, artifacts=args.include)
                  if args.command == "export" else verify_archive(args.archive))
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        print(json.dumps({"archiveBundleFormatVersion": 1, "status": "error", "modelCalled": False,
                          "error": str(error)}, ensure_ascii=False), flush=True)
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
