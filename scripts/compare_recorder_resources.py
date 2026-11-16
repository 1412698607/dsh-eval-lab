"""Read-only paired comparison of completed recorder measurement v2 artifacts."""
from __future__ import annotations

import argparse
import calendar
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys


IDENTITY_RUN = "00000000-0000-0000-0000-000000000000"
IDENTITY_TIME = "2000-01-01T00:00:00.000Z"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
GENERATED_TIMESTAMP = re.compile(r"([0-9]{4}|[+-][0-9]{6})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})\.([0-9]{3})Z\Z")
PROVENANCE_FILES = {
    "recorder": ["recorder.js", "config.js", "metadata.js", "session-status.js", "../package.json"],
    "inspector": ["inspect.js", "config.js", "metadata.js", "session-status.js", "../package.json", "recorder.js"],
    "measurement": ["measure-recorder.js", "recorder-measurement.js"],
}


class ComparisonError(ValueError):
    """The sources do not support the requested paired comparison."""


def require(condition, message):
    if not condition:
        raise ComparisonError(message)


def generated_timestamp(value, field):
    match = GENERATED_TIMESTAMP.fullmatch(value) if isinstance(value, str) else None
    require(match is not None, f"invalid generated timestamp: {field}")
    parts = tuple(int(part) for part in match.groups())
    year, month, day, hour, minute, second, _ = parts
    # Match Date.toISOString, including year zero and the extended years within JS Date's range.
    require((len(match[1]) == 4) == (0 <= year <= 9999)
            and 1 <= month <= 12 and 1 <= day <= calendar.monthrange(year, month)[1]
            and hour < 24 and minute < 60 and second < 60
            and (-271821, 4, 20, 0, 0, 0, 0) <= parts <= (275760, 9, 13, 0, 0, 0, 0),
            f"invalid generated timestamp: {field}")


def metric_value(value, name):
    require(value is None or type(value) in (float, int), f"invalid metric: {name}")
    require(value is None or -sys.float_info.max <= value <= sys.float_info.max, f"nonfinite metric: {name}")
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def compact(value):
    # The measurement protocol hashes JSON.stringify output in insertion order.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def decode(data):
    return json.loads(data.decode("utf-8"), object_pairs_hook=unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ComparisonError(f"nonfinite JSON: {value}")))


class Sources:
    """Record the exact bytes read, then recheck them before writing any output."""

    def __init__(self):
        self.hashes = {}
        self.directories = {}

    def read(self, path):
        path = path.resolve(strict=True)
        data = path.read_bytes()
        current = digest(data)
        require(path not in self.hashes or self.hashes[path] == current, f"source changed while reading: {path}")
        self.hashes[path] = current
        return data

    def json(self, path):
        return decode(self.read(path))

    def files(self, directory):
        directory = directory.resolve(strict=True)
        entries = list(directory.iterdir())
        require(all(item.is_file() and not item.is_symlink() for item in entries), f"unexpected directory/link: {directory}")
        names = sorted(item.name for item in entries)
        self.directories[directory] = names
        return names

    def verify_unchanged(self):
        for path, expected in self.hashes.items():
            require(digest(path.read_bytes()) == expected, f"source changed during comparison: {path}")
        for path, expected in self.directories.items():
            require(sorted(item.name for item in path.iterdir()) == expected, f"source file set changed: {path}")


def within(directory, relative):
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(), "expected relative artifact path")
    path = (directory / relative).resolve(strict=True)
    require(path.is_relative_to(directory.resolve(strict=True)), f"artifact escapes source directory: {relative}")
    return path


def provenance(value, sources):
    require(isinstance(value, dict) and set(value) == {"recorder", "inspector", "measurement"}, "missing source provenance")
    result = {}
    for group, info in value.items():
        files = info["files"]
        require(isinstance(files, list) and files, f"missing provenance files: {group}")
        names = [row["name"] for row in files]
        require(names == PROVENANCE_FILES[group], f"unexpected provenance dependency set: {group}")
        entry_directory = Path(files[0]["path"]).parent
        for row in files:
            require(isinstance(row["name"], str) and isinstance(row["path"], str)
                    and SHA256.fullmatch(row["sha256"]), f"invalid provenance file: {group}")
            path = Path(row["path"])
            require(path.is_absolute(), f"provenance source path must be absolute: {group}/{row['name']}")
            if row is not files[0]:
                require(path.resolve(strict=True) == (entry_directory / row["name"]).resolve(strict=True),
                        f"provenance dependency path mismatch: {group}/{row['name']}")
            require(digest(sources.read(path)) == row["sha256"], f"actual provenance source digest mismatch: {group}/{row['name']}")
        canonical = [{"name": row["name"], "sha256": row["sha256"]} for row in files]
        require(info["sha256"] == digest(compact(canonical)), f"provenance digest mismatch: {group}")
        result[group] = {"sha256": info["sha256"], "files": canonical}
    return result


def normalize_artifacts(sample, root, sources):
    run_directory = within(root, sample["runDirectory"])
    names = sources.files(run_directory)
    manifest = sources.json(run_directory / "run.json")
    require(manifest["runId"] == sample["runId"], "run identity mismatch")
    require(manifest["state"] == ("failed" if sample["closeRejected"] else "sealed"), "manifest/close state mismatch")
    expected_names = {"run.json"}
    traces = {}
    files = []
    for member in manifest["sessions"]:
        trace_name = member["traceFile"]
        require(Path(trace_name).name == trace_name and trace_name not in traces, "invalid/duplicate trace filename")
        require(Path(member["statusFile"]).name == member["statusFile"], "invalid status filename")
        expected_names.add(member["statusFile"])
        raw = sources.read(run_directory / trace_name) if trace_name in names else b""
        rows = [decode(line) for line in raw.rstrip().splitlines()] if raw else []
        require(raw == b"".join(compact(row) + b"\n" for row in rows), "trace is not canonical UTF-8 JSONL")
        normalized = bytearray()
        for row in rows:
            require(row["runId"] == sample["runId"] and row["sessionId"] == member["sessionId"], "trace identity mismatch")
            row["runId"] = IDENTITY_RUN
            normalized.extend(compact(row) + b"\n")
        trace = {"sha256": digest(raw), "normalizedSha256": digest(normalized), "bytes": len(raw), "count": len(rows)}
        traces[trace_name] = trace
        if raw:
            expected_names.add(trace_name)
            files.append({"file": trace_name, **trace})
    require(names == sorted(expected_names), "unexpected/missing recorder output files")
    totals = {"received": 0, "accepted": 0, "written": 0, "writtenBytes": 0, "sealed": 0, "failed": 0}
    errors = []
    for name in (name for name in names if name.endswith(".json")):
        raw = sources.read(run_directory / name)
        data = decode(raw)
        require(data["runId"] == sample["runId"], "status/manifest identity mismatch")
        data["runId"] = IDENTITY_RUN
        if name == "run.json":
            generated_timestamp(data["startedAt"], "startedAt")
            data["startedAt"] = IDENTITY_TIME
        else:
            require(data["state"] in ("sealed", "failed"), "session is not completed")
            for total, field in (("received", "receivedCount"), ("accepted", "acceptedCount"),
                                 ("written", "writtenCount"), ("writtenBytes", "writtenBytes")):
                require(type(data[field]) is int and data[field] >= 0, "invalid persisted count")
                totals[total] += data[field]
            totals[data["state"]] += 1
            if data["error"] is not None:
                errors.append({"code": data["error"]["code"], "message": data["error"]["message"], "sessionId": data["sessionId"]})
            generated_timestamp(data["updatedAt"], "updatedAt")
            data["updatedAt"] = IDENTITY_TIME
            trace = traces[data["traceFile"]]
            require(data["sha256"] == trace["sha256"] and data["writtenCount"] == trace["count"]
                    and data["writtenBytes"] == trace["bytes"], "status does not match actual trace")
            data["sha256"] = trace["normalizedSha256"]
        files.append({"file": name, "bytes": len(raw), "sha256": digest(raw), "normalizedSha256": digest(compact(data))})
    require(totals == sample["totals"] and totals["accepted"] == sample["accepted"]
            and totals["writtenBytes"] == sample["io"]["appendedBytes"], "persisted totals differ from measurement")
    require(sorted(errors, key=lambda row: row["sessionId"]) == sorted(sample["errors"], key=lambda row: row["sessionId"]),
            "persisted errors differ from measurement")
    files.sort(key=lambda row: row["file"])
    inspection = deepcopy(sample["inspection"])
    # Saved absolute paths are recording metadata; the artifact tree may have moved.
    require(isinstance(inspection["runDir"], str) and Path(inspection["runDir"]).name == sample["runId"],
            "inspection run identity mismatch")
    inspection["runDir"] = "<run-directory>"
    for session in inspection["sessions"]:
        if "sha256" in session:
            trace = traces[session["traceFile"]]
            require(session["sha256"] == trace["sha256"], "inspection trace digest mismatch")
            session["sha256"] = trace["normalizedSha256"]
    evidence = {"files": files,
                "normalizedFilesSha256": digest(compact([{key: row[key] for key in ("file", "bytes", "normalizedSha256")} for row in files])),
                "normalizedInspectionSha256": digest(compact(inspection))}
    require(evidence == sample["artifacts"], "saved artifact evidence differs from actual files/inspection")
    return evidence, inspection


def load_measurement(path, sources):
    summary = sources.json(path)
    require(summary["measurementFormatVersion"] == 2 and summary["source"] == "synthetic"
            and summary["modelCalled"] is False, "requires synthetic measurement format 2 without model calls")
    require(summary["status"] == "completed" and not summary.get("failure"), "measurement is not completed")
    repeats = summary["repeats"]
    scenarios = summary["scenarios"]
    require(type(repeats) is int and 1 <= repeats <= 10, "invalid repeat count")
    require(isinstance(scenarios, list) and scenarios and all(isinstance(name, str) and name for name in scenarios)
            and len(set(scenarios)) == len(scenarios), "invalid or duplicate scenarios")
    require(isinstance(summary["samplingProtocol"], dict) and summary["samplingProtocol"], "missing sampling protocol")
    require(isinstance(summary["environment"], dict) and summary["environment"], "missing environment")
    source = provenance(summary["provenance"], sources)
    expected = {(scenario, repeat) for scenario in scenarios for repeat in range(1, repeats + 1)}
    indexed = {}
    for sample in summary["samples"]:
        key = (sample["scenario"], sample["repeat"])
        require(type(sample["repeat"]) is int and key in expected and key not in indexed, f"unexpected/duplicate sample: {key}")
        require(sample["status"] == "completed", f"sample is not completed: {key}")
        require(all(type(sample[field]) is int and sample[field] >= 0 for field in ("accepted", "rejected"))
                and type(sample["closeRejected"]) is bool, f"invalid counts/close state: {key}")
        require(provenance(sample["provenance"], sources) == source, f"sample provenance differs from summary: {key}")
        require(sample["samplingProtocol"] == summary["samplingProtocol"], f"sample samplingProtocol mismatch: {key}")
        for field in ("workloadFingerprint", "inputSha256"):
            require(isinstance(sample[field], str) and SHA256.fullmatch(sample[field]), f"invalid {field}: {key}")
        fingerprint = {"scenario": sample["scenario"], "workload": sample["workload"],
                       "inputSha256": sample["inputSha256"], "samplingProtocol": sample["samplingProtocol"]}
        require(sample["workloadFingerprint"] == digest(compact(fingerprint)), f"workload fingerprint mismatch: {key}")
        actual_measurement = sources.json(within(path.parent, sample["runDirectory"]).parent / "measurement.json")
        require(actual_measurement == sample, f"summary/measurement mismatch: {key}")
        indexed[key] = sample
    require(set(indexed) == expected, "missing scenario/repeat samples")
    return summary, source, indexed


def flatten_metrics(sample):
    result = {}

    def visit(prefix, value, members=None):
        if members is not None and value is not None:
            require(isinstance(value, dict) and value, f"invalid metric object: {prefix}")
            for key, member in value.items():
                visit(f"{prefix}.{key}", member, members.get(key))
        else:
            result[prefix] = metric_value(value, prefix)

    for key in ("closeMs", "measurementMs"):
        visit(key, sample[key])
    containers = {"io": {key: {} for key in ("append", "manifestWrite", "statusWrite", "manifestRename", "statusRename")},
                  "timing": {}, "enqueue": {}, "eventLoop": {"delay": {"arm": {}}, "utilization": {}}}
    for key, members in containers.items():
        visit(key, sample[key], members)
    visit("cpu.total", sample["cpu"]["total"], {})
    phases = sample["cpu"]["phases"]
    require([row["phase"] for row in phases] == sample["samplingProtocol"]["cpuPhases"], "missing/duplicate CPU phase")
    for row in phases:
        visit(f"cpu.phases.{row['phase']}", {key: value for key, value in row.items() if key != "phase"}, {})
    visit("flush.summary", sample["flush"]["summary"], {})
    require(sample["flush"]["summary"]["count"] == len(sample["flush"]["calls"]), "flush call count mismatch")
    for field in ("userUs", "systemUs"):
        values = [metric_value(row[field], f"flush.calls.{index}.{field}") for index, row in enumerate(sample["flush"]["calls"])]
        visit(f"flush.total.{field}", sum(values) if all(value is not None for value in values) else None)
    rounds = sample["rounds"]
    require([row["round"] for row in rounds] == list(range(sample["workload"].get("rounds", 0))), "missing/duplicate load round")
    for row in rounds:
        visit(f"rounds.{row['round']}", row, {})
    round_memory = [row for row in sample["memory"]["samples"] if row["phase"] == "after-round-flush"]
    require(len(round_memory) == len(rounds), "round memory sample count mismatch")
    for field in ("rss", "heapTotal", "heapUsed", "external", "arrayBuffers"):
        for phase in ("baseline", "afterCloseGC", "sampledMax"):
            visit(f"memory.{phase}.{field}", sample["memory"][phase][field])
        baseline = sample["memory"]["baseline"][field]
        for phase in ("sampledMax", "afterCloseGC"):
            value = sample["memory"][phase][field]
            visit(f"memory.{phase}Delta.{field}", value - baseline if value is not None and baseline is not None else None)
        for index, row in enumerate(round_memory):
            visit(f"memory.rounds.{index}.{field}", row[field])
    return result


def stats(values):
    available = [value for value in values if value is not None]
    return {"count": len(available), "median": statistics.median(available) if available else None,
            "min": min(available) if available else None, "max": max(available) if available else None}


def compare(baseline_path, candidate_path):
    sources = Sources()
    baseline_path = Path(baseline_path).resolve(strict=True)
    candidate_path = Path(candidate_path).resolve(strict=True)
    baseline, baseline_source, before = load_measurement(baseline_path, sources)
    candidate, candidate_source, after = load_measurement(candidate_path, sources)
    for field in ("repeats", "scenarios", "samplingProtocol", "environment"):
        require(baseline[field] == candidate[field], f"comparison {field} mismatch")
    for group in ("inspector", "measurement"):
        require(baseline_source[group] == candidate_source[group], f"comparison {group} source mismatch")
    pairs = []
    for scenario in baseline["scenarios"]:
        for repeat in range(1, baseline["repeats"] + 1):
            key = (scenario, repeat)
            left, right = before[key], after[key]
            for field in ("workload", "workloadFingerprint", "inputSha256", "limits", "accepted", "rejected", "totals", "errors", "closeRejected"):
                require(left[field] == right[field], f"{scenario} #{repeat}: {field} mismatch")
            left_evidence, left_inspection = normalize_artifacts(left, baseline_path.parent, sources)
            right_evidence, right_inspection = normalize_artifacts(right, candidate_path.parent, sources)
            require(left_evidence["normalizedFilesSha256"] == right_evidence["normalizedFilesSha256"], f"{scenario} #{repeat}: normalized file content mismatch")
            require(left_inspection == right_inspection, f"{scenario} #{repeat}: normalized inspection mismatch")
            left_metrics, right_metrics = flatten_metrics(left), flatten_metrics(right)
            require(left_metrics.keys() == right_metrics.keys(), f"{scenario} #{repeat}: metric fields mismatch")
            metrics = {}
            for name, old in left_metrics.items():
                new = right_metrics[name]
                delta = metric_value(new - old if new is not None and old is not None else None, f"{name}.delta")
                metrics[name] = {"baseline": old, "candidate": new, "delta": delta,
                                 "percentChange": metric_value(delta / old * 100 if delta is not None and old != 0 else None,
                                                               f"{name}.percentChange")}
            changed = [{"file": old["file"], "baselineSha256": old["sha256"], "candidateSha256": new["sha256"]}
                       for old, new in zip(left_evidence["files"], right_evidence["files"])
                       if old["sha256"] != new["sha256"]]
            pairs.append({"scenario": scenario, "repeat": repeat, "countsErrorsAndCloseMatch": True,
                          "normalizedFilesMatch": True, "normalizedInspectionMatch": True,
                          "rawFileHashDifferences": changed, "rawBytesIdentical": not changed, "metrics": metrics})
    aggregates = []
    for scenario in baseline["scenarios"]:
        rows = [row for row in pairs if row["scenario"] == scenario]
        metrics = {name: {side: stats([row["metrics"][name][side] for row in rows])
                          for side in ("baseline", "candidate", "delta", "percentChange")} for name in rows[0]["metrics"]}
        aggregates.append({"scenario": scenario, "pairs": len(rows), "metrics": metrics})
    old_sources = {row["name"]: row["sha256"] for row in baseline_source["recorder"]["files"]}
    new_sources = {row["name"]: row["sha256"] for row in candidate_source["recorder"]["files"]}
    recorder_changes = [{"file": name, "baselineSha256": old_sources.get(name), "candidateSha256": new_sources.get(name)}
                        for name in sorted(old_sources.keys() | new_sources.keys()) if old_sources.get(name) != new_sources.get(name)]
    sources.verify_unchanged()
    result = {"recorderResourceComparisonFormatVersion": 1, "status": "completed", "source": "synthetic", "modelCalled": False,
              "createdAt": datetime.now(timezone.utc).isoformat(), "baseline": {"path": str(baseline_path), "sha256": sources.hashes[baseline_path]},
              "candidate": {"path": str(candidate_path), "sha256": sources.hashes[candidate_path]},
              "environment": baseline["environment"], "samplingProtocol": baseline["samplingProtocol"],
              "provenance": {"baseline": baseline_source, "candidate": candidate_source},
              "recorderSourceChanged": baseline_source["recorder"] != candidate_source["recorder"],
              "recorderSourceDifferences": recorder_changes,
              "deltaDefinition": "candidate - baseline", "percentChangeDefinition": "100 * delta / baseline; null for zero/missing baseline",
              "pairs": pairs, "scenarios": aggregates, "sourceFilesChecked": len(sources.hashes), "sourceBytesUnchanged": True,
              "limitations": ["Descriptive paired samples only; no significance test or causal performance claim.",
                              "UUIDs, generated timestamps and verified trace-derived hashes are normalized; raw files may differ.",
                              "No event-loop samples or zero baseline denominators produce null values.",
                              "Memory maxima are sampled values, not true process peaks; instrumentation and filesystem effects remain."]}
    return result, sources


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        require(not args.output.exists() and not args.output.is_symlink(), "output already exists")
        result, sources = compare(args.baseline, args.candidate)
        output = args.output.resolve()
        require(output not in sources.hashes and not any(output.is_relative_to(path) for path in sources.directories),
                "output must be outside recorder artifact directories")
        data = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        sources.verify_unchanged()
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
        print(f"Compared {len(result['pairs'])} completed pairs: {output}")
        return 0
    except (ComparisonError, OSError, KeyError, TypeError, ValueError) as error:
        print(f"Recorder resource comparison rejected: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
