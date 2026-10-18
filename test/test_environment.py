import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4

from dsh_eval.environment import StatefulEnvironment
from dsh_eval.formats import load_json, validate_case
from dsh_eval.runner import prepare_workspace, supervise, _process_options

ROOT = Path(__file__).resolve().parents[1]

class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.case = validate_case(load_json(ROOT / 'fixtures/evaluation/retry-read.case.json'))
        self.environment = StatefulEnvironment(self.case['environment'], 'case-run')
        self.environment.bind('session')

    def request(self, path='project.md', operation='read', request_id=None):
        return {'type':'tool-request','bridgeVersion':1,'requestId':request_id or str(uuid4()),
                'caseRunId':'case-run','sessionId':'session','operation':operation,'arguments':{'path':path}}

    def test_failure_is_per_path_and_duplicate_does_not_consume_again(self):
        first = self.request(request_id='first')
        self.assertIn('TEMPORARY_READ_FAILURE', self.environment.handle(first)['text'])
        self.assertTrue(self.environment.handle(first)['isError'])
        self.assertFalse(self.environment.handle(self.request())['isError'])
        fresh = StatefulEnvironment(self.case['environment'], 'case-run')
        fresh.bind('session')
        self.assertTrue(fresh.handle(first)['isError'])
        self.assertEqual(self.case['environment']['stateful']['transientReadFailures']['project.md'], 1)

    def test_missing_and_invalid_paths_do_not_consume_valid_file_failure(self):
        for path in ('missing.md', '../project.md', '/project.md', 'C:/project.md', 'a/./b', 'a\\b'):
            self.assertTrue(self.environment.handle(self.request(path))['isError'])
        self.assertTrue(self.environment.handle(self.request())['isError'])

    def test_list_discovers_current_path_without_reading_or_consuming_failure(self):
        self.assertEqual(self.environment.handle(self.request('.', 'list'))['text'], 'project.md')
        self.assertTrue(self.environment.handle(self.request())['isError'])

    def test_identity_protocol_and_conflicting_duplicates_rejected(self):
        request = self.request(request_id='same')
        self.environment.handle(request)
        for patch in ({'sessionId':'other'}, {'caseRunId':'other'}, {'bridgeVersion':2},
                      {'arguments':{'path':'other'}}, {'operation':'write'}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.environment.handle({**request, **patch})
        with self.assertRaises(ValueError):
            self.environment.bind('other')

    def test_version_one_rejects_stateful_and_bad_failure_counts(self):
        for update in ({'caseFormatVersion':1},):
            with self.assertRaises(ValueError):
                validate_case({**self.case, **update})
        for failures in ({'missing':1}, {'project.md':True}, {'project.md':-1}):
            case = copy.deepcopy(self.case)
            case['environment']['stateful']['transientReadFailures'] = failures
            with self.assertRaises(ValueError):
                validate_case(case)

    def test_virtual_files_are_not_materialized_for_native_tool_bypass(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(list(prepare_workspace(directory, self.case).iterdir()), [])

    def test_real_process_roundtrip_is_served_while_running(self):
        code = """import sys,json
print(json.dumps({'type':'selection','sessionId':'session'}),flush=True)
request = json.loads(sys.argv[1])
print(json.dumps(request),flush=True)
response=json.loads(sys.stdin.readline())
assert response['requestId']==request['requestId'] and response['isError']
"""
        process = subprocess.Popen(['python','-u','-c',code,json.dumps(self.request())],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',**_process_options())
        try:
            report = supervise(process, 5, environment=self.environment, event_log=io.StringIO())
            self.assertEqual(report['adapterExitCode'], 0, process.stderr.read())
            self.assertIsNone(report['protocolError'])
        finally:
            process.stderr.close()

if __name__ == '__main__':
    unittest.main()
