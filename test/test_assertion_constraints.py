"""Format and causal-order boundaries for optional tool-result constraints."""
import copy
import unittest

from dsh_eval.evaluate import check_assertion, check_assertions, task_view
from dsh_eval.formats import validate_case


def constrained_case():
    return {
        'caseFormatVersion': 2, 'caseId': 'constraints', 'input': 'Read a, then b.',
        'environment': {'files': {'a.txt': '', 'b.txt': ''}},
        'configRef': {'provider': 'test', 'model': 'test', 'profile': 'headless', 'pluginVersion': '0.1.2'},
        'budget': {'timeoutSeconds': 1},
        'assertions': [
            {'id': 'first', 'type': 'tool_result', 'tool': 'eval_read', 'arguments': {'path': 'a.txt'},
             'result': {'isError': False, 'textEquals': ''}},
            {'id': 'second', 'type': 'tool_result', 'tool': 'eval_read', 'arguments': {'path': 'b.txt'},
             'result': {'isError': False}, 'after': 'first'},
        ],
    }


def scheduled_view(schedule):
    events = [{'type': 'user/message', 'data': {'source': {'kind': 'user'},
               'content': [{'type': 'text', 'text': 'Read a, then b.'}]}}]
    for operation, call_id, value in schedule:
        if operation == 'call':
            events.append({'type': 'tool/call', 'data': {'callId': call_id, 'name': 'eval_read',
                           'arguments': '{"path":"' + value + '"}'}})
        else:
            events.append({'type': 'tool/result', 'data': {'message': {'toolCallId': call_id,
                           'isError': False, 'content': [{'type': 'text', 'text': text} for text in value]}}})
    events.extend([
        {'type': 'assistant/message', 'data': {'message': {'content': [{'type': 'text', 'text': 'done'}]}}},
        {'type': 'turn/end', 'data': {'reason': {'kind': 'completed'}}},
    ])
    for seq, event in enumerate(events):
        event['seq'] = seq
    return task_view(events, 'Read a, then b.')


class ConstraintFormatTests(unittest.TestCase):
    def test_optional_constraints_are_valid_without_rewriting_case(self):
        for version in (1, 2):
            with self.subTest(version=version):
                case = constrained_case()
                case['caseFormatVersion'] = version
                before = copy.deepcopy(case)
                self.assertEqual(validate_case(case), before)
                self.assertEqual(case, before)

    def test_after_requires_an_earlier_tool_result_id(self):
        for value in (None, False, 1, [], {}, '', 'unknown', 'second'):
            with self.subTest(value=value):
                case = constrained_case()
                case['assertions'][1]['after'] = value
                with self.assertRaises(ValueError):
                    validate_case(case)
        case = constrained_case()
        case['assertions'][0]['after'] = 'second'
        with self.assertRaises(ValueError):
            validate_case(case)  # Forward references also exclude cycles.
        case = constrained_case()
        case['assertions'].insert(0, {'id': 'answer', 'type': 'final_text', 'equals': 'done'})
        case['assertions'][2]['after'] = 'answer'
        with self.assertRaises(ValueError):
            validate_case(case)
        case['assertions'][2]['after'] = 'first'
        case['assertions'][0]['after'] = 'first'
        with self.assertRaises(ValueError):
            validate_case(case)  # Other assertion types cannot declare after.

    def test_exact_text_requires_a_string_and_excludes_contains(self):
        for value in (None, False, 0, [], {}):
            with self.subTest(value=value):
                case = constrained_case()
                case['assertions'][0]['result']['textEquals'] = value
                with self.assertRaises(ValueError):
                    validate_case(case)
        case = constrained_case()
        case['assertions'][0]['result']['textContains'] = 'x'
        with self.assertRaises(ValueError):
            validate_case(case)
        del case['assertions'][0]['result']['textEquals']
        case['assertions'][0]['result']['textContains'] = ''
        with self.assertRaises(ValueError):
            validate_case(case)  # Empty substring matching is still forbidden.


class ConstraintAssertionTests(unittest.TestCase):
    def test_exact_text_preserves_whitespace_and_joins_all_text_blocks(self):
        for expected, texts, outcome in (
                ('', [''], 'passed'), ('', [' ', ''], 'failed'), ('', ['', '\n'], 'failed'),
                ('', ['', 'nonempty'], 'failed'), ('中文', ['中', '文'], 'passed'),
                (' a ', [' a '], 'passed'), ('a', [' a '], 'failed')):
            with self.subTest(expected=expected, texts=texts):
                assertion = constrained_case()['assertions'][0]
                assertion['result']['textEquals'] = expected
                view = scheduled_view([('call', 'a', 'a.txt'), ('result', 'a', texts)])
                self.assertEqual(check_assertion(assertion, view)['outcome'], outcome)

    def test_after_rejects_call_before_predecessor_result(self):
        for schedule, outcome in (
                ([('call', 'a', 'a.txt'), ('result', 'a', ['']),
                  ('call', 'b', 'b.txt'), ('result', 'b', [''])], 'passed'),
                ([('call', 'a', 'a.txt'), ('call', 'b', 'b.txt'),
                  ('result', 'a', ['']), ('result', 'b', [''])], 'failed')):
            with self.subTest(outcome=outcome):
                results = check_assertions(constrained_case()['assertions'], scheduled_view(schedule))
                self.assertEqual(results[0]['outcome'], 'passed')
                self.assertEqual(results[1]['outcome'], outcome)

    def test_earliest_matching_completion_keeps_valid_successors(self):
        view = scheduled_view([
            ('call', 'slow', 'a.txt'), ('call', 'fast', 'a.txt'), ('result', 'fast', ['']),
            ('call', 'b', 'b.txt'), ('result', 'b', ['']), ('result', 'slow', ['']),
        ])
        results = check_assertions(constrained_case()['assertions'], view)
        self.assertEqual([row['outcome'] for row in results], ['passed', 'passed'])
        self.assertEqual(results[0]['evidence']['callId'], 'fast')
        self.assertEqual(results[1]['evidence']['afterResultSeq'], results[0]['evidence']['resultSeq'])

    def test_later_ordered_match_is_used_and_earlier_mismatch_is_skipped(self):
        view = scheduled_view([
            ('call', 'early', 'b.txt'), ('result', 'early', ['']),
            ('call', 'a', 'a.txt'), ('result', 'a', ['']),
            ('call', 'late', 'b.txt'), ('result', 'late', ['']),
        ])
        results = check_assertions(constrained_case()['assertions'], view)
        self.assertEqual([row['outcome'] for row in results], ['passed', 'passed'])
        self.assertEqual(results[1]['evidence']['callId'], 'late')

    def test_missing_or_failed_predecessor_cannot_pass(self):
        for prefix, outcome in (
                ([], 'insufficient_evidence'),
                ([('call', 'a', 'a.txt')], 'insufficient_evidence'),
                ([('call', 'a', 'a.txt'), ('result', 'a', ['nonempty'])], 'failed')):
            with self.subTest(outcome=outcome, prefix=prefix):
                view = scheduled_view([*prefix, ('call', 'b', 'b.txt'), ('result', 'b', [''])])
                assertions = constrained_case()['assertions']
                results = check_assertions(assertions, view)
                self.assertEqual([row['outcome'] for row in results], [outcome, outcome])
                self.assertEqual(check_assertion(assertions[1], view)['outcome'], 'insufficient_evidence')


if __name__ == '__main__':
    unittest.main()
