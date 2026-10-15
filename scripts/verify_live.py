"""Validate only the M2.3 controlled fixtures; reuse Node inspect for recording validity."""
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text_of(message):
    return "".join(block.get("text", "") for block in message.get("content", []) if block.get("type") == "text")


def check_task_events(events, mode, expected_value):
    ends = [event for event in events if event["type"] == "turn/end"]
    require(ends, "No durable turn/end")
    reason = ends[-1]["data"]["reason"]
    if mode == "cancel":
        require(reason == {"kind": "aborted", "reason": {"kind": "user"}}, "Not a user cancellation")
        return {"turnEndReason": reason}
    require(reason.get("kind") == "completed", "Task did not complete")
    target = "missing-m2-3.txt" if mode == "missing" else "README.md"
    users = [event for event in events if event["type"] == "user/message"
             and event["data"].get("source", {}).get("kind") == "user"
             and target in text_of(event["data"])]
    require(users, "No matching user input")
    interval = [event for event in events if users[-1]["seq"] < event["seq"] < ends[-1]["seq"]]
    answers = [event for event in interval if event["type"] == "assistant/message"
               and text_of(event["data"]["message"])]
    require(answers, "No assistant answer after input")
    final = answers[-1]
    answer = text_of(final["data"]["message"])
    if mode == "missing":
        require(target in answer and re.search(r"not (?:exist|found)|doesn't exist|cannot (?:find|read)", answer, re.I),
                "Answer does not report the missing file")
    else:
        require(answer.strip() == expected_value, "Wrong projectName answer")
    calls = {event["data"]["callId"]: event for event in interval if event["type"] == "tool/call"}
    for event in interval:
        if event["type"] != "tool/result" or event["seq"] >= final["seq"]:
            continue
        message = event["data"]["message"]
        call = calls.get(message.get("toolCallId"))
        if not call or call["seq"] >= event["seq"]:
            continue
        arguments = json.loads(call["data"]["arguments"] or "{}")
        if not isinstance(arguments, dict) or not any(
            isinstance(value, str) and value.replace("\\", "/").split("/")[-1] == target
            for value in arguments.values()
        ):
            continue
        evidence = message.get("isError") is True if mode == "missing" else (
            message.get("isError") is False and f"projectName: {expected_value}" in text_of(message))
        if evidence:
            return {"toolName": call["data"]["name"], "callSeq": call["seq"], "resultSeq": event["seq"],
                    "answerSeq": final["seq"], "turnEndReason": reason}
    raise ValueError("No matching tool call/result before the answer")


def verify_launch(directory):
    directory = Path(directory).resolve()
    report = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    require(report.get("resultFormatVersion") == 1, "Unsupported live result format")
    mode = report["mode"]
    require(mode in {"read", "missing", "web", "cancel", "kill"}, "Unsupported mode")
    require(report.get("inspections"), "No run evidence")
    fresh = []
    for saved in report["inspections"]:
        inspected = subprocess.run(["node", str(ROOT / "scripts" / "inspect.js"), "--run", saved["runDir"]],
                                   capture_output=True, text=True, encoding="utf-8", timeout=30)
        result = json.loads(inspected.stdout)
        require(inspected.returncode == result["exitCode"], "inspect process/report disagree")
        require(result["sessions"], "No recorded sessions")
        fresh.append((Path(saved["runDir"]), result))
    codes = [result["exitCode"] for _, result in fresh]
    if mode == "kill":
        require(report["signal"] == "SIGKILL" and report["intervention"] == "force-stop-after-stream-chunk",
                "No forced-stop evidence")
        require(all(code in (1, 2) for code in codes), "Force-stopped recording was accepted as complete")
        return {"mode": mode, "verified": True, "recordingExitCodes": codes}
    require(report["exitCode"] == (1 if mode == "cancel" else 0), "Unexpected Harness exit code")
    require(all(code == 0 for code in codes), "Recording did not pass fresh inspect")
    if mode == "cancel":
        require(report["intervention"] == "agent-cancel-after-stream-chunk", "No live cancellation evidence")
    fixture = (ROOT / "fixtures" / "live-read" / "README.md").read_text(encoding="utf-8")
    expected_value = re.search(r"^projectName: (.+)$", fixture, re.M).group(1)
    sessions = [(run_dir, session) for run_dir, result in fresh for session in result["sessions"]]
    require(len(sessions) == 1, "This fixture check expects exactly one session")
    run_dir, session = sessions[0]
    events = [json.loads(line)["event"] for line in (run_dir / session["traceFile"]).read_text(encoding="utf-8").splitlines()]
    evidence = check_task_events(events, mode, expected_value)
    if mode != "web":
        frames = [json.loads(line) for line in (directory / "stdout.jsonl").read_text(encoding="utf-8").splitlines()]
        require(frames[0].get("type") == "session" and frames[0].get("sessionId") == session["sessionId"],
                "Headless stream/session mismatch")
        require(frames[-1].get("type") == "final", "No headless final frame")
        if mode == "read":
            require(frames[-1].get("text", "").strip() == expected_value, "Wrong headless final answer")
    return {"mode": mode, "verified": True, "recordingExitCodes": codes, "taskEvidence": evidence}


if __name__ == "__main__":
    try:
        require(len(sys.argv) == 2, "Usage: python scripts/verify_live.py <launch-directory>")
        print(json.dumps(verify_launch(sys.argv[1]), ensure_ascii=False))
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"verified": False, "error": str(error)}, ensure_ascii=False))
        sys.exit(1)
