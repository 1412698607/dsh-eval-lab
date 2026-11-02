"""Concurrent virtual operations and real-process task deadline boundaries."""
import copy
import io
import json
import subprocess
import sys
import unittest

from dsh_eval.environment import StatefulEnvironment
from dsh_eval.runner import _process_options, supervise


class ToolControlTests(unittest.TestCase):
    def setUp(self):
        self.initial = {"a.txt": "old-a", "b.txt": "old-b", "c.txt": "keep-c"}
        self.definition = {"files": self.initial, "stateful": {"transientReadFailures": {},
                           "tools": ["eval_read", "eval_write", "eval_edit", "eval_delete"]}}
        self.budget = {"timeoutSeconds": 5, "toolTimeoutMs": 5000,
                       "toolTimeoutsMs": {"eval_write": 200, "eval_edit": 2000, "eval_delete": 3000}}
        self.env = StatefulEnvironment(self.definition, "case", self.budget)
        self.env.bind("session")
        self.requests = [
            self.request("write-a", "write", {"path": "a.txt", "content": "new-a"}),
            self.request("edit-b", "edit", {"path": "b.txt", "oldText": "old-b", "newText": "new-b"}),
            self.request("delete-c", "delete", {"path": "c.txt"}),
        ]

    def request(self, request_id, operation, arguments):
        return {"type": "tool-request", "bridgeVersion": 1, "requestId": request_id,
                "caseRunId": "case", "sessionId": "session", "operation": operation, "arguments": arguments}

    def cancel(self, request):
        return {key: "tool-cancel" if key == "type" else value for key, value in request.items()
                if key not in ("operation", "arguments")}

    def test_independent_deadlines_and_one_cancel_leave_healthy_operation_running(self):
        self.env.delays = {"eval_write": [1000], "eval_edit": [400], "eval_delete": [1000]}
        for request in self.requests:
            self.assertEqual(self.env.submit(request, 0), [])
        self.env.cancel(self.cancel(self.requests[2]))
        self.assertEqual(set(self.env.pending), {"write-a", "edit-b"})
        self.assertEqual(self.env.poll(.2)[0]["text"], "TOOL_TIMEOUT: a.txt")
        self.assertEqual(set(self.env.pending), {"edit-b"})
        self.assertEqual(self.env.poll(.4)[0]["text"], "EDITED: b.txt")
        self.assertEqual(self.env.files, {"a.txt": "old-a", "b.txt": "new-b", "c.txt": "keep-c"})
        self.assertEqual(self.env.poll(100), [])
        self.assertFalse(self.env.pending)
        # Cancellation remains conservatively incomplete for final-state evaluation.
        self.assertFalse(self.env.snapshot({"environment": self.definition, "budget": self.budget}, "run", True)["complete"])

    def test_late_cancel_and_duplicate_timeout_do_not_touch_another_pending_request(self):
        self.env.delays = {"eval_write": [1000], "eval_edit": [400]}
        for request in self.requests[:2]:
            self.env.submit(request, 0)
        response = self.env.poll(.2)[0]
        pending = copy.deepcopy(self.env.pending)
        self.env.cancel(self.cancel(self.requests[0]))
        self.assertEqual(self.env.submit(self.requests[0], .3), [response])
        self.assertEqual(self.env.pending, pending)
        self.assertEqual(self.env.attempts, {"eval_write": 1, "eval_edit": 1})
        self.assertEqual(self.env.poll(.4)[0]["text"], "EDITED: b.txt")
        self.assertEqual(self.env.files["a.txt"], "old-a")

    def test_post_commit_cancel_neither_rolls_back_nor_cancels_other_work(self):
        self.env.delays = {"eval_delete": [500]}
        self.assertFalse(self.env.submit(self.requests[1], 0)[0]["isError"])
        self.env.submit(self.requests[2], 0)
        self.env.cancel(self.cancel(self.requests[1]))
        self.assertFalse(self.env.cancelled)
        self.assertEqual(set(self.env.pending), {"delete-c"})
        self.assertEqual(self.env.files["b.txt"], "new-b")
        self.assertEqual(self.env.poll(.5)[0]["text"], "DELETED: c.txt")
        self.assertEqual(self.env.files, {"a.txt": "old-a", "b.txt": "new-b"})

    def child(self, script, payload):
        process = subprocess.Popen([sys.executable, "-u", "-c", script, json.dumps(payload)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", **_process_options())
        def cleanup():
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if not stream.closed:
                    stream.close()
        self.addCleanup(cleanup)
        return process

    def test_real_process_single_cancel_does_not_stop_two_other_operations(self):
        self.env.budget = {"toolTimeoutMs": 5000}
        self.env.delays = {"eval_write": [2000], "eval_edit": [150], "eval_delete": [250]}
        read = self.request("read-b", "read", {"path": "b.txt"})
        script = """import json,sys
data=json.loads(sys.argv[1])
def send(value): print(json.dumps(value),flush=True)
def receive(): return json.loads(sys.stdin.readline())
send({'type':'selection','sessionId':'session'})
for request in data['requests']: send(request)
send(data['cancel'])
responses={value['requestId']:value for value in [receive(),receive()]}
assert set(responses)=={'edit-b','delete-c'},responses
assert all(not value['isError'] for value in responses.values()),responses
send(data['requests'][0])
assert receive()['text']=='TOOL_CANCELLED: a.txt'
send(data['read'])
assert receive()['text']=='new-b'
"""
        process = self.child(script, {"requests": self.requests, "cancel": self.cancel(self.requests[0]), "read": read})
        report = supervise(process, 5, environment=self.env)
        self.assertEqual(report["adapterExitCode"], 0, process.stderr.read())
        self.assertIsNone(report["intervention"])
        self.assertIsNone(report["protocolError"])
        self.assertTrue(report["stdinWriterStopped"])
        self.assertEqual(self.env.files, {"a.txt": "old-a", "b.txt": "new-b"})
        self.assertFalse(self.env.pending)

    def test_real_process_tool_timeout_does_not_cancel_other_tool(self):
        self.env.delays = {"eval_write": [1000], "eval_edit": [400]}
        script = """import json,sys
requests=json.loads(sys.argv[1])
def send(value): print(json.dumps(value),flush=True)
def receive(): return json.loads(sys.stdin.readline())
send({'type':'selection','sessionId':'session'})
for request in requests: send(request)
responses={value['requestId']:value for value in [receive(),receive()]}
assert responses['write-a']['text']=='TOOL_TIMEOUT: a.txt',responses
assert responses['edit-b']['text']=='EDITED: b.txt',responses
send(requests[0])
assert receive()==responses['write-a']
"""
        process = self.child(script, self.requests[:2])
        report = supervise(process, 5, environment=self.env)
        self.assertEqual(report["adapterExitCode"], 0, process.stderr.read())
        self.assertIsNone(report["intervention"])
        self.assertIsNone(report["protocolError"])
        self.assertEqual(self.env.files, {"a.txt": "old-a", "b.txt": "new-b", "c.txt": "keep-c"})
        self.assertEqual(self.env.attempts, {"eval_write": 1, "eval_edit": 1})
        self.assertFalse(self.env.pending)

    def test_real_process_task_deadline_clears_all_longer_tool_deadlines(self):
        self.env.budget = {"toolTimeoutMs": 10000}
        self.env.delays = {"eval_write": [5000], "eval_edit": [5000], "eval_delete": [5000]}
        script = """import json,sys
requests=json.loads(sys.argv[1])
print(json.dumps({'type':'selection','sessionId':'session'}),flush=True)
for request in requests: print(json.dumps(request),flush=True)
assert json.loads(sys.stdin.readline())['type']=='timeout'
"""
        process = self.child(script, self.requests)
        report = supervise(process, 1, environment=self.env, event_log=io.StringIO())
        self.assertEqual(report["adapterExitCode"], 0, process.stderr.read())
        self.assertEqual(report["intervention"], "timeout")
        self.assertTrue(report["stdinWriterStopped"])
        self.assertEqual(self.env.attempts, {"eval_write": 1, "eval_edit": 1, "eval_delete": 1})
        self.assertFalse(self.env.pending)
        self.assertEqual(self.env.poll(1e10), [])
        self.assertEqual(self.env.files, self.initial)
        self.assertTrue(all(response[1]["text"].startswith("TOOL_CANCELLED:") for response in self.env.responses.values()))


if __name__ == "__main__":
    unittest.main()
