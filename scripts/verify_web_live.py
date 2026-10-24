"""Verify explicitly collected live Web actions, actual model stream and owned console exit."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from uuid import UUID

from dsh_eval.formats import fields, load_json, nonempty, parse_json, require, validate_case
from dsh_eval.metrics import empty_metrics, recording_metrics
from .verify_web_lifecycle import SCENARIOS, verify_recorded_task


def timestamp(value):
    require(nonempty(value), "Missing observation timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.utcoffset() is not None, "Timestamp needs a timezone")
    return result


def validate_live(capture, observations, ui):
    fields(capture, ("liveWebLifecycleFormatVersion", "source", "scenario", "runId", "sessionId", "runDir",
                     "operation", "platform", "cliVersion", "nodePtyVersion", "process", "startedAt", "finishedAt", "url"))
    require(type(capture["liveWebLifecycleFormatVersion"]) is int and capture["liveWebLifecycleFormatVersion"] == 1
            and capture["source"] == "live", "Expected an explicit live Web capture version 1")
    require(capture["scenario"] in SCENARIOS and capture["platform"] == "win32", "Unsupported live scenario/platform")
    require(capture["cliVersion"] == "0.2.0-rc.2" and nonempty(capture["nodePtyVersion"]), "Unsupported host version")
    run_id = capture["runId"]
    require(nonempty(run_id) and str(UUID(run_id)) == run_id and nonempty(capture["sessionId"]), "Invalid live identity")
    require(capture["runDir"] == f"traces/{run_id}", "Live trace directory mismatch")
    from urllib.parse import urlparse
    url = urlparse(capture["url"])
    require(url.scheme == "http" and url.hostname == "127.0.0.1" and url.port
            and not url.query and not url.fragment and not url.username, "Expected a clean owned loopback URL")
    started, finished = timestamp(capture["startedAt"]), timestamp(capture["finishedAt"])
    require(started < finished, "Invalid process observation interval")
    process = capture["process"]
    fields(process, ("pid", "closed", "exitCode", "signal", "forceStopped", "intervention", "error"))
    require(type(process["pid"]) is int and process["pid"] > 0 and process["closed"] is True
            and process["error"] is None and type(process["exitCode"]) is int
            and type(process["forceStopped"]) is bool, "Missing owned process exit facts")
    operation = capture["operation"]
    fields(operation, ("kind", "afterSeq", "at", "requestedSignal"))
    require(type(operation["afterSeq"]) is int and operation["afterSeq"] >= 0
            and started <= timestamp(operation["at"]) <= finished, "Invalid live operation checkpoint")
    require(isinstance(observations, list) and observations, "Missing native lifecycle observations")
    for event in observations:
        require(isinstance(event, dict) and type(event.get("observationVersion")) is int
                and event["observationVersion"] == 1 and event.get("pid") == process["pid"]
                and started <= timestamp(event.get("at")) <= finished, "Unassociated native observation")
    require(all(timestamp(left["at"]) <= timestamp(right["at"])
                for left, right in zip(observations, observations[1:])), "Reversed native observations")
    streams = [item for item in observations if item.get("kind") == "model/first-chunk"]
    require(len(streams) == 1 and streams[0].get("sessionId") == capture["sessionId"], "No actual model stream for this task")
    fields(ui, ("webUiActionsVersion", "driver", "actions"))
    require(type(ui["webUiActionsVersion"]) is int and ui["webUiActionsVersion"] == 1
            and ui["driver"] == "cua" and isinstance(ui["actions"], list), "Missing actual browser action evidence")
    expected = ["submit", "cancel"] if capture["scenario"] == "page-cancel" else ["submit"]
    require([item.get("kind") for item in ui["actions"]] == expected, "Expected exactly one submitted browser task")
    for action in ui["actions"]:
        fields(action, ("kind", "at", "url", "control"))
        require(action["url"] == capture["url"] and nonempty(action["control"])
                and started <= timestamp(action["at"]) <= finished, "Unassociated browser action")
    require(timestamp(ui["actions"][0]["at"]) <= timestamp(streams[0]["at"]), "Stream precedes page submission")
    ends = [item for item in observations if item.get("kind") == "session/event" and item.get("type") == "turn/end"]
    interrupted = capture["scenario"] == "process-interrupt"
    if interrupted:
        require(operation["kind"] == "process-kill" and operation["requestedSignal"] == "SIGKILL"
                and process["forceStopped"] is True and process["intervention"] == "expected-interrupt"
                and process["exitCode"] != 0 and process["signal"] is None
                and timestamp(streams[0]["at"]) <= timestamp(operation["at"]) and not ends,
                "No in-task owned process interruption")
    else:
        require(process["forceStopped"] is False and process["intervention"] == "console-shutdown"
                and process["exitCode"] == 130 and process["signal"] is None
                and any(item.get("kind") == "process/SIGINT" for item in observations)
                and any(item.get("kind") == "observer/disposed" for item in observations), "No observed native Ctrl+C cleanup")
        signals = [item for item in observations if item.get("kind") == "process/SIGINT"]
        require(len(ends) == len(signals) == 1 and timestamp(ends[0]["at"]) <= timestamp(signals[0]["at"]),
                "Console shutdown did not follow the finished task")
        if capture["scenario"] == "page-cancel":
            require(operation["kind"] == "page-cancel" and operation["requestedSignal"] is None
                    and timestamp(streams[0]["at"]) <= timestamp(operation["at"])
                    <= timestamp(ui["actions"][1]["at"]) <= timestamp(ends[0]["at"]),
                    "No browser cancellation after the observed checkpoint")
        else:
            require(operation["kind"] == "console-ctrl-c" and operation["requestedSignal"] == "SIGINT",
                    "Normal exit did not use native console input")
    return capture


def verify_live(directory):
    directory = Path(directory).resolve()
    result = {"liveWebVerificationVersion": 1, "source": "live", "scope": "live-web-lifecycle", "scenario": None,
              "verified": False, "liveWebVerified": False, "execution": {"status": "unknown"},
              "recording": {"outcome": "unverified"}, "assertions": {"outcome": "not_run"},
              "metrics": empty_metrics(), "outcome": "unevaluable", "reasons": []}
    try:
        capture = load_json(directory / "lifecycle-live.json")
        require(isinstance(capture, dict), "Live capture must be an object")
        result.update(scenario=capture.get("scenario"), process=capture.get("process"))
        observations = [parse_json(line) for line in (directory / "observations.jsonl").read_text(encoding="utf-8").splitlines()]
        ui = load_json(directory / "ui-actions.json")
        validate_live(capture, observations, ui)
        result.update(scenario=capture["scenario"], process=capture["process"], url=capture["url"])
        case = validate_case(load_json(directory / "case.json"))
        events = verify_recorded_task(directory, capture, case, result, allow_unconfirmed_tail=True)
        observed = [item for item in observations if item.get("kind") == "session/event"]
        require(observed and all(item.get("sessionId") == capture["sessionId"] for item in observed)
                and [item.get("seq") for item in observed[:len(events)]] == [item["seq"] for item in events],
                "Native event observations do not cover this recording")
        headers = [item["data"]["header"]["config"] for item in events if item.get("type") == "request/header"]
        require(headers and all(header.get("provider") == case["configRef"]["provider"]
                                    and header.get("model") == case["configRef"]["model"] for header in headers),
                "Actual model request route differs from frozen case")
        if capture["scenario"] == "process-interrupt":
            require(any(item.get("type") == "request/header" and item["seq"] <= capture["operation"]["afterSeq"]
                        for item in events), "Operation checkpoint did not cover the model request route")
        setup = load_json(directory / "setup.json")
        workspaces = {item["cwd"] for item in observed if nonempty(item.get("cwd"))}
        expected_workspace = str(Path(setup["workspace"]).resolve())
        matches = all(str(Path(value).resolve()) == expected_workspace for value in workspaces) if workspaces else None
        result["environment"] = {"workspaceMatch": matches, "workspaceObservationAvailable": bool(workspaces)}
        require(matches is not False and (capture["scenario"] == "page-cancel" or matches is True),
                "Actual Web Workspace is not associated with this frozen fixture")
        if capture["scenario"] != "process-interrupt":
            result["metrics"] = recording_metrics(events, case["input"])
        result["metrics"]["elapsedSeconds"] = (timestamp(capture["finishedAt"]) - timestamp(capture["startedAt"])).total_seconds()
        result["observedModelStream"] = True
        result["verified"] = result["liveWebVerified"] = True
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        # A task assertion cannot promote a capture whose route/environment/action gate failed.
        result["outcome"] = "unevaluable"
        result["reasons"].append(str(error))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = verify_live(args.directory)
    try:
        text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
        print(text, end="")
        return 0 if result["verified"] else 1
    except OSError as error:
        print(json.dumps({"verified": False, "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
