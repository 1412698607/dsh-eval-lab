"""No-model acceptance for the fixed M6 suite, with real recording and inspect."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from dsh_eval.environment import StatefulEnvironment
from dsh_eval.evaluate import check_assertions, evaluate, task_view
from dsh_eval.formats import load_json, validate_experiment
from dsh_eval.runner import validate_live_case

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "fixtures/evaluation/core"
# Reference actions and answers are authored separately from the case assertions.
REFERENCES = {
    "direct-read": ([('read', 'project.md')], 'core-direct'),
    "nested-discovery": ([('list', 'docs'), ('read', 'docs/releases/current.md')], 'core-nested'),
    "reference-chain": ([('read', 'README.md'), ('read', 'docs/index.md'), ('read', 'data/project.md')], 'core-chain'),
    "current-over-archive": ([('read', 'README.md'), ('read', 'releases/current.md')], 'core-current'),
    "missing-file": ([('read', 'absent.md')], 'FILE_NOT_FOUND'),
    "empty-file": ([('read', 'empty.md')], 'EMPTY_FILE'),
    "unicode-path": ([('read', '资料/项目说明.md')], '星河评测'),
    "retry-once": ([('read', 'project.md'), ('read', 'project.md')], 'core-retry'),
    "independent-retries": ([('read', 'alpha.md'), ('read', 'alpha.md'),
                             ('read', 'beta.md'), ('read', 'beta.md')], 'ALPHA+BETA'),
    "stale-then-retry": ([('read', 'README.md'), ('read', 'docs/old.md'), ('list', 'docs'),
                          ('read', 'docs/current.md'), ('read', 'docs/current.md')], 'core-recovered'),
}


def reference_events(case, actions, answer):
    environment = StatefulEnvironment(case['environment'], 'reference-run')
    environment.bind('reference-session')
    events = [{'type': 'turn/start', 'data': {}},
              {'type': 'user/message', 'data': {'source': {'kind': 'user'},
               'content': [{'type': 'text', 'text': case['input']}]}}]
    for index, (operation, path) in enumerate(actions):
        call_id = f'call-{index}'
        response = environment.handle({'type': 'tool-request', 'bridgeVersion': 1,
            'requestId': call_id, 'caseRunId': 'reference-run', 'sessionId': 'reference-session',
            'operation': operation, 'arguments': {'path': path}})
        events.extend([
            {'type': 'tool/call', 'data': {'callId': call_id, 'name': f'eval_{operation}',
                                         'arguments': json.dumps({'path': path}, ensure_ascii=False)}},
            {'type': 'tool/result', 'data': {'message': {'toolCallId': call_id,
                'isError': response['isError'], 'content': [{'type': 'text', 'text': response['text']}]}}},
        ])
    events.extend([{'type': 'assistant/message', 'data': {'message': {'content': [{'type': 'text', 'text': answer}]}}},
                   {'type': 'turn/end', 'data': {'reason': {'kind': 'completed'}}}])
    for index, event in enumerate(events):
        event['seq'] = index
    return events


class CoreSuiteTests(unittest.TestCase):
    def record_and_evaluate(self, name, events):
        with tempfile.TemporaryDirectory(prefix='dsh-core-') as directory:
            code = """
import { recordExample } from './scripts/demo-eval.js';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const data = JSON.parse(input);
console.log(JSON.stringify(await recordExample(data.casePath, data.events, data.outputDir)));
"""
            case_path = SUITE / f'{name}.case.json'
            process = subprocess.run(['node', '--input-type=module', '-e', code], cwd=ROOT,
                input=json.dumps({'casePath': str(case_path), 'events': events, 'outputDir': directory}),
                capture_output=True, text=True, encoding='utf-8', timeout=30, check=True)
            return evaluate(case_path, json.loads(process.stdout)['evidencePath'])

    def test_manifest_has_exactly_ten_unique_live_ready_cases_and_ten_tasks(self):
        manifest = validate_experiment(load_json(SUITE / 'core.experiment.json'))
        self.assertEqual({item['entryId'] for item in manifest['cases']}, set(REFERENCES))
        self.assertEqual(len(manifest['cases']), 10)
        self.assertEqual(manifest['repetitions'] * len(manifest['configurations']) * len(manifest['cases']), 10)
        self.assertEqual(manifest['failurePolicy'], 'continue')
        self.assertEqual(manifest['configurations'][0]['configRef']['model'], 'deepseek-flash')
        identifiers = set()
        for entry in manifest['cases']:
            case = validate_live_case(load_json(SUITE / entry['casePath']))
            self.assertNotIn(case['caseId'], identifiers)
            identifiers.add(case['caseId'])
            self.assertEqual(case['configRef'], manifest['configurations'][0]['configRef'])
            self.assertEqual(case['budget'], {'timeoutSeconds': 120})

    def test_reference_actions_pass_after_real_recording_and_fresh_inspect(self):
        for name, (actions, answer) in REFERENCES.items():
            with self.subTest(case=name):
                case = load_json(SUITE / f'{name}.case.json')
                result = self.record_and_evaluate(name, reference_events(case, actions, answer))
                self.assertEqual(result['source'], 'synthetic')
                self.assertEqual(result['outcome'], 'passed', result)
                self.assertEqual(result['recording']['outcome'], 'complete')

    def test_correct_answer_without_tools_is_unevaluable(self):
        for name, (_, answer) in REFERENCES.items():
            with self.subTest(case=name):
                case = load_json(SUITE / f'{name}.case.json')
                result = self.record_and_evaluate(name, reference_events(case, [], answer))
                self.assertEqual(result['recording']['outcome'], 'complete')
                self.assertEqual(result['outcome'], 'unevaluable')
                self.assertEqual(result['assertions']['outcome'], 'insufficient_evidence')

    def test_wrong_answer_with_valid_tools_is_failed(self):
        for name, (actions, _) in REFERENCES.items():
            with self.subTest(case=name):
                case = load_json(SUITE / f'{name}.case.json')
                result = self.record_and_evaluate(name, reference_events(case, actions, 'WRONG_ANSWER'))
                self.assertEqual(result['recording']['outcome'], 'complete')
                self.assertEqual(result['outcome'], 'failed', result)

    def test_required_step_order_is_enforced(self):
        variants = {
            'nested-discovery': [('read', 'docs/releases/current.md'), ('list', 'docs')],
            'reference-chain': [('read', 'data/project.md'), ('read', 'docs/index.md'), ('read', 'README.md')],
            'current-over-archive': [('read', 'releases/current.md'), ('read', 'README.md')],
            'stale-then-retry': [('read', 'docs/current.md'), ('read', 'docs/current.md'),
                                 ('list', 'docs'), ('read', 'docs/old.md'), ('read', 'README.md')],
        }
        for name, actions in variants.items():
            with self.subTest(case=name):
                case = load_json(SUITE / f'{name}.case.json')
                result = self.record_and_evaluate(name, reference_events(case, actions, REFERENCES[name][1]))
                self.assertEqual(result['recording']['outcome'], 'complete')
                self.assertEqual(result['outcome'], 'failed', result)

    def test_followup_call_must_wait_for_prerequisite_result(self):
        for name in ('nested-discovery', 'retry-once'):
            with self.subTest(case=name):
                case = load_json(SUITE / f'{name}.case.json')
                events = reference_events(case, *REFERENCES[name])
                events[3], events[4] = events[4], events[3]
                for seq, event in enumerate(events):
                    event['seq'] = seq
                result = self.record_and_evaluate(name, events)
                self.assertEqual(result['recording']['outcome'], 'complete')
                self.assertEqual(result['outcome'], 'failed', result)

    def test_empty_file_requires_exact_empty_tool_text(self):
        name = 'empty-file'
        case = load_json(SUITE / f'{name}.case.json')
        for texts in (['This file is NOT empty.'], [' \n'], ['', 'nonempty']):
            with self.subTest(texts=texts):
                events = reference_events(case, *REFERENCES[name])
                events[3]['data']['message']['content'] = [{'type': 'text', 'text': text} for text in texts]
                result = self.record_and_evaluate(name, events)
                self.assertEqual(result['recording']['outcome'], 'complete')
                self.assertEqual(result['outcome'], 'failed', result)

    def test_independent_retry_paths_can_interleave(self):
        name = 'independent-retries'
        case = load_json(SUITE / f'{name}.case.json')
        for paths in (['alpha.md', 'beta.md', 'alpha.md', 'beta.md'],
                      ['beta.md', 'beta.md', 'alpha.md', 'alpha.md']):
            with self.subTest(paths=paths):
                actions = [('read', path) for path in paths]
                result = self.record_and_evaluate(name, reference_events(case, actions, REFERENCES[name][1]))
                self.assertEqual(result['outcome'], 'passed', result)

    def test_later_valid_chain_can_pass_after_extra_calls(self):
        name = 'nested-discovery'
        case = load_json(SUITE / f'{name}.case.json')
        actions = [('read', 'docs/releases/current.md'), *REFERENCES[name][0]]
        result = self.record_and_evaluate(name, reference_events(case, actions, REFERENCES[name][1]))
        self.assertEqual(result['outcome'], 'passed', result)

    def test_each_required_tool_result_is_necessary(self):
        for name, (actions, answer) in REFERENCES.items():
            case = load_json(SUITE / f'{name}.case.json')
            events = reference_events(case, actions, answer)
            for index, assertion in enumerate(case['assertions'][:-2]):
                with self.subTest(case=name, assertion=assertion['id']):
                    variant = copy.deepcopy(events)
                    del variant[2 + index * 2:4 + index * 2]
                    for seq, event in enumerate(variant):
                        event['seq'] = seq
                    results = check_assertions(case['assertions'], task_view(variant, case['input']))
                    result = next(row for row in results if row['id'] == assertion['id'])
                    self.assertNotEqual(result['outcome'], 'passed', result)

    def test_root_listing_is_also_valid_and_retry_state_resets(self):
        for name in ('nested-discovery', 'stale-then-retry', 'retry-once', 'independent-retries'):
            with self.subTest(case=name):
                case = load_json(SUITE / f'{name}.case.json')
                actions, answer = REFERENCES[name]
                actions = [(operation, '.' if operation == 'list' else path) for operation, path in actions]
                first = reference_events(case, actions, answer)
                self.assertEqual(first, reference_events(case, actions, answer))
                view = task_view(first, case['input'])
                self.assertTrue(all(row['outcome'] == 'passed' for row in check_assertions(case['assertions'], view)))


if __name__ == '__main__':
    unittest.main()
