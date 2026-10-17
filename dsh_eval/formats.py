"""Version 1 case and evidence formats. No third-party dependencies."""
import json
import math
from pathlib import Path, PurePosixPath
from uuid import UUID


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"Non-finite JSON number: {value}")


def _float(value):
    number = float(value)
    require(math.isfinite(number), f"Non-finite JSON number: {value}")
    return number


def parse_json(text):
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float)


def load_json(path):
    return parse_json(Path(path).read_text(encoding="utf-8"))


def fields(value, required, optional=()):
    require(isinstance(value, dict), "Expected a JSON object")
    require(set(required) <= value.keys(), f"Missing fields: {set(required) - value.keys()}")
    require(value.keys() <= set(required) | set(optional), f"Unknown fields: {value.keys() - set(required) - set(optional)}")


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def configuration(value):
    fields(value, ("provider", "model", "profile", "pluginVersion"))
    require(all(nonempty(item) for item in value.values()), "Configuration values must be nonempty strings")


def validate_case(case):
    fields(case, ("caseFormatVersion", "caseId", "input", "environment", "configRef", "budget", "assertions"))
    require(type(case["caseFormatVersion"]) is int and case["caseFormatVersion"] == 1, "Unsupported case format")
    require(nonempty(case["caseId"]) and nonempty(case["input"]), "caseId and input must be nonempty strings")
    fields(case["environment"], ("files",))
    files = case["environment"]["files"]
    require(isinstance(files, dict), "environment.files must be an object")
    for path, content in files.items():
        require(nonempty(path) and "\\" not in path and ":" not in path and not path.startswith("/")
                and all(part not in ("", ".", "..") for part in path.split("/"))
                and not PurePosixPath(path).is_absolute(), "Fixture paths must be relative POSIX file paths")
        require(isinstance(content, str), "Fixture content must be text")
    require(not any(str(parent) in files for path in files for parent in PurePosixPath(path).parents),
            "Fixture file/directory collision")
    configuration(case["configRef"])
    fields(case["budget"], ("timeoutSeconds",))
    require(type(case["budget"]["timeoutSeconds"]) is int and case["budget"]["timeoutSeconds"] > 0,
            "timeoutSeconds must be a positive integer")
    assertions = case["assertions"]
    require(isinstance(assertions, list) and assertions, "At least one assertion is required")
    ids = set()
    for assertion in assertions:
        require(isinstance(assertion, dict), "Assertion must be an object")
        kind = assertion.get("type")
        if kind == "final_text":
            fields(assertion, ("id", "type", "equals"))
            require(nonempty(assertion["equals"]), "Final text must be nonempty")
        elif kind == "tool_result":
            fields(assertion, ("id", "type", "tool", "arguments", "result"))
            require(nonempty(assertion["tool"]), "Tool name must be nonempty")
            require(isinstance(assertion["arguments"], dict) and assertion["arguments"], "Expected tool arguments are required")
            fields(assertion["result"], ("isError",), ("textContains",))
            require(type(assertion["result"]["isError"]) is bool, "isError must be boolean")
            if "textContains" in assertion["result"]:
                require(nonempty(assertion["result"]["textContains"]), "textContains must be nonempty")
        elif kind == "turn_end":
            fields(assertion, ("id", "type", "reason"))
            require(isinstance(assertion["reason"], dict) and nonempty(assertion["reason"].get("kind")), "Expected end reason is required")
        else:
            raise ValueError(f"Unsupported assertion type: {kind}")
        require(nonempty(assertion["id"]) and assertion["id"] not in ids, "Assertion IDs must be nonempty and unique")
        ids.add(assertion["id"])
    return case


def validate_evidence(evidence, case):
    fields(evidence, ("evidenceFormatVersion", "caseRunId", "caseId", "runId", "sessionId", "runDir",
                      "source", "configuration", "budgetEnforcement", "execution"), ("batchId",))
    require(type(evidence["evidenceFormatVersion"]) is int and evidence["evidenceFormatVersion"] == 1, "Unsupported evidence format")
    require(nonempty(evidence["caseRunId"]), "caseRunId must be a UUID")
    UUID(evidence["caseRunId"])
    require(evidence["caseId"] == case["caseId"], "Case/evidence caseId mismatch")
    require(all(nonempty(evidence[key]) for key in ("runId", "sessionId", "runDir")), "Recording identity and path are required")
    require(evidence["caseRunId"] != evidence["runId"], "caseRunId must be distinct from recorder runId")
    require(evidence["source"] in ("synthetic", "live"), "source must be synthetic or live")
    if "batchId" in evidence:
        require(nonempty(evidence["batchId"]), "batchId must be nonempty")
    configuration(evidence["configuration"])
    fields(evidence["budgetEnforcement"], ("timeoutSeconds",))
    require(type(evidence["budgetEnforcement"]["timeoutSeconds"]) is bool, "Budget enforcement must be boolean")
    execution = evidence["execution"]
    fields(execution, ("status",), ("reason", "exitCode", "signal"))
    require(execution["status"] in ("completed", "cancelled", "timed_out", "runtime_error", "unknown"), "Unknown execution status")
    for key in ("reason", "signal"):
        require(key not in execution or execution[key] is None or nonempty(execution[key]), f"Invalid execution {key}")
    require("exitCode" not in execution or execution["exitCode"] is None or type(execution["exitCode"]) is int, "Invalid exitCode")
    return evidence
