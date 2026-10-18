"""Read stable recordings, then evaluate a single task's linked evidence."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from .formats import load_json, parse_json, require, validate_case, validate_evidence

ROOT = Path(__file__).resolve().parents[1]
KNOWN = {"user/message", "assistant/message", "tool/call", "tool/result", "turn/end"}


def inspect_recording(run_dir):
    try:
        process = subprocess.run(["node", str(ROOT / "scripts" / "inspect.js"), "--run", str(run_dir)],
                                 capture_output=True, text=True, encoding="utf-8", timeout=30)
        report = parse_json(process.stdout)
        require(isinstance(report, dict) and report.get("outcome") in ("complete", "invalid", "unverified"), "Invalid inspect report")
        require(process.returncode == report.get("exitCode") == {"complete": 0, "invalid": 1, "unverified": 2}[report["outcome"]],
                "inspect process/report disagree")
        require(isinstance(report.get("sessions"), list), "Missing inspect sessions")
        return {"outcome": report["outcome"], "reasons": report.get("reasons", []), "inspection": report}
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return {"outcome": "unverified", "reasons": [f"Cannot inspect recording: {error}"]}


def text_of(message):
    require(isinstance(message, dict) and isinstance(message.get("content"), list), "Missing message content")
    parts = []
    for block in message["content"]:
        require(isinstance(block, dict), "Malformed content block")
        if block.get("type") == "text":
            require(isinstance(block.get("text"), str), "Malformed text block")
            parts.append(block["text"])
    return "".join(parts)


def task_view(events, task_input):
    for event in events:
        if event.get("type") in KNOWN:
            require(isinstance(event.get("data"), dict), "Malformed known event data")
    users = [event for event in events if event.get("type") == "user/message"
             and event["data"].get("source", {}).get("kind") == "user"]
    require(len(users) == 1 and text_of(users[0]["data"]) == task_input, "Expected exactly one matching user task")
    ends = [event for event in events if event.get("type") == "turn/end"]
    require(len(ends) == 1 and ends[0]["seq"] > users[0]["seq"], "Expected one turn/end after input")
    end = ends[0]
    require(all(users[0]["seq"] < event["seq"] < end["seq"] for event in events
                if event.get("type") in ("assistant/message", "tool/call", "tool/result")),
            "Message/tool evidence outside the single task boundaries")
    interval = [event for event in events if users[0]["seq"] <= event["seq"] <= end["seq"]]
    require(all(right["seq"] == left["seq"] + 1 for left, right in zip(interval, interval[1:])), "Sequence gap in task evidence")
    answers = [event for event in interval if event.get("type") == "assistant/message" and text_of(event["data"].get("message"))]
    require(answers, "No final assistant text before turn/end")
    final = answers[-1]
    calls, results = {}, {}
    for event in interval:
        if event.get("type") == "tool/call":
            data = event["data"]
            call_id = data.get("callId")
            require(isinstance(call_id, str) and call_id and call_id not in calls, "Missing or duplicate callId")
            require(isinstance(data.get("name"), str) and data["name"], "Missing tool name")
            require(isinstance(data.get("arguments"), str), "Tool arguments must be JSON text")
            arguments = parse_json(data["arguments"])
            require(isinstance(arguments, dict), "Tool arguments must decode to an object")
            calls[call_id] = (event, arguments)
        elif event.get("type") == "tool/result":
            message = event["data"].get("message")
            require(isinstance(message, dict), "Missing tool result message")
            call_id = message.get("toolCallId")
            require(isinstance(call_id, str) and call_id in calls and call_id not in results, "Orphan, reversed or duplicate tool result")
            require(type(message.get("isError")) is bool, "Missing boolean isError")
            text_of(message)
            results[call_id] = event
    return {"end": end, "final": final, "calls": calls, "results": results}


def _same(left, right):
    # Python's True == 1 must not make an argument match.
    return json.dumps(left, sort_keys=True, ensure_ascii=False) == json.dumps(right, sort_keys=True, ensure_ascii=False)


def check_assertion(assertion, view):
    base = {"id": assertion["id"], "type": assertion["type"]}
    kind = assertion["type"]
    if kind == "final_text":
        actual = text_of(view["final"]["data"]["message"]).strip()
        return {**base, "outcome": "passed" if actual == assertion["equals"] else "failed",
                "actual": actual, "evidence": {"answerSeq": view["final"]["seq"]}}
    if kind == "turn_end":
        actual = view["end"]["data"].get("reason")
        return {**base, "outcome": "passed" if _same(actual, assertion["reason"]) else "failed",
                "actual": actual, "evidence": {"endSeq": view["end"]["seq"]}}
    mismatches = []
    for call_id, (call, arguments) in view["calls"].items():
        if call["data"]["name"] != assertion["tool"] or not all(
                key in arguments and _same(arguments[key], value) for key, value in assertion["arguments"].items()):
            continue
        result = view["results"].get(call_id)
        if result is None or result["seq"] >= view["final"]["seq"]:
            continue
        message = result["data"]["message"]
        evidence = {"callId": call_id, "callSeq": call["seq"], "resultSeq": result["seq"], "answerSeq": view["final"]["seq"]}
        expected = assertion["result"]
        if message["isError"] is expected["isError"] and ("textContains" not in expected or expected["textContains"] in text_of(message)):
            return {**base, "outcome": "passed", "evidence": evidence}
        mismatches.append(evidence)
    if mismatches:
        return {**base, "outcome": "failed", "reason": "Linked tool results did not match", "evidence": mismatches}
    return {**base, "outcome": "insufficient_evidence", "reason": "No matching call/result before final answer"}


def evaluate(case_path, evidence_path):
    case_path, evidence_path = Path(case_path).resolve(), Path(evidence_path).resolve()
    case = validate_case(load_json(case_path))
    evidence = validate_evidence(load_json(evidence_path), case)
    run_dir = (evidence_path.parent / evidence["runDir"]).resolve() if evidence["runDir"] is not None else None
    recording = (inspect_recording(run_dir) if run_dir else
                 {"outcome": "unverified", "reasons": ["No recorder run was observed"]})
    execution = {**evidence["execution"], "reportedStatus": evidence["execution"]["status"]}
    rows = [{"id": item["id"], "type": item["type"], "outcome": "not_run"} for item in case["assertions"]]
    assertions = {"outcome": "not_run", "results": rows}
    result = {"evaluationFormatVersion": evidence["evidenceFormatVersion"], "evaluatedAt": datetime.now(timezone.utc).isoformat(),
              "caseRunId": evidence["caseRunId"], "caseId": case["caseId"], "case": case,
              "source": evidence["source"], "configuration": evidence["configuration"],
              "budgetEnforcement": evidence["budgetEnforcement"],
              "association": {"runId": evidence["runId"], "sessionId": evidence["sessionId"], "runDir": str(run_dir) if run_dir else None,
                              "casePath": str(case_path), "evidencePath": str(evidence_path)},
              "execution": execution, "recording": recording, "assertions": assertions, "outcome": "unevaluable"}
    if "batchId" in evidence:
        result["batchId"] = evidence["batchId"]
    if "runtimeReport" in evidence:
        result["association"]["runtimeReport"] = str((evidence_path.parent / evidence["runtimeReport"]).resolve())
    if recording["outcome"] != "complete":
        return result
    try:
        manifest = load_json(run_dir / "run.json")
        sessions = recording["inspection"]["sessions"]
        require(manifest["runId"] == evidence["runId"] and len(sessions) == 1
                and sessions[0].get("sessionId") == evidence["sessionId"], "Recording association mismatch; expected one session")
        if evidence["configuration"] is not None:
            require(manifest.get("pluginVersion") == evidence["configuration"]["pluginVersion"], "Recorded plugin version/configuration mismatch")
        session = sessions[0]
        with (run_dir / session["traceFile"]).open(encoding="utf-8") as stream:
            events = [parse_json(line)["event"] for line in stream]
    except (OSError, ValueError, KeyError, TypeError) as error:
        recording.update(outcome="unverified", reasons=[*recording["reasons"], str(error)])
        return result
    try:
        ends = [event for event in events if event.get("type") == "turn/end"]
        end_reason = ends[0].get("data", {}).get("reason") if len(ends) == 1 else None
        execution["turnEndReason"] = end_reason
        if execution["status"] == "completed" and (not isinstance(end_reason, dict)
                or end_reason.get("kind") != "completed" or execution.get("exitCode") not in (None, 0)
                or execution.get("signal") is not None):
            execution.update(status="unknown", reason="Completed execution conflicts with end/exit evidence")
        if execution["status"] == "cancelled" and end_reason != {"kind": "aborted", "reason": {"kind": "user"}}:
            execution.update(status="unknown", reason="User cancellation lacks matching end evidence")
        if execution["status"] != "completed":
            return result
        # Preserve unknown event types; only interpret the documented task events.
        view = task_view(events, case["input"])
        require(evidence["configuration"] == case["configRef"], "Actual configuration differs from case configRef")
        if evidence["evidenceFormatVersion"] == 2 and evidence["source"] == "live":
            headers = [event["data"]["header"]["config"] for event in events if event.get("type") == "request/header"]
            require(headers and all(header.get("provider") == evidence["configuration"]["provider"]
                                    and header.get("model") == evidence["configuration"]["model"] for header in headers),
                    "Actual request routes do not match the evidence configuration")
        rows[:] = [check_assertion(item, view) for item in case["assertions"]]
        outcomes = {row["outcome"] for row in rows}
        assertions["outcome"] = ("insufficient_evidence" if "insufficient_evidence" in outcomes
                                 else "failed" if "failed" in outcomes else "passed")
        if assertions["outcome"] in ("passed", "failed"):
            result["outcome"] = assertions["outcome"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        assertions.update(outcome="insufficient_evidence", reason=str(error))
        for row in rows:
            row.update(outcome="insufficient_evidence", reason=str(error))
    return result
