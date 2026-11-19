"""Compare two assertion sets by re-evaluating the same stable task archive."""
import hashlib
from pathlib import Path

from .environment import snapshot_digest
from .evaluate import evaluate
from .formats import parse_json, require, validate_case, validate_evidence


def _contained(directory, path):
    resolved = (directory / path).resolve()
    require(resolved.is_relative_to(directory), "Comparison input escapes the evidence directory")
    return resolved


class _NotAnInputFile(ValueError):
    pass


def _file_digest(path):
    if not path.exists():
        return None
    if not path.is_file():
        raise _NotAnInputFile(f"Expected a comparison input file: {path.name}")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _read_input(path, hashes):
    data = path.read_bytes()
    hashes[str(path)] = hashlib.sha256(data).hexdigest()
    return parse_json(data.decode("utf-8"))


def _source_state(evidence_path, case_paths, evidence, *, file_digest=_file_digest):
    directory = evidence_path.parent
    files = [evidence_path, *case_paths]
    if "runtimeReport" in evidence:
        files.append(_contained(directory, evidence["runtimeReport"]))
    if evidence["runDir"] is not None:
        run_dir = _contained(directory, evidence["runDir"])
        files.append(_contained(directory, run_dir / "run.json"))
        if run_dir.is_dir():
            # The inspector reads a flat run manifest, traces and statuses and
            # checks for pending state files. Never traverse the host/workspace.
            files.extend(_contained(directory, path) for path in run_dir.iterdir()
                         if path.name.endswith((".jsonl", ".status.json", ".tmp")))
    return {str(path): file_digest(path) for path in files}


def _side(case_path, case, evaluation):
    return {"casePath": str(case_path), "caseSha256": snapshot_digest(case),
            "assertionsSha256": snapshot_digest(case["assertions"]), "outcome": evaluation["outcome"],
            "assertionOutcome": evaluation["assertions"]["outcome"],
            "assertionReason": evaluation["assertions"].get("reason"),
            "recordingReasons": evaluation["recording"]["reasons"],
            "executionStatus": evaluation["execution"]["status"], "recordingOutcome": evaluation["recording"]["outcome"]}


def _indexed_rows(evaluation):
    results = {row["id"]: row for row in evaluation["assertions"]["results"]}
    return {rule["id"]: {"position": index, "definition": rule, "result": results[rule["id"]]}
            for index, rule in enumerate(evaluation["case"]["assertions"], 1)}


def compare_assertions(evidence_path, candidate_case_path):
    """Return a read-only comparison; the original rules come from sibling case.json."""
    evidence_path = Path(evidence_path).resolve()
    baseline_path = _contained(evidence_path.parent, "case.json")
    candidate_path = Path(candidate_case_path).resolve()
    input_hashes = {}
    baseline = validate_case(_read_input(baseline_path, input_hashes))
    candidate = validate_case(_read_input(candidate_path, input_hashes))
    evidence = validate_evidence(_read_input(evidence_path, input_hashes), baseline)
    fixed_input = {key: value for key, value in baseline.items() if key != "assertions"}
    require(snapshot_digest(fixed_input) == snapshot_digest({key: value for key, value in candidate.items()
                                                             if key != "assertions"}),
            "Only assertions may differ between the frozen and candidate cases")

    paths = (baseline_path, candidate_path)
    before = _source_state(evidence_path, paths, evidence)
    require(all(before[path] == digest for path, digest in input_hashes.items()), "Comparison inputs changed")
    evaluations = []
    for path, case in zip(paths, (baseline, candidate)):
        result = evaluate(path, evidence_path)
        require(snapshot_digest(result["case"]) == snapshot_digest(case)
                and result["caseRunId"] == evidence["caseRunId"] and result["source"] == evidence["source"]
                and result["association"]["runId"] == evidence["runId"]
                and result["association"]["sessionId"] == evidence["sessionId"],
                "Comparison case or evidence identity changed")
        require(_source_state(evidence_path, paths, evidence) == before, "Comparison source files changed")
        evaluations.append(result)
    original, revised = evaluations
    for key in ("recording", "execution", "metrics", "configuration", "budgetEnforcement"):
        require(snapshot_digest(original[key]) == snapshot_digest(revised[key]),
                f"Comparison evidence differs between evaluations: {key}")

    left, right = _indexed_rows(original), _indexed_rows(revised)
    rows = []
    for identifier in dict.fromkeys([*left, *right]):
        a, b = left.get(identifier), right.get(identifier)
        missing = a is None or b is None
        rows.append({"id": identifier, "baseline": a, "candidate": b,
                     "ruleChanged": missing or snapshot_digest(a["definition"]) != snapshot_digest(b["definition"]),
                     "outcomeChanged": missing or a["result"]["outcome"] != b["result"]["outcome"],
                     "resultChanged": missing or snapshot_digest(a["result"]) != snapshot_digest(b["result"]),
                     "positionChanged": not missing and a["position"] != b["position"]})
    scored = all(item["outcome"] in ("passed", "failed") for item in evaluations)
    changed_ids = [row["id"] for row in rows if row["ruleChanged"] or row["resultChanged"] or row["positionChanged"]]
    return {"assertionComparisonFormatVersion": 1, "modelCalled": False, "status": "compared" if scored else "inconclusive",
            "exitCode": 0 if scored else 2, "caseId": baseline["caseId"], "caseRunId": evidence["caseRunId"],
            "runId": evidence["runId"], "sessionId": evidence["sessionId"], "source": evidence["source"],
            **({"batchId": evidence["batchId"]} if "batchId" in evidence else {}),
            "evidencePath": str(evidence_path), "baseline": _side(baseline_path, baseline, original),
            "candidate": _side(candidate_path, candidate, revised),
            "summary": {"taskOutcomeChanged": original["outcome"] != revised["outcome"], "changedAssertionIds": changed_ids},
            "assertions": rows}
