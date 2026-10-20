"""Observed single-task metrics and explicit sample denominators; no price estimates."""
from collections import Counter
import math

from .formats import require

METRICS = ("modelCalls", "toolCalls", "inputTokens", "outputTokens", "totalTokens", "elapsedSeconds", "cost")


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def empty_metrics():
    return {"metricsFormatVersion": 1, **dict.fromkeys(METRICS)}


def recording_metrics(events, task_input):
    from .evaluate import text_of

    # Closed, contiguous task boundaries are required even for cancelled/error runs.
    users = [event for event in events if event.get("type") == "user/message"
             and event.get("data", {}).get("source", {}).get("kind") == "user"]
    ends = [event for event in events if event.get("type") == "turn/end"]
    require(len(users) == len(ends) == 1 and text_of(users[0]["data"]) == task_input
            and users[0]["seq"] < ends[0]["seq"], "Metrics require one closed matching task")
    relevant = {"assistant/message", "assistant/attempt", "tool/call", "tool/result"}
    require(all(users[0]["seq"] < event["seq"] < ends[0]["seq"] for event in events if event.get("type") in relevant),
            "Metric evidence outside task")
    interval = [event for event in events if users[0]["seq"] <= event["seq"] <= ends[0]["seq"]]
    require(all(right["seq"] == left["seq"] + 1 for left, right in zip(interval, interval[1:])), "Metric sequence gap")
    messages = [event["data"] for event in interval if event.get("type") == "assistant/message"]
    attempts = [event for event in interval if event.get("type") == "assistant/attempt"]
    result = empty_metrics()
    # request/header is an epoch/configuration change, not one event per model call.
    result.update(modelCalls=len(messages) + len(attempts),
                  toolCalls=sum(event.get("type") == "tool/call" for event in interval))
    for key in ("inputTokens", "outputTokens", "totalTokens"):
        values = [message.get("usage", {}).get(key) if isinstance(message.get("usage"), dict) else None for message in messages]
        if values and not attempts and all(type(value) is int and value >= 0 for value in values):
            result[key] = sum(values)
    return result


def summarize(samples):
    planned = len(samples)
    attempted = sum(row["caseRunId"] is not None for row in samples)
    outcomes = Counter(row["outcome"] for row in samples)
    evaluable = outcomes["passed"] + outcomes["failed"]

    def rate(numerator, denominator):
        return {"numerator": numerator, "denominator": denominator,
                "value": numerator / denominator if denominator else None}

    result = {"planned": planned, "attempted": attempted, "finished": sum(row["status"] == "finished" for row in samples),
              "skipped": sum(row["status"] == "skipped" for row in samples),
              "errors": sum(row["status"] == "error" for row in samples),
              "outcomes": {key: outcomes[key] for key in ("passed", "failed", "unevaluable")},
              "evaluablePassRate": rate(outcomes["passed"], evaluable),
              "attemptedPassRate": rate(outcomes["passed"], attempted),
              "evaluableCoverage": rate(evaluable, planned), "metrics": {}}
    for field in ("executionStatus", "recordingOutcome", "assertionOutcome", "source", "configurationMatch"):
        result[field + "Counts"] = dict(Counter(row.get(field) or "unknown" for row in samples))
    for key in METRICS:
        values = [(row.get("metrics") or {}).get(key) for row in samples]
        observed = [value for value in values if number(value)]
        result["metrics"][key] = {"observedSamples": len(observed), "missingSamples": planned - len(observed),
                                  "observedTotal": sum(observed) if observed else None,
                                  "observedMean": sum(observed) / len(observed) if observed else None}
    return result
