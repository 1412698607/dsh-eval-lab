import copy
import unittest
from scripts.verify_live import check_task_events


def read_events():
    return [
        {"type": "user/message", "seq": 0, "data": {"source": {"kind": "user"},
         "content": [{"type": "text", "text": "Read README.md and return projectName"}]}},
        {"type": "tool/call", "seq": 1, "data": {"callId": "actual-call", "name": "host-specific-file-tool",
         "arguments": '{"path":"README.md"}'}},
        {"type": "tool/result", "seq": 2, "data": {"message": {"toolCallId": "actual-call", "isError": False,
         "content": [{"type": "text", "text": "projectName: fixture"}]}}},
        {"type": "assistant/message", "seq": 3, "data": {"message": {"content": [{"type": "text", "text": "fixture"}]}}},
        {"type": "turn/end", "seq": 4, "data": {"reason": {"kind": "completed"}}},
    ]


class LiveEvidenceTests(unittest.TestCase):
    def test_host_tool_name_is_not_hardcoded(self):
        self.assertEqual(check_task_events(read_events(), "read", "fixture")["toolName"], "host-specific-file-tool")

    def test_answer_without_actual_read_result_is_rejected(self):
        with self.assertRaises(ValueError):
            check_task_events([event for event in read_events() if event["type"] != "tool/result"], "read", "fixture")

    def test_unrelated_call_result_and_failed_read_are_rejected(self):
        for key, value in [("toolCallId", "unrelated-call"), ("isError", True)]:
            events = copy.deepcopy(read_events())
            events[2]["data"]["message"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_task_events(events, "read", "fixture")

    def test_wrong_field_and_result_after_answer_are_rejected(self):
        for mutate in [lambda events: events[3]["data"]["message"]["content"][0].update(text="wrong"),
                       lambda events: events[2].update(seq=5)]:
            events = copy.deepcopy(read_events())
            mutate(events)
            with self.assertRaises(ValueError):
                check_task_events(events, "read", "fixture")

    def test_missing_file_requires_actual_error_then_response(self):
        events = copy.deepcopy(read_events())
        events[0]["data"]["content"][0]["text"] = "Read missing-m2-3.txt"
        events[1]["data"]["arguments"] = '{"file_path":"missing-m2-3.txt"}'
        events[2]["data"]["message"].update(isError=True)
        events[3]["data"]["message"]["content"][0]["text"] = "missing-m2-3.txt does not exist."
        self.assertEqual(check_task_events(events, "missing", "fixture")["resultSeq"], 2)
        events[2]["data"]["message"].update(isError=False)
        with self.assertRaises(ValueError):
            check_task_events(events, "missing", "fixture")

    def test_only_user_cancellation_is_accepted(self):
        event = {"type": "turn/end", "seq": 1, "data": {"reason": {"kind": "aborted", "reason": {"kind": "user"}}}}
        check_task_events([event], "cancel", "fixture")
        event["data"]["reason"]["reason"]["kind"] = "disposed"
        with self.assertRaises(ValueError):
            check_task_events([event], "cancel", "fixture")
