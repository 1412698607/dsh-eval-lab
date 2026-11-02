"""Version 1 case and evidence formats. No third-party dependencies."""
import json
import math
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
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


def validate_experiment(experiment):
    fields(experiment, ("experimentFormatVersion", "experimentName", "repetitions", "failurePolicy", "cases", "configurations"),
           ("randomSeed",))
    require(type(experiment["experimentFormatVersion"]) is int and experiment["experimentFormatVersion"] == 1,
            "Unsupported experiment format")
    require(nonempty(experiment["experimentName"]), "experimentName must be nonempty")
    require(type(experiment["repetitions"]) is int and experiment["repetitions"] > 0,
            "repetitions must be a positive integer")
    if "randomSeed" in experiment:
        require(type(experiment["randomSeed"]) is int and 0 <= experiment["randomSeed"] <= 9007199254740991,
                "randomSeed must be a nonnegative safe integer")
    validate_batch({"batchFormatVersion": 1, "batchName": experiment["experimentName"],
                    "failurePolicy": experiment["failurePolicy"], "cases": experiment["cases"]})
    require(isinstance(experiment["configurations"], list) and experiment["configurations"], "Configurations are required")
    identifiers = set()
    for entry in experiment["configurations"]:
        fields(entry, ("configurationId", "configRef"))
        require(nonempty(entry["configurationId"]) and entry["configurationId"] not in identifiers,
                "configurationId must be nonempty and unique")
        identifiers.add(entry["configurationId"])
        configuration(entry["configRef"])
    return experiment


def model_providers(value):
    require(isinstance(value, dict), "modelProviders must be an object")
    for route, profile in value.items():
        require(re.fullmatch(r"[a-z][a-z0-9-]*", route) is not None
                and route not in ("deepseek-official", "deepseek-account"), "Invalid external provider route")
        fields(profile, ("api", "baseURL", "apiKeyEnv", "models"))
        require(profile["api"] == "openai-completions", "External providers require openai-completions")
        require(isinstance(profile["apiKeyEnv"], str)
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", profile["apiKeyEnv"]) is not None,
                "apiKeyEnv must be a credential reference name")
        address = profile["baseURL"]
        require(isinstance(address, str) and address.startswith("https://")
                and all(33 <= ord(character) <= 126 and character not in "\\@?#" for character in address),
                "baseURL must be an ASCII HTTPS endpoint without credentials, query or fragment")
        endpoint = urlsplit(address)
        require(re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", endpoint.netloc) is not None
                and endpoint.scheme == "https" and bool(endpoint.hostname)
                and re.fullmatch(r"[A-Za-z0-9.-]+", endpoint.hostname) is not None
                and endpoint.username is None and endpoint.password is None
                and (endpoint.port is None or 0 < endpoint.port <= 65535), "Invalid HTTPS provider endpoint")
        require(isinstance(profile["models"], list) and bool(profile["models"]), "Provider models must be nonempty")
        identifiers = set()
        for model in profile["models"]:
            fields(model, ("id", "contextWindow", "maxTokens"))
            require(nonempty(model["id"]) and model["id"] not in identifiers, "Model IDs must be nonempty and unique")
            identifiers.add(model["id"])
            for name in ("contextWindow", "maxTokens"):
                require(type(model[name]) is int and 0 < model[name] <= 9007199254740991,
                        f"Model {name} must be a positive safe integer")
    return value


def validate_case(case):
    fields(case, ("caseFormatVersion", "caseId", "input", "environment", "configRef", "budget", "assertions"),
           ("recorder", "modelProviders"))
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
        fields(stateful, ("transientReadFailures",), ("tools", "toolDelaysMs"))
        tools = stateful.get("tools", ["eval_read", "eval_list"])
        require(isinstance(tools, list) and tools and all(isinstance(tool, str) and tool in
                ("eval_read", "eval_list", "eval_write") for tool in tools) and len(set(tools)) == len(tools),
                "stateful.tools must name distinct supported tools")
        delays = stateful.get("toolDelaysMs", {})
        require(isinstance(delays, dict), "toolDelaysMs must be an object")
        for tool, values in delays.items():
            require(tool in tools and isinstance(values, list) and all(type(value) is int and
                    0 <= value <= 3600000 for value in values), "Tool delays must be enabled-tool millisecond sequences (0..3600000)")
        failures = stateful["transientReadFailures"]
        require(isinstance(failures, dict), "transientReadFailures must be an object")
        require(all(path in files and type(count) is int and count >= 0 for path, count in failures.items()),
                "Transient failures require an existing file and a nonnegative integer")
    configuration(case["configRef"])
    if "modelProviders" in case:
        model_providers(case["modelProviders"])
    if "recorder" in case:
        fields(case["recorder"], (), ("maxEventBytes", "maxPendingBytes"))
        for name, value in case["recorder"].items():
            require(type(value) is int and 0 < value <= 9007199254740991,
                    f"recorder.{name} must be a positive safe integer (UTF-8 bytes)")
    fields(case["budget"], ("timeoutSeconds",), ("toolTimeoutMs", "toolTimeoutsMs"))
    require(type(case["budget"]["timeoutSeconds"]) is int and case["budget"]["timeoutSeconds"] > 0,
            "timeoutSeconds must be a positive integer")
    if any(key in case["budget"] for key in ("toolTimeoutMs", "toolTimeoutsMs")):
        require("stateful" in case["environment"], "Tool deadlines require the controlled stateful environment")
        overrides = case["budget"].get("toolTimeoutsMs", {})
        require(isinstance(overrides, dict) and all(tool in tools for tool in overrides),
                "toolTimeoutsMs must name enabled tools")
        require(all(type(value) is int and 0 < value <= 3600000 for value in
                    [case["budget"].get("toolTimeoutMs", 5000), *overrides.values()]),
                "Tool deadlines must be integer milliseconds (1..3600000)")
    assertions = case["assertions"]
    require(isinstance(assertions, list) and assertions, "At least one assertion is required")
    ids = set()
    tool_ids = set()
    for assertion in assertions:
        require(isinstance(assertion, dict), "Assertion must be an object")
        kind = assertion.get("type")
        if kind == "final_text":
            fields(assertion, ("id", "type", "equals"))
            require(nonempty(assertion["equals"]), "Final text must be nonempty")
        elif kind == "environment_files":
            fields(assertion, ("id", "type", "equals"))
            require("stateful" in case["environment"], "environment_files requires stateful execution")
            expected = assertion["equals"]
            require(isinstance(expected, dict) and all(nonempty(path) and isinstance(content, str)
                    and "\\" not in path and ":" not in path and not path.startswith("/")
                    and all(part not in ("", ".", "..") for part in path.split("/"))
                    for path, content in expected.items()), "Expected files must be relative POSIX paths and text")
            require(not any(str(parent) in expected for path in expected for parent in PurePosixPath(path).parents),
                    "Expected file/directory collision")
        elif kind == "tool_result":
            fields(assertion, ("id", "type", "tool", "arguments", "result"), ("after",))
            require(nonempty(assertion["tool"]), "Tool name must be nonempty")
            if "after" in assertion:
                require(nonempty(assertion["after"]) and assertion["after"] in tool_ids,
                        "after must name an earlier tool_result assertion")
            require(isinstance(assertion["arguments"], dict)
                    and (case["caseFormatVersion"] == 2 or assertion["arguments"]),
                    "Expected tool arguments must be an object (nonempty in case version 1)")
            fields(assertion["result"], ("isError",), ("textContains", "textEquals"))
            require(type(assertion["result"]["isError"]) is bool, "isError must be boolean")
            require(not {"textContains", "textEquals"} <= assertion["result"].keys(),
                    "Choose textContains or textEquals")
            if "textContains" in assertion["result"]:
                require(nonempty(assertion["result"]["textContains"]), "textContains must be nonempty")
            if "textEquals" in assertion["result"]:
                require(isinstance(assertion["result"]["textEquals"], str), "textEquals must be text")
        elif kind in ("tool_forbidden", "tool_call_count"):
            fields(assertion, ("id", "type", "tool"),
                   ("arguments", "min", "max") if kind == "tool_call_count" else ("arguments",))
            require(nonempty(assertion["tool"]), "Tool name must be nonempty")
            require(isinstance(assertion.get("arguments", {}), dict), "Expected tool arguments must be an object")
            if kind == "tool_call_count":
                require("min" in assertion or "max" in assertion, "Tool call count requires min or max")
                for bound in ("min", "max"):
                    if bound in assertion:
                        require(type(assertion[bound]) is int and 0 <= assertion[bound] <= 9007199254740991,
                                f"Tool call count {bound} must be a nonnegative safe integer")
                require(assertion.get("min", 0) <= assertion.get("max", 9007199254740991),
                        "Tool call count min must not exceed max")
        elif kind == "turn_end":
            fields(assertion, ("id", "type", "reason"))
            require(isinstance(assertion["reason"], dict) and nonempty(assertion["reason"].get("kind")), "Expected end reason is required")
        else:
            raise ValueError(f"Unsupported assertion type: {kind}")
        require(nonempty(assertion["id"]) and assertion["id"] not in ids, "Assertion IDs must be nonempty and unique")
        ids.add(assertion["id"])
        if kind == "tool_result":
            tool_ids.add(assertion["id"])
    return case


def validate_evidence(evidence, case):
    fields(evidence, ("evidenceFormatVersion", "caseRunId", "caseId", "runId", "sessionId", "runDir",
                      "source", "configuration", "budgetEnforcement", "execution"),
           ("batchId", "runtimeReport", "environmentSnapshotSha256"))
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
    if "environmentSnapshotSha256" in evidence:
        digest = evidence["environmentSnapshotSha256"]
        require(version == 2 and "runtimeReport" in evidence and isinstance(digest, str)
                and len(digest) == 64 and all(char in "0123456789abcdef" for char in digest), "Invalid environment snapshot digest")
    fields(evidence["budgetEnforcement"], ("timeoutSeconds",), ("toolTimeouts",))
    require("toolTimeouts" not in evidence["budgetEnforcement"] or type(evidence["budgetEnforcement"]["toolTimeouts"]) is bool,
            "Tool timeout enforcement must be boolean")
    require(type(evidence["budgetEnforcement"]["timeoutSeconds"]) is bool, "Budget enforcement must be boolean")
    execution = evidence["execution"]
    fields(execution, ("status",), ("reason", "exitCode", "signal"))
    require(execution["status"] in ("completed", "cancelled", "timed_out", "runtime_error", "unknown"), "Unknown execution status")
    for key in ("reason", "signal"):
        require(key not in execution or execution[key] is None or nonempty(execution[key]), f"Invalid execution {key}")
    require("exitCode" not in execution or execution["exitCode"] is None or type(execution["exitCode"]) is int, "Invalid exitCode")
    return evidence
