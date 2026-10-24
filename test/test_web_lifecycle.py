"""M6.4 synthetic acceptance rules, real child exits, recording and fresh inspect."""
import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dsh_eval.formats import load_json, validate_case
from scripts.verify_web_lifecycle import check_events, main, validate_capture, verify_launch, verify_recorded_task

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "fixtures/evaluation/web-lifecycle.case.json"


def reference_events():
    # Independent reference values; do not derive expected answers from the assertions.
    return [
        {"seq": 0, "type": "turn/start", "data": {"turn": 1}},
        {"seq": 1, "type": "user/message", "data": {"source": {"kind": "user"},
         "content": [{"type": "text", "text": load_json(CASE)["input"]}]}},
        {"seq": 2, "type": "tool/call", "data": {"callId": "read-1", "name": "read", "arguments": '{"file_path":"README.md"}'}},
        {"seq": 3, "type": "tool/result", "data": {"message": {"toolCallId": "read-1", "isError": False,
         "content": [{"type": "text", "text": "projectName: dsh-eval-web-fixture\n"}]}}},
        {"seq": 4, "type": "assistant/message", "data": {"message": {"content": [{"type": "text", "text": "dsh-eval-web-fixture"}]}}},
        {"seq": 5, "type": "turn/end", "data": {"reason": {"kind": "completed"}}},
    ]


def resequence(events):
    for index, event in enumerate(events):
        event["seq"] = index
    return events


class WebLifecycleEventTests(unittest.TestCase):
    def setUp(self):
        self.case = validate_case(load_json(CASE))

    def test_web_case_and_completed_tool_evidence(self):
        self.assertEqual(self.case["configRef"]["profile"], "web")
        result = check_events(reference_events(), self.case, "normal-exit", 5)
        self.assertEqual(result["outcome"], "passed")
        self.assertEqual(result["assertions"]["outcome"], "passed")

    def test_runtime_context_and_skill_catalog_are_not_extra_user_tasks(self):
        events = reference_events()
        events[2:2] = [{"type": "user/message", "data": {"source": {"kind": source},
                       "content": [{"type": "text", "text": "Injected context"}]}}
                      for source in ("runtime-context", "skill-catalog")]
        resequence(events)
        result = check_events(events, self.case, "normal-exit", events[-1]["seq"])
        self.assertEqual(result["outcome"], "passed")

    def test_wrong_answer_or_result_is_a_task_failure(self):
        for index in (3, 4):
            events = reference_events()
            events[index]["data"]["message"]["content"][0]["text"] = "WRONG"
            self.assertEqual(check_events(events, self.case, "normal-exit", 5)["outcome"], "failed")

    def test_correct_answer_without_result_does_not_pass(self):
        events = resequence([event for event in reference_events() if event["type"] != "tool/result"])
        result = check_events(events, self.case, "normal-exit", events[-1]["seq"])
        self.assertEqual(result["outcome"], "unevaluable")
        self.assertEqual(result["assertions"]["outcome"], "insufficient_evidence")

    def test_orphan_result_wrong_arguments_and_reversed_tools_do_not_pass(self):
        for mutation in (lambda events: events[3]["data"]["message"].update(toolCallId="other"),
                         lambda events: events[2]["data"].update(arguments='{"path":"README.md"}'),
                         lambda events: events.__setitem__(slice(2, 4), events[2:4][::-1])):
            events = reference_events()
            mutation(events)
            resequence(events)
            try:
                result = check_events(events, self.case, "normal-exit", 5)
            except ValueError:
                continue
            self.assertNotEqual(result["outcome"], "passed")

    def test_cancel_needs_matching_task_user_reason_and_later_end(self):
        events = [*reference_events()[:2], {"seq": 2, "type": "turn/end",
                  "data": {"reason": {"kind": "aborted", "reason": {"kind": "user"}}}}]
        result = check_events(events, self.case, "page-cancel", 1)
        self.assertEqual(result["execution"]["status"], "cancelled")
        self.assertEqual(result["outcome"], "unevaluable")
        self.assertEqual(result["assertions"]["outcome"], "not_run")
        for change in (lambda rows: rows[2]["data"]["reason"]["reason"].update(kind="disposed"),
                       lambda rows: rows[1]["data"]["content"][0].update(text="different task"),
                       lambda rows: rows.pop(1)):
            changed = copy.deepcopy(events)
            change(changed)
            with self.assertRaises(ValueError):
                check_events(changed, self.case, "page-cancel", 1)
        with self.assertRaises(ValueError):
            check_events(events, self.case, "page-cancel", 2)

    def test_interruption_requires_started_unfinished_task_at_observed_prefix(self):
        result = check_events(reference_events()[:3], self.case, "process-interrupt", 2)
        self.assertEqual(result["execution"]["status"], "interrupted")
        self.assertEqual(result["assertions"]["outcome"], "not_run")
        for events, checkpoint in ((reference_events(), 5), (reference_events()[:1], 0), (reference_events()[:3], 1)):
            with self.subTest(checkpoint=checkpoint), self.assertRaises(ValueError):
                check_events(events, self.case, "process-interrupt", checkpoint)

    def test_multiple_tasks_gaps_and_evidence_after_end_rejected(self):
        variants = [reference_events() + [{"seq": 6, "type": "user/message", "data": {}}],
                    reference_events() + [{"seq": 6, "type": "tool/call", "data": {}}]]
        gap = reference_events()
        gap[3]["seq"] = 99
        variants.append(gap)
        for events in variants:
            with self.assertRaises(ValueError):
                check_events(events, self.case, "normal-exit", 5)


class WebLifecycleProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="dsh-web-lifecycle-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.captures = cls.root / "captures"
        process = subprocess.run(["node", str(ROOT / "scripts/check-web-lifecycle.js"), str(cls.captures)],
                                 cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=100)
        if process.returncode:
            raise AssertionError(f"Real lifecycle fixture failed: {process.stdout}\n{process.stderr}")

    def copied(self, scenario="normal-exit"):
        directory = self.root / f"copy-{self._testMethodName}"
        shutil.copytree(self.captures / scenario, directory)
        return directory

    def save_capture(self, directory, value):
        (directory / "lifecycle.json").write_text(json.dumps(value), encoding="utf-8")

    def directory_alias(self, alias, target):
        if os.name == "nt":
            subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(alias), str(target.resolve())],
                           capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            self.addCleanup(alias.rmdir)
        else:
            alias.symlink_to(target.resolve(), target_is_directory=True)
            self.addCleanup(alias.unlink)
        return alias

    def save_checkpoint(self, directory, count):
        capture = load_json(directory / "lifecycle.json")
        run_dir = directory / capture["runDir"]
        trace = next(run_dir.glob("*.jsonl"))
        prefix = trace.read_bytes().splitlines(keepends=True)[:count]
        events = [json.loads(line)["event"] for line in prefix]
        status_path = next(run_dir.glob("*.status.json"))
        status = load_json(status_path)
        status.update(writtenCount=len(prefix), writtenBytes=sum(map(len, prefix)),
                      firstSeq=events[0]["seq"] if events else None,
                      lastSeq=events[-1]["seq"] if events else None,
                      sha256=hashlib.sha256(b"".join(prefix)).hexdigest())
        status_path.write_text(json.dumps(status), encoding="utf-8")

    def test_three_real_child_processes_keep_task_and_lifecycle_outcomes_separate(self):
        pids = set()
        for scenario, execution, recording, outcome in (
                ("normal-exit", "completed", "complete", "passed"),
                ("page-cancel", "cancelled", "complete", "unevaluable"),
                ("process-interrupt", "interrupted", "unverified", "unevaluable")):
            with self.subTest(scenario=scenario):
                result = verify_launch(self.captures / scenario)
                self.assertTrue(result["verified"], result)
                self.assertFalse(result["liveWebVerified"])
                self.assertEqual(result["source"], "synthetic")
                self.assertEqual(result["execution"]["status"], execution)
                self.assertEqual(result["recording"]["outcome"], recording)
                self.assertEqual(result["outcome"], outcome)
                self.assertTrue(result["process"]["closed"])
                pids.add(result["process"]["pid"])
        self.assertEqual(len(pids), 3)

    def test_source_version_unknown_fields_and_boolean_facts_rejected(self):
        original = load_json(self.captures / "normal-exit/lifecycle.json")
        for mutation in (lambda value: value.update(source="live"),
                         lambda value: value.update(webLifecycleFormatVersion=True),
                         lambda value: value.update(verified=True),
                         lambda value: value["process"].update(pid=True),
                         lambda value: value["process"].update(exitCode=False),
                         lambda value: value["process"].update(closed=1),
                         lambda value: value["operation"].update(afterSeq=True)):
            value = copy.deepcopy(original)
            mutation(value)
            with self.assertRaises(ValueError):
                validate_capture(value)

    def test_timeout_fallback_open_process_and_ipc_cancel_cannot_claim_expected_scenario(self):
        for scenario in ("normal-exit", "page-cancel", "process-interrupt"):
            original = load_json(self.captures / scenario / "lifecycle.json")
            for mutation in (lambda value: value["process"].update(intervention="timeout"),
                             lambda value: value["process"].update(closed=False),
                             lambda value: value["process"].update(error="EPERM"),
                             lambda value: value["operation"].update(kind="agent-cancel-after-stream-chunk")):
                value = copy.deepcopy(original)
                mutation(value)
                with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                    validate_capture(value)

    def test_fresh_inspect_rejects_corruption_after_a_saved_success(self):
        directory = self.copied()
        previous = verify_launch(directory)
        self.assertTrue(previous["verified"])
        (directory / "verification.json").write_text(json.dumps(previous), encoding="utf-8")
        capture = load_json(directory / "lifecycle.json")
        run_dir = directory / capture["runDir"]
        trace = next(run_dir.glob("*.jsonl"))
        trace.write_bytes(trace.read_bytes()[:-1])
        result = verify_launch(directory)
        self.assertFalse(result["verified"])
        self.assertEqual(result["recording"]["outcome"], "invalid")
        self.assertEqual(result["assertions"]["outcome"], "not_run")

    def test_missing_whole_session_pair_cannot_claim_interruption(self):
        directory = self.copied("process-interrupt")
        capture = load_json(directory / "lifecycle.json")
        run_dir = directory / capture["runDir"]
        for path in [*run_dir.glob("*.jsonl"), *run_dir.glob("*.status.json")]:
            path.unlink()
        result = verify_launch(directory)
        self.assertFalse(result["verified"])
        self.assertEqual(result["outcome"], "unevaluable")

    def test_sealed_success_cannot_be_relabelled_as_an_in_task_interruption(self):
        directory = self.copied()
        capture = load_json(directory / "lifecycle.json")
        capture.update(scenario="process-interrupt")
        capture["operation"].update(kind="process-kill", signal="SIGKILL")
        capture["process"].update(exitCode=None, signal="SIGKILL", forceStopped=True, intervention="expected-interrupt")
        self.save_capture(directory, capture)
        result = verify_launch(directory)
        self.assertFalse(result["verified"])
        self.assertEqual(result["recording"]["outcome"], "complete")
        self.assertEqual(result["assertions"]["outcome"], "not_run")

    def test_interruption_rejects_unsupported_recording_metadata_versions(self):
        directory = self.copied("process-interrupt")
        capture = load_json(directory / "lifecycle.json")
        manifest_path = directory / capture["runDir"] / "run.json"
        original = load_json(manifest_path)
        versions = [("statusFormatVersion", value) for value in (2, True, None, "1", 1.0)]
        versions.extend((("formatVersion", 3), ("runManifestFormatVersion", 2)))
        for field, version in versions:
            with self.subTest(field=field, version=version):
                manifest_path.write_text(json.dumps({**original, field: version}), encoding="utf-8")
                result = verify_launch(directory)
                self.assertFalse(result["verified"], result)
                self.assertEqual(result["outcome"], "unevaluable")
                self.assertEqual(result["assertions"]["outcome"], "not_run")

    def test_interruption_requires_checkpoint_covering_operation(self):
        directory = self.copied("process-interrupt")
        for count in (0, 1, 2):
            with self.subTest(checkpoint_count=count):
                self.save_checkpoint(directory, count)
                result = verify_launch(directory)
                # A valid older prefix remains unverified in the general inspector.
                self.assertEqual(result["recording"]["outcome"], "unverified")
                self.assertFalse(result["verified"], result)
                self.assertEqual(result["outcome"], "unevaluable")
                self.assertEqual(result["assertions"]["outcome"], "not_run")

    def test_interruption_accepts_checkpoint_with_nonzero_sequence_origin(self):
        directory = self.copied("process-interrupt")
        capture = load_json(directory / "lifecycle.json")
        run_dir = directory / capture["runDir"]
        trace = next(run_dir.glob("*.jsonl"))
        rows = [json.loads(line) for line in trace.read_bytes().splitlines()]
        for row in rows:
            row["event"]["seq"] += 10
        trace.write_bytes(b"".join((json.dumps(row) + "\n").encode("utf-8") for row in rows))
        capture["operation"]["afterSeq"] += 10
        self.save_capture(directory, capture)
        self.save_checkpoint(directory, len(rows))
        result = verify_launch(directory)
        self.assertTrue(result["verified"], result)
        self.assertEqual(result["execution"]["status"], "interrupted")
        self.assertEqual(result["outcome"], "unevaluable")

    def test_live_tail_policy_still_requires_operation_checkpoint_coverage(self):
        directory = self.copied("process-interrupt")
        capture = load_json(directory / "lifecycle.json")
        case = validate_case(load_json(directory / "case.json"))
        self.save_checkpoint(directory, 2)
        capture["operation"]["afterSeq"] = 1
        result = {}
        verify_recorded_task(directory, capture, case, result, allow_unconfirmed_tail=True)
        self.assertEqual(result["execution"]["status"], "interrupted")
        with self.assertRaises(ValueError):
            verify_recorded_task(directory, capture, case, {})
        capture["operation"]["afterSeq"] = 2
        with self.assertRaises(ValueError):
            verify_recorded_task(directory, capture, case, {}, allow_unconfirmed_tail=True)
        capture["operation"]["afterSeq"] = 1
        self.save_checkpoint(directory, 0)
        with self.assertRaises(ValueError):
            verify_recorded_task(directory, capture, case, {}, allow_unconfirmed_tail=True)

    def test_shared_helper_accepts_directory_alias(self):
        for scenario, status in (("normal-exit", "completed"), ("page-cancel", "cancelled"),
                                 ("process-interrupt", "interrupted")):
            directory = self.captures / scenario
            alias = self.directory_alias(self.root / f"alias-{scenario}", directory)
            self.assertNotEqual(alias, alias.resolve())
            capture = load_json(directory / "lifecycle.json")
            case = validate_case(load_json(directory / "case.json"))
            for live_tail in (False, True):
                with self.subTest(scenario=scenario, live_tail=live_tail):
                    result = {}
                    verify_recorded_task(alias, capture, case, result, allow_unconfirmed_tail=live_tail)
                    self.assertEqual(result["execution"]["status"], status)

    def test_shared_helper_normalizes_parent_path(self):
        directory = self.copied()
        (directory / "via").mkdir()
        alias = directory / "via" / ".."
        self.assertNotEqual(alias, alias.resolve())
        result = {}
        verify_recorded_task(alias, load_json(directory / "lifecycle.json"),
                             validate_case(load_json(directory / "case.json")), result)
        self.assertEqual(result["outcome"], "passed")

    def test_shared_helper_still_rejects_resolved_escape(self):
        directory = self.root / "escape-capture"
        directory.mkdir()
        source = self.captures / "normal-exit"
        self.directory_alias(directory / "traces", source / "traces")
        capture = load_json(source / "lifecycle.json")
        case = validate_case(load_json(source / "case.json"))
        with patch("scripts.verify_web_lifecycle.inspect_recording", side_effect=AssertionError("Must reject before inspect")):
            with self.assertRaisesRegex(ValueError, "Trace directory escapes"):
                verify_recorded_task(directory, capture, case, {})

    def test_interruption_rejects_pending_status_replacement(self):
        directory = self.copied("process-interrupt")
        capture = load_json(directory / "lifecycle.json")
        run_dir = directory / capture["runDir"]
        (run_dir / "run.json.incomplete.tmp").write_text("{}", encoding="utf-8")
        result = verify_launch(directory)
        self.assertEqual(result["recording"]["outcome"], "unverified")
        self.assertFalse(result["verified"], result)
        self.assertEqual(result["assertions"]["outcome"], "not_run")

    def test_cli_rejects_unsupported_version_and_uncovered_checkpoint(self):
        directory = self.copied("process-interrupt")
        capture = load_json(directory / "lifecycle.json")
        manifest_path = directory / capture["runDir"] / "run.json"
        original = load_json(manifest_path)
        for variant in ("unsupported-version", "uncovered-checkpoint"):
            with self.subTest(variant=variant):
                manifest_path.write_text(json.dumps({**original, "statusFormatVersion":
                                                    2 if variant == "unsupported-version" else 1}), encoding="utf-8")
                if variant == "uncovered-checkpoint":
                    self.save_checkpoint(directory, 0)
                output = io.StringIO()
                with redirect_stdout(output):
                    exit_code = main([str(directory)])
                result = json.loads(output.getvalue())
                self.assertEqual(exit_code, 1, result)
                self.assertFalse(result["verified"], result)
                self.assertFalse(result["liveWebVerified"])

    def test_wrong_run_session_and_external_paths_rejected(self):
        directory = self.copied()
        original = load_json(directory / "lifecycle.json")
        for changes in ({"sessionId": "another-session"}, {"runId": "not-a-uuid"},
                        {"runDir": "../outside"}, {"runDir": "//invalid-server/share"}):
            self.save_capture(directory, {**original, **changes})
            result = verify_launch(directory)
            self.assertFalse(result["verified"], result)

    def test_unavailable_inspect_is_not_evidence_of_a_successful_interruption(self):
        with patch("dsh_eval.evaluate.subprocess.run", side_effect=FileNotFoundError("node unavailable")):
            result = verify_launch(self.captures / "process-interrupt")
        self.assertFalse(result["verified"])
        self.assertEqual(result["recording"]["outcome"], "unverified")
        self.assertIn("Fresh inspect unavailable", result["reasons"][0])

    def test_cli_rechecks_and_never_overwrites_an_existing_output(self):
        output = self.root / "cli-verification.json"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(self.captures / "page-cancel"), "--output", str(output)]), 0)
            previous = output.read_bytes()
            self.assertEqual(main([str(self.captures / "page-cancel"), "--output", str(output)]), 1)
            self.assertEqual(output.read_bytes(), previous)
            self.assertEqual(main([str(self.root / "missing")]), 1)

    def test_capture_command_refuses_to_overwrite_a_previous_directory(self):
        manifest = (self.captures / "normal-exit/lifecycle.json").read_bytes()
        process = subprocess.run(["node", str(ROOT / "scripts/check-web-lifecycle.js"), str(self.captures)],
                                 cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual((self.captures / "normal-exit/lifecycle.json").read_bytes(), manifest)


if __name__ == "__main__":
    unittest.main()
