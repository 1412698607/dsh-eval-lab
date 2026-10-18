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


def validate_batch(batch):
    fields(batch, ("batchFormatVersion", "batchName", "failurePolicy", "cases"))
    require(type(batch["batchFormatVersion"]) is int and batch["batchFormatVersion"] == 1, "Unsupported batch format")
    require(nonempty(batch["batchName"]), "batchName must be nonempty")
    require(batch["failurePolicy"] in ("continue", "stop"), "failurePolicy must be continue or stop")
    require(isinstance(batch["cases"], list) and batch["cases"], "Batch must contain cases")
    identifiers = set()
    for entry in batch["cases"]:
        fields(entry, ("entryId", "casePath"))
        require(nonempty(entry["entryId"]) and entry["entryId"] not in identifiers, "Batch entryId must be nonempty and unique")
        identifiers.add(entry["entryId"])
        path = entry["casePath"]
        require(nonempty(path) and "\\" not in path and ":" not in path and not path.startswith("/")
                and all(part not in ("", ".") for part in path.split("/")),
                "casePath must be a relative POSIX path, resolved beside the batch manifest")
    return batch


def validate_case(case):
    fields(case, ("caseFormatVersion", "caseId", "input", "environment", "configRef", "budget", "assertions"))
    require(type(case["caseFormatVersion"]) is int and case["caseFormatVersion"] in (1, 2), "Unsupported case format")
    require(nonempty(case["caseId"]) and nonempty(case["input"]), "caseId and input must be nonempty strings")
    fields(case["environment"], ("files",), ("stateful",) if case["caseFormatVersion"] == 2 else ())
    files = case["environment"]["files"]
    require(isinstance(files, dict), "environment.files must be an object")
    for path, content in files.items():
        require(nonempty(path) and "\\" not in path and ":" not in path and not path.startswith("/")
                and all(part not in ("", ".", "..") for part in path.split("/"))
                and not PurePosixPath(path).is_absolute(), "Fixture paths must be relative POSIX file paths")
        require(isinstance(content, str), "Fixture content must be text")
    require(not any(str(parent) in files for path in files for parent in PurePosixPath(path).parents),
            "Fixture file/directory collision")
    if "stateful" in case["environment"]:
        stateful = case["environment"]["stateful"]
        fields(stateful, ("transientReadFailures",))
        failures = stateful["transientReadFailures"]
        require(isinstance(failures, dict), "transientReadFailures must be an object")
        require(all(path in files and type(count) is int and count >= 0 for path, count in failures.items()),
                "Transient failures require an existing file and a nonnegative integer")
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
            require(isinstance(assertion["arguments"], dict)
                    and (case["caseFormatVersion"] == 2 or assertion["arguments"]),
                    "Expected tool arguments must be an object (nonempty in case version 1)")
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
                      "source", "configuration", "budgetEnforcement", "execution"), ("batchId", "runtimeReport"))
    version = evidence["evidenceFormatVersion"]
    require(type(version) is int and version in (1, 2), "Unsupported evidence format")
    require(version == 2 or "runtimeReport" not in evidence, "runtimeReport requires evidence version 2")
    require(nonempty(evidence["caseRunId"]), "caseRunId must be a UUID")
    UUID(evidence["caseRunId"])
    require(evidence["caseId"] == case["caseId"], "Case/evidence caseId mismatch")
    require(all(nonempty(evidence[key]) or version == 2 and evidence[key] is None
                for key in ("runId", "sessionId", "runDir")), "Recording identity and path are required (or null in version 2)")
    require(evidence["caseRunId"] != evidence["runId"], "caseRunId must be distinct from recorder runId")
    require(evidence["source"] in ("synthetic", "live"), "source must be synthetic or live")
    if "batchId" in evidence:
        require(nonempty(evidence["batchId"]), "batchId must be nonempty")
    if evidence["configuration"] is not None or version == 1:
        configuration(evidence["configuration"])
    if "runtimeReport" in evidence:
        require(nonempty(evidence["runtimeReport"]), "runtimeReport must be a path")
    fields(evidence["budgetEnforcement"], ("timeoutSeconds",))
    require(type(evidence["budgetEnforcement"]["timeoutSeconds"]) is bool, "Budget enforcement must be boolean")
    execution = evidence["execution"]
    fields(execution, ("status",), ("reason", "exitCode", "signal"))
    require(execution["status"] in ("completed", "cancelled", "timed_out", "runtime_error", "unknown"), "Unknown execution status")
    for key in ("reason", "signal"):
        require(key not in execution or execution[key] is None or nonempty(execution[key]), f"Invalid execution {key}")
    require("exitCode" not in execution or execution["exitCode"] is None or type(execution["exitCode"]) is int, "Invalid exitCode")
    return evidence
