"""Deterministic virtual files. No host filesystem access or model-dependent answers."""
from copy import deepcopy
import hashlib
import json
from pathlib import PurePosixPath

from .formats import fields, nonempty, require


def snapshot_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


class StatefulEnvironment:
    def __init__(self, environment, case_run_id, budget=None):
        self.files = dict(environment["files"])
        self.failures = dict(environment["stateful"]["transientReadFailures"])
        self.case_run_id = case_run_id
        self.session_id = None
        self.responses = {}
        self.tools = environment["stateful"].get("tools", ["eval_read", "eval_list"])
        self.delays = deepcopy(environment["stateful"].get("toolDelaysMs", {}))
        self.budget = budget or {}
        self.pending = {}
        self.attempts = {}
        self.cancelled = False

    def bind(self, session_id):
        require(nonempty(session_id), "Missing bridge session")
        require(self.session_id in (None, session_id), "Bridge session changed")
        self.session_id = session_id

    def _validate(self, request):
        fields(request, ("type", "bridgeVersion", "requestId", "caseRunId", "sessionId", "operation", "arguments"))
        require(request["type"] == "tool-request" and type(request["bridgeVersion"]) is int
                and request["bridgeVersion"] == 1, "Unsupported bridge request")
        require(request["caseRunId"] == self.case_run_id and self.session_id is not None
                and request["sessionId"] == self.session_id, "Bridge identity mismatch")
        require(nonempty(request["requestId"]), "Missing bridge request ID")
        request_id = request["requestId"]
        if request_id in self.responses:
            previous, response = self.responses[request_id]
            require(previous == request, "Conflicting duplicate bridge request")
        require(request["operation"] in ("read", "list", "write", "delete", "edit") and
                "eval_" + request["operation"] in self.tools, "Unknown or disabled bridge operation")
        arguments = (("path", "content") if request["operation"] == "write" else
                     ("path", "oldText", "newText") if request["operation"] == "edit" else ("path",))
        fields(request["arguments"], arguments)
        if request["operation"] == "write":
            require(isinstance(request["arguments"]["content"], str), "Write content must be text")
        if request["operation"] == "edit":
            require(all(isinstance(request["arguments"][key], str) for key in ("oldText", "newText")),
                    "Edit oldText and newText must be text")
        path = request["arguments"]["path"]
        require(isinstance(path, str), "Tool path must be text")
        if request_id in self.pending:
            require(self.pending[request_id][0] == request, "Conflicting pending bridge request")

    def _respond(self, request, error, text=""):
        response = {"type": "tool-response", "bridgeVersion": 1, "requestId": request["requestId"],
                    "caseRunId": self.case_run_id, "sessionId": self.session_id,
                    "isError": error is not None, "text": f"{error}: {request['arguments']['path']}" if error else text}
        self.responses[request["requestId"]] = (deepcopy(request), deepcopy(response))
        return response

    def submit(self, request, now):
        """Schedule virtual work without sleeping on the task supervision thread."""
        self._validate(request)
        request_id = request["requestId"]
        if request_id in self.responses:
            return [deepcopy(self.responses[request_id][1])]
        if request_id not in self.pending:
            tool = "eval_" + request["operation"]
            index = self.attempts.get(tool, 0)
            self.attempts[tool] = index + 1
            delays = self.delays.get(tool, [])
            delay = delays[index] if index < len(delays) else 0
            timeout = self.budget.get("toolTimeoutsMs", {}).get(tool, self.budget.get("toolTimeoutMs", 5000))
            self.pending[request_id] = (deepcopy(request), now + delay / 1000, now + timeout / 1000)
        return self.poll(now)

    def poll(self, now):
        responses = []
        for request_id, (request, ready, deadline) in list(self.pending.items()):
            if now >= deadline:
                del self.pending[request_id]
                responses.append(self._respond(request, "TOOL_TIMEOUT"))
            elif now >= ready:
                del self.pending[request_id]
                responses.append(self.handle(request))
        return responses

    def wait_seconds(self, now):
        return max(0, min((min(ready, deadline) - now for _, ready, deadline in self.pending.values()), default=.1))

    def cancel(self, request):
        fields(request, ("type", "bridgeVersion", "requestId", "caseRunId", "sessionId"))
        require(request["type"] == "tool-cancel" and type(request["bridgeVersion"]) is int
                and request["bridgeVersion"] == 1 and request["caseRunId"] == self.case_run_id
                and request["sessionId"] == self.session_id and nonempty(request["requestId"]), "Invalid tool cancellation")
        entry = self.pending.pop(request["requestId"], None)
        if entry:
            self.cancelled = True
            self._respond(entry[0], "TOOL_CANCELLED")

    def cancel_all(self):
        if self.pending:
            self.cancelled = True
        for request, _, _ in self.pending.values():
            self._respond(request, "TOOL_CANCELLED")
        self.pending.clear()

    def snapshot(self, case, run_id, completed):
        return {"environmentSnapshotFormatVersion": 1, "caseRunId": self.case_run_id,
                "sessionId": self.session_id, "runId": run_id, "environmentSha256": snapshot_digest(case["environment"]),
                "toolBudget": {key: value for key, value in case["budget"].items() if key != "timeoutSeconds"},
                "complete": bool(completed and not self.pending and not self.cancelled), "files": dict(self.files)}

    def handle(self, request):
        """Immediate virtual operation; production calls enter through submit/poll."""
        self._validate(request)
        if request["requestId"] in self.responses:
            return deepcopy(self.responses[request["requestId"]][1])
        path = request["arguments"]["path"]
        error = None
        text = ""
        if "\\" in path or ":" in path or path.startswith("/") or any(p in ("", "..") for p in path.split("/")) or (path != "." and "." in path.split("/")):
            error = "INVALID_PATH"
        elif request["operation"] == "list":
            prefix = "" if path == "." else path + "/"
            matches = sorted(name for name in self.files if name.startswith(prefix))
            text = "\n".join(matches)
            if not matches:
                error = "NOT_FOUND"
        elif request["operation"] == "write":
            if path == "." or any(str(parent) in self.files for parent in PurePosixPath(path).parents) or any(
                    name.startswith(path + "/") for name in self.files):
                error = "PATH_COLLISION"
            else:
                self.files[path] = request["arguments"]["content"]
                text = "WROTE: " + path
        elif path not in self.files:
            error = "NOT_FOUND"
        elif request["operation"] == "delete":
            del self.files[path]
            text = "DELETED: " + path
        elif request["operation"] == "edit":
            old, new = request["arguments"]["oldText"], request["arguments"]["newText"]
            content = self.files[path]
            start = content.find(old)
            if not old:
                error = "EMPTY_EDIT_TARGET"
            elif start < 0:
                error = "TEXT_NOT_FOUND"
            elif content.find(old, start + 1) >= 0:
                error = "AMBIGUOUS_MATCH"  # Overlapping occurrences also count as ambiguous.
            else:
                self.files[path] = content[:start] + new + content[start + len(old):]
                text = "EDITED: " + path
        elif self.failures.get(path, 0) > 0:
            self.failures[path] -= 1
            error = "TEMPORARY_READ_FAILURE"
        else:
            text = self.files[path]
        return self._respond(request, error, text)
