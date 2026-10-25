"""Artificial metadata regression only; actual browser/model acceptance is separate."""
import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.verify_web_live import main, validate_live, verify_live


def at(second):
    return f"2026-10-24T08:00:{second:02d}+00:00"


def reference(scenario="normal-exit"):
    run_id = "11111111-1111-4111-8111-111111111111"
    interrupted = scenario == "process-interrupt"
    capture = {"liveWebLifecycleFormatVersion": 1, "source": "live", "scenario": scenario,
               "runId": run_id, "sessionId": "test-session", "runDir": f"traces/{run_id}",
               "platform": "win32", "cliVersion": "0.2.0-rc.2", "nodePtyVersion": "test-only",
               "url": "http://127.0.0.1:12345", "startedAt": at(0), "finishedAt": at(20),
               "operation": {"kind": "process-kill" if interrupted else "page-cancel" if scenario == "page-cancel" else "console-ctrl-c",
                             "afterSeq": 10, "at": at(4 if scenario != "normal-exit" else 12),
                             "requestedSignal": "SIGKILL" if interrupted else None if scenario == "page-cancel" else "SIGINT"},
               "process": {"pid": 123, "closed": True, "exitCode": 1 if interrupted else 130, "signal": None,
                           "forceStopped": interrupted, "intervention": "expected-interrupt" if interrupted else "console-shutdown",
                           "error": None}}
    observations = [{"observationVersion": 1, "at": at(3), "kind": "model/first-chunk", "pid": 123, "sessionId": "test-session"}]
    if not interrupted:
        observations += [{"observationVersion": 1, "at": at(10), "kind": "session/event", "type": "turn/end", "pid": 123},
                         {"observationVersion": 1, "at": at(15), "kind": "process/SIGINT", "pid": 123},
                         {"observationVersion": 1, "at": at(16), "kind": "observer/disposed", "pid": 123}]
    actions = [{"kind": "submit", "at": at(1), "url": capture["url"], "control": "test-only submit button"}]
    if scenario == "page-cancel":
        actions.append({"kind": "cancel", "at": at(5), "url": capture["url"], "control": "test-only stop button"})
    return capture, observations, {"webUiActionsVersion": 1, "driver": "cua", "actions": actions}


class LiveWebMetadataTests(unittest.TestCase):
    def test_late_environment_or_route_failure_cannot_report_task_pass(self):
        # Artificial metadata and task facts isolate the final live gate. Real recording
        # inspection is exercised independently by the lifecycle process regressions.
        with tempfile.TemporaryDirectory(prefix="web-live-gates-") as temporary:
            directory = Path(temporary)
            capture, observations, ui = reference()
            observed = {"observationVersion": 1, "at": at(2), "kind": "session/event", "pid": 123,
                        "sessionId": "test-session", "type": "request/header", "seq": 0,
                        "cwd": str(directory / "actual-workspace")}
            observations.insert(0, observed)
            case = json.loads((Path(__file__).resolve().parents[1] / "fixtures/evaluation/web-lifecycle.case.json").read_text(encoding="utf-8"))
            for name, value in {"lifecycle-live.json": capture, "ui-actions.json": ui, "case.json": case}.items():
                (directory / name).write_text(json.dumps(value), encoding="utf-8")
            (directory / "observations.jsonl").write_text("".join(json.dumps(item) + "\n" for item in observations), encoding="utf-8")

            for route_match in (True, False):
                with self.subTest(route_match=route_match):
                    expected = observed["cwd"] if not route_match else str(directory / "unrelated-workspace")
                    (directory / "setup.json").write_text(json.dumps({"workspace": expected}), encoding="utf-8")

                    def task_facts(_directory, _capture, _case, result, **_options):
                        result.update(execution={"status": "completed"}, recording={"outcome": "complete"},
                                      assertions={"outcome": "passed"}, outcome="passed")
                        return [{"seq": 0, "type": "request/header", "data": {"header": {"config": {
                            "provider": case["configRef"]["provider"],
                            "model": case["configRef"]["model"] if route_match else "unrelated-model"}}}}]

                    with patch("scripts.verify_web_live.verify_recorded_task", side_effect=task_facts):
                        result = verify_live(directory)
                    self.assertFalse(result["verified"])
                    self.assertFalse(result["liveWebVerified"])
                    self.assertEqual(result["outcome"], "unevaluable")
                    self.assertEqual(result["assertions"]["outcome"], "passed")
                    self.assertTrue(result["reasons"])

    def test_three_reference_metadata_shapes(self):
        for scenario in ("normal-exit", "page-cancel", "process-interrupt"):
            with self.subTest(scenario=scenario):
                capture, observations, ui = reference(scenario)
                self.assertIs(validate_live(capture, observations, ui), capture)

    def test_source_version_platform_and_boolean_process_facts_rejected(self):
        original, observations, ui = reference()
        for change in ({"source": "synthetic"}, {"liveWebLifecycleFormatVersion": True}, {"platform": "linux"},
                       {"cliVersion": "future"}, {"runDir": "../outside"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_live({**original, **change}, observations, ui)
        for change in ({"pid": True}, {"closed": 1}, {"exitCode": True}, {"forceStopped": 0}):
            capture = copy.deepcopy(original)
            capture["process"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_live(capture, observations, ui)

    def test_missing_or_unassociated_model_stream_cannot_claim_live(self):
        capture, observations, ui = reference()
        for changed in (observations[1:], [{**observations[0], "sessionId": "other"}, *observations[1:]],
                        [{**observations[0], "pid": 999}, *observations[1:]]):
            with self.assertRaises(ValueError):
                validate_live(capture, changed, ui)

    def test_real_console_signal_disposal_and_exit_are_required(self):
        capture, observations, ui = reference()
        for kind in ("process/SIGINT", "observer/disposed"):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validate_live(capture, [item for item in observations if item["kind"] != kind], ui)
        for change in ({"exitCode": 0}, {"intervention": "ipc-shutdown"}, {"forceStopped": True}):
            changed = copy.deepcopy(capture)
            changed["process"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_live(changed, observations, ui)

    def test_cancel_needs_actual_page_action_in_observed_interval(self):
        capture, observations, ui = reference("page-cancel")
        for change in ({"driver": "agent-api"}, {"actions": ui["actions"][:1]},
                       {"actions": [ui["actions"][0], {**ui["actions"][1], "at": at(11)}]},
                       {"actions": [ui["actions"][0], {**ui["actions"][1], "url": "http://127.0.0.1:9999"}]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_live(capture, observations, {**ui, **change})

    def test_normal_console_operation_must_follow_end_and_precede_sigint(self):
        capture, observations, ui = reference()
        for second in (1, 9, 16, 19):
            changed = copy.deepcopy(capture)
            changed["operation"]["at"] = at(second)
            with self.subTest(second=second), self.assertRaises(ValueError):
                validate_live(changed, observations, ui)
        for second in (10, 12, 15):
            changed = copy.deepcopy(capture)
            changed["operation"]["at"] = at(second)
            with self.subTest(boundary=second):
                self.assertIs(validate_live(changed, observations, ui), changed)

    def test_console_disposal_must_be_unique_and_follow_sigint(self):
        for scenario in ("normal-exit", "page-cancel"):
            capture, observations, ui = reference(scenario)
            for second in (3, 9, 10, 14):
                changed = copy.deepcopy(observations)
                next(item for item in changed if item["kind"] == "observer/disposed")["at"] = at(second)
                changed.sort(key=lambda item: item["at"])
                with self.subTest(scenario=scenario, second=second), self.assertRaises(ValueError):
                    validate_live(capture, changed, ui)
            with self.subTest(scenario=scenario, duplicate=True), self.assertRaises(ValueError):
                validate_live(capture, [*observations, observations[-1]], ui)
            for second in (15, 16, 20):
                changed = copy.deepcopy(observations)
                changed[-1]["at"] = at(second)
                with self.subTest(scenario=scenario, boundary=second):
                    self.assertIs(validate_live(capture, changed, ui), capture)

    def test_equal_console_lifecycle_timestamps_are_accepted(self):
        for scenario in ("normal-exit", "page-cancel"):
            capture, observations, ui = reference(scenario)
            for item in observations[1:]:
                item["at"] = at(10)
            if scenario == "normal-exit":
                capture["operation"]["at"] = at(10)
            self.assertIs(validate_live(capture, observations, ui), capture)

    def test_interrupt_rejects_finished_task_timeout_and_wrong_signal(self):
        original, observations, ui = reference("process-interrupt")
        ended = [*observations, {"observationVersion": 1, "at": at(5), "kind": "session/event", "type": "turn/end", "pid": 123}]
        with self.assertRaises(ValueError):
            validate_live(original, ended, ui)
        for change in ({"intervention": "timeout"}, {"forceStopped": False}, {"exitCode": 0}):
            capture = copy.deepcopy(original)
            capture["process"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_live(capture, observations, ui)
        capture = copy.deepcopy(original)
        capture["operation"]["requestedSignal"] = "SIGINT"
        with self.assertRaises(ValueError):
            validate_live(capture, observations, ui)

    def test_duplicate_tasks_reversed_times_and_credential_urls_rejected(self):
        capture, observations, ui = reference()
        for change in ({"actions": ui["actions"] * 2},
                       {"actions": [{**ui["actions"][0], "at": at(4)}]}):
            with self.assertRaises(ValueError):
                validate_live(capture, observations, {**ui, **change})
        with self.assertRaises(ValueError):
            validate_live(capture, observations[::-1], ui)
        with self.assertRaises(ValueError):
            validate_live({**capture, "url": capture["url"] + "?token=private"}, observations, ui)

    def test_missing_capture_and_cli_do_not_promote_a_source_label(self):
        with tempfile.TemporaryDirectory(prefix="web-live-metadata-") as temporary:
            directory = Path(temporary)
            (directory / "lifecycle.json").write_text('{"source":"live"}', encoding="utf-8")
            result = verify_live(directory)
            self.assertFalse(result["verified"])
            self.assertFalse(result["liveWebVerified"])
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main([str(directory)]), 1)
            self.assertFalse(json.loads(output.getvalue())["liveWebVerified"])


if __name__ == "__main__":
    unittest.main()
