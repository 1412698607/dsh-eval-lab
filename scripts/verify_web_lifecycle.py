"""M6.4 first-stage verifier: synthetic lifecycle captures, never live Web acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from uuid import UUID

from dsh_eval.evaluate import check_assertions, inspect_recording, task_view, text_of
from dsh_eval.formats import fields, load_json, nonempty, parse_json, require, validate_case

SCENARIOS = {"page-cancel", "normal-exit", "process-interrupt"}


def check_events(events, case, scenario, after_seq, *, allow_unconfirmed_tail=False):
    require(events and all(isinstance(event, dict) and type(event.get("seq")) is int
                           and event["seq"] >= 0 for event in events), "Missing or malformed event sequence")
    require(all(right["seq"] == left["seq"] + 1 for left, right in zip(events, events[1:])),
            "Sequence gap or reversed events")
    messages = [event for event in events if event.get("type") == "user/message"]
    require(all(nonempty(event.get("data", {}).get("source", {}).get("kind")) for event in messages),
            "Malformed user/message source")
    users = [event for event in messages if event["data"]["source"]["kind"] == "user"]
    starts = [event for event in events if event.get("type") == "turn/start"]
    require(len(users) == len(starts) == 1 and starts[0]["seq"] < users[0]["seq"],
            "Expected one started task and one user input")
    user = users[0]
    require(user.get("data", {}).get("source", {}).get("kind") == "user"
            and text_of(user["data"]) == case["input"], "Task input mismatch")
    ends = [event for event in events if event.get("type") == "turn/end"]
    require(type(after_seq) is int and user["seq"] <= after_seq <= events[-1]["seq"],
            "Operation checkpoint outside task evidence")
    if scenario == "process-interrupt":
        require(not ends and (allow_unconfirmed_tail or after_seq == events[-1]["seq"]),
                "Interruption was not inside an unfinished task")
        return {"execution": {"status": "interrupted"}, "assertions": {"outcome": "not_run"}, "outcome": "unevaluable"}
    require(len(ends) == 1 and ends[0]["seq"] > user["seq"], "Expected one turn/end after input")
    end = ends[0]
    require(all(user["seq"] < event["seq"] < end["seq"] for event in events
                if event.get("type") in ("assistant/message", "tool/call", "tool/result")),
            "Message or tool evidence outside the task")
    reason = end.get("data", {}).get("reason")
    if scenario == "page-cancel":
        require(after_seq < end["seq"] and reason == {"kind": "aborted", "reason": {"kind": "user"}},
                "No user cancellation after the operation checkpoint")
        return {"execution": {"status": "cancelled", "turnEndReason": reason},
                "assertions": {"outcome": "not_run"}, "outcome": "unevaluable"}
    require(reason == {"kind": "completed"} and after_seq >= end["seq"],
            "Normal exit did not follow task completion")
    rows = check_assertions(case["assertions"], task_view(events, case["input"]))
    outcomes = {row["outcome"] for row in rows}
    assertions = "insufficient_evidence" if "insufficient_evidence" in outcomes else "failed" if "failed" in outcomes else "passed"
    return {"execution": {"status": "completed", "turnEndReason": reason},
            "assertions": {"outcome": assertions, "results": rows},
            "outcome": "unevaluable" if assertions == "insufficient_evidence" else assertions}


def validate_capture(capture):
    fields(capture, ("webLifecycleFormatVersion", "source", "scenario", "runId", "sessionId", "runDir", "operation", "process"))
    require(type(capture["webLifecycleFormatVersion"]) is int and capture["webLifecycleFormatVersion"] == 1,
            "Unsupported Web lifecycle capture version")
    # Live collection has a separate protocol/verifier. A source label cannot promote this fixture.
    require(capture["source"] == "synthetic", "This first-stage verifier accepts synthetic captures only")
    require(capture["scenario"] in SCENARIOS, "Unknown lifecycle scenario")
    process = capture["process"]
    fields(process, ("pid", "closed", "exitCode", "signal", "forceStopped", "intervention", "error"))
    require(process["error"] is None, f"Process capture error: {process['error']}")
    require(type(process["pid"]) is int and process["pid"] > 0 and process["closed"] is True,
            "Owned child process was not observed closed")
    require(type(process["forceStopped"]) is bool, "Missing force-stop fact")
    require(process["intervention"] in (None, "expected-interrupt"), f"Unexpected intervention: {process['intervention']}")
    run_id = capture["runId"]
    require(nonempty(run_id) and str(UUID(run_id)) == run_id and nonempty(capture["sessionId"]), "Missing run/session identity")
    require(capture["runDir"] == f"traces/{run_id}", "runDir must name this capture's relative trace directory")
    operation = capture["operation"]
    fields(operation, ("kind", "afterSeq", "signal"))
    require(type(operation["afterSeq"]) is int and operation["afterSeq"] >= 0, "Invalid operation checkpoint")
    if capture["scenario"] == "process-interrupt":
        require(operation["kind"] == "process-kill" and operation["signal"] == process["signal"] == "SIGKILL"
                and process["exitCode"] is None and process["forceStopped"] is True
                and process["intervention"] == "expected-interrupt", "No expected owned-process interruption")
    else:
        expected = "synthetic-cancel" if capture["scenario"] == "page-cancel" else "fixture-exit"
        require(operation["kind"] == expected and operation["signal"] is None
                and type(process["exitCode"]) is int and process["exitCode"] == 0
                and process["signal"] is None and process["forceStopped"] is False
                and process["intervention"] is None, "Unexpected exit, timeout, fallback or operation kind")
    return capture


def verify_recorded_task(directory, capture, case, result, *, allow_unconfirmed_tail=False):
    require(case["configRef"]["profile"] == "web", "Expected a frozen Web case")
    run_dir = directory / capture["runDir"]
    require(run_dir.resolve().is_relative_to(directory), "Trace directory escapes the capture")
    result["process"] = capture["process"]
    recording = result["recording"] = inspect_recording(run_dir)
    inspection = recording.get("inspection")
    require(isinstance(inspection, dict), "Fresh inspect unavailable; absence is not interruption evidence")
    manifest = load_json(run_dir / "run.json")
    require(all(type(manifest.get(key)) is int and manifest[key] == version for key, version in
                (("formatVersion", 2), ("statusFormatVersion", 1), ("runManifestFormatVersion", 1))),
            "Unsupported recording metadata version")
    require(manifest.get("runId") == capture["runId"]
            and manifest.get("pluginVersion") == case["configRef"]["pluginVersion"], "Run identity/version mismatch")
    sessions = inspection["sessions"]
    require(len(sessions) == 1 and sessions[0].get("sessionId") == capture["sessionId"], "Expected one associated session")
    trace_file = hashlib.sha256(capture["sessionId"].encode("utf-8")).hexdigest() + ".jsonl"
    require(sessions[0].get("traceFile") == trace_file, "Trace association mismatch")
    interrupted = capture["scenario"] == "process-interrupt"
    require(recording["outcome"] == ("unverified" if interrupted else "complete"),
            "Recording is not the expected open prefix or complete sealed capture")
    require(inspection.get("runManifest", {}).get("state") == ("recording" if interrupted else "sealed")
            and sessions[0].get("state") == ("recording" if interrupted else "sealed"), "Unexpected run/session state")
    if interrupted:
        inventory = inspection["runManifest"]
        require(inventory.get("outcome") == sessions[0].get("outcome") == "unverified"
                and inspection.get("reasons") == inventory.get("reasons"),
                "Interruption inspect has uncertainty beyond an open recording")
        status = load_json(run_dir / trace_file.replace(".jsonl", ".status.json"))
        require(type(status.get("statusFormatVersion")) is int and status["statusFormatVersion"] == 1,
                "Unsupported interruption checkpoint version")
        # Both policies require a real nonempty checkpoint covering the operation. Live
        # observation permits later valid bytes; the synthetic fixture writes nothing later.
        require(type(status.get("lastSeq")) is int and status["lastSeq"] >= capture["operation"]["afterSeq"]
                and status["writtenCount"] > 0 and type(sessions[0].get("lastSeq")) is int
                and (allow_unconfirmed_tail or all(status.get(key) == sessions[0].get(key) for key in
                     ("writtenCount", "writtenBytes", "firstSeq", "lastSeq", "sha256"))),
                "Saved checkpoint does not cover the interruption operation")
    rows = [parse_json(line) for line in (run_dir / trace_file).read_text(encoding="utf-8").splitlines()]
    require(rows and all(row.get("runId") == capture["runId"] and row.get("sessionId") == capture["sessionId"] for row in rows),
            "Recorded row identity mismatch")
    events = [row["event"] for row in rows]
    task = check_events(events, case, capture["scenario"], capture["operation"]["afterSeq"],
                        allow_unconfirmed_tail=allow_unconfirmed_tail)
    result.update(task)
    require(interrupted or capture["scenario"] == "page-cancel" or task["assertions"]["outcome"] == "passed",
            "Completed task assertions did not pass")
    return events


def verify_launch(directory):
    directory = Path(directory).resolve()
    result = {"webLifecycleVerificationVersion": 1, "scope": "synthetic-process-check", "source": None,
              "scenario": None, "verified": False, "liveWebVerified": False,
              "execution": {"status": "unknown"}, "recording": {"outcome": "unverified"},
              "assertions": {"outcome": "not_run"}, "outcome": "unevaluable", "reasons": []}
    try:
        capture = load_json(directory / "lifecycle.json")
        require(isinstance(capture, dict), "Lifecycle capture must be an object")
        result.update(source=capture.get("source"), scenario=capture.get("scenario"), process=capture.get("process"))
        validate_capture(capture)
        case = validate_case(load_json(directory / "case.json"))
        verify_recorded_task(directory, capture, case, result)
        result["verified"] = True
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        result["reasons"].append(str(error))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="One explicit lifecycle capture directory")
    parser.add_argument("--output", type=Path, help="Write a new verification JSON without overwriting")
    args = parser.parse_args(argv)
    result = verify_launch(args.directory)
    try:
        encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
        print(encoded, end="")
        return 0 if result["verified"] else 1
    except OSError as error:
        print(json.dumps({"verified": False, "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
