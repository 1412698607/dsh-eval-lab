"""Deterministic virtual files. No host filesystem access or model-dependent answers."""
from copy import deepcopy

from .formats import fields, nonempty, require


class StatefulEnvironment:
    def __init__(self, environment, case_run_id):
        self.files = dict(environment["files"])
        self.failures = dict(environment["stateful"]["transientReadFailures"])
        self.case_run_id = case_run_id
        self.session_id = None
        self.responses = {}

    def bind(self, session_id):
        require(nonempty(session_id), "Missing bridge session")
        require(self.session_id in (None, session_id), "Bridge session changed")
        self.session_id = session_id

    def handle(self, request):
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
            return deepcopy(response)
        fields(request["arguments"], ("path",))
        path = request["arguments"]["path"]
        require(isinstance(path, str), "Tool path must be text")
        require(request["operation"] in ("read", "list"), "Unknown bridge operation")
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
        elif path not in self.files:
            error = "NOT_FOUND"
        elif self.failures.get(path, 0) > 0:
            self.failures[path] -= 1
            error = "TEMPORARY_READ_FAILURE"
        else:
            text = self.files[path]
        response = {"type": "tool-response", "bridgeVersion": 1, "requestId": request_id,
                    "caseRunId": self.case_run_id, "sessionId": self.session_id,
                    "isError": error is not None, "text": f"{error}: {path}" if error else text}
        self.responses[request_id] = (deepcopy(request), deepcopy(response))
        return response
