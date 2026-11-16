import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from dsh_eval.environment import StatefulEnvironment, snapshot_digest
from dsh_eval.evaluate import evaluate
from dsh_eval.formats import load_json
from dsh_eval.runner import ROOT, _process_options, classify_execution, run_synthetic_case, save_json, supervise


def budget_case(limit):
    case = load_json(ROOT / 'fixtures/evaluation/edit-delete.case.json')
    case['budget'].update(timeoutSeconds=10, maxToolCalls=limit)
    return case


class ToolBudgetExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='dsh-budget-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name).resolve()
        cls.results = {}
        for limit in (0, 1, 3):
            source = cls.directory / f'case-{limit}.json'
            save_json(source, budget_case(limit))
            cls.results[limit] = run_synthetic_case(source, cls.directory / 'runs', scenario='edit-delete')

    def test_exact_limit_completes_and_records_enforcement_without_exhaustion(self):
        result = self.results[3]
        self.assertEqual(result['outcome'], 'passed')
        self.assertEqual(result['execution']['status'], 'completed')
        self.assertTrue(result['budgetEnforcement']['maxToolCalls'])
        runtime = load_json(result['association']['runtimeReport'])
        self.assertEqual(runtime['environmentSnapshot']['toolCallBudget'],
                         {'toolCallBudgetFormatVersion': 1, 'limit': 3, 'admitted': 3, 'rejected': 0, 'exhausted': False})
        self.assertEqual(runtime['supervisor']['toolCallBudget'], runtime['environmentSnapshot']['toolCallBudget'])
        self.assertTrue(runtime['environmentSnapshot']['complete'])
        self.assertFalse(runtime['modelCalled'])

    def test_zero_and_first_over_limit_stop_with_no_rejected_operation_effect(self):
        for limit in (0, 1):
            with self.subTest(limit=limit):
                result = self.results[limit]
                self.assertEqual(result['execution']['status'], 'budget_exceeded')
                self.assertEqual(result['outcome'], 'unevaluable')
                self.assertEqual(result['assertions']['outcome'], 'not_run')
                self.assertEqual(result['recording']['outcome'], 'complete')
                runtime = load_json(result['association']['runtimeReport'])
                snapshot, supervisor = runtime['environmentSnapshot'], runtime['supervisor']
                self.assertFalse(snapshot['complete'])
                expected = dict(budget_case(limit)['environment']['files'])
                if limit:
                    expected['settings.txt'] = expected['settings.txt'].replace('mode=draft', 'mode=ready')
                self.assertEqual(snapshot['files'], expected)
                self.assertEqual(snapshot['toolCallBudget']['admitted'], limit)
                self.assertEqual(snapshot['toolCallBudget']['rejected'], 1)
                self.assertTrue(snapshot['toolCallBudget']['exhausted'])
                self.assertEqual(supervisor['intervention'], 'tool_budget')
                self.assertTrue(supervisor['stdinWriterStopped'])
                self.assertTrue(supervisor['stdoutReaderStopped'])
                self.assertEqual(supervisor['adapterExitCode'], 0)
                self.assertIsNone(supervisor['protocolError'])
                self.assertFalse(supervisor['forceStopAttempted'])
                trace = next(Path(result['association']['runDir']).glob('*.jsonl')).read_text(encoding='utf-8')
                self.assertIn('TOOL_CALL_LIMIT_EXCEEDED', trace)
                self.assertNotIn('assistant/message', trace)
                self.assertEqual(evaluate(result['association']['casePath'], result['association']['evidencePath'])['outcome'], 'unevaluable')

    def test_completed_claim_requires_consistent_bound_budget_receipt(self):
        result = self.results[3]
        original_evidence = load_json(result['association']['evidencePath'])
        original_runtime = load_json(result['association']['runtimeReport'])
        case_path = Path(result['association']['casePath'])
        # Mutate copies alongside the original recording, retaining all first-run files.
        directory = case_path.parent
        variants = ('flag', 'missing', 'exhausted', 'rejected', 'admitted', 'limit', 'boolean', 'supervisor',
                    'digest', 'missing-digest', 'supervisor-stop', 'host-stop', 'supervisor-protocol-error',
                    'supervisor-exit', 'host-error', 'host-open', 'host-force', 'host-exit', 'host-signal',
                    'host-protocol-invalid', 'host-end', 'host-missing-protocol')
        for variant in variants:
            with self.subTest(variant=variant):
                evidence, runtime = copy.deepcopy(original_evidence), copy.deepcopy(original_runtime)
                snapshot = runtime['environmentSnapshot']
                if variant == 'flag':
                    evidence['budgetEnforcement'].pop('maxToolCalls')
                elif variant == 'missing':
                    snapshot.pop('toolCallBudget')
                elif variant in ('exhausted', 'rejected', 'admitted', 'limit', 'boolean'):
                    key, value = {'exhausted': ('exhausted', True), 'rejected': ('rejected', 1),
                                  'admitted': ('admitted', 4), 'limit': ('limit', 4), 'boolean': ('admitted', True)}[variant]
                    snapshot['toolCallBudget'][key] = value
                    runtime['supervisor']['toolCallBudget'] = copy.deepcopy(snapshot['toolCallBudget'])
                elif variant == 'supervisor':
                    runtime['supervisor']['toolCallBudget']['admitted'] = 0
                elif variant == 'supervisor-stop':
                    runtime['supervisor']['intervention'] = 'tool_budget'
                elif variant == 'host-stop':
                    runtime['host']['intervention'] = 'tool_budget'
                elif variant == 'supervisor-protocol-error':
                    runtime['supervisor']['protocolError'] = 'Tool request after adapter exit or closure'
                elif variant == 'supervisor-exit':
                    runtime['supervisor']['adapterExitCode'] = 1
                elif variant in ('host-error', 'host-open', 'host-force', 'host-exit', 'host-signal'):
                    key, value = {'host-error':('error','Host failed'), 'host-open':('childClosed',False),
                                  'host-force':('forceStopped',True), 'host-exit':('exitCode',1),
                                  'host-signal':('signal','SIGTERM')}[variant]
                    runtime['host'][key] = value
                elif variant == 'host-protocol-invalid':
                    runtime['host']['protocol']['valid'] = False
                elif variant == 'host-end':
                    runtime['host']['protocol']['turnEndReason'] = {'kind':'aborted','reason':{'kind':'user'}}
                elif variant == 'host-missing-protocol':
                    runtime['host'].pop('protocol')
                if variant != 'digest':
                    evidence['environmentSnapshotSha256'] = snapshot_digest(snapshot)
                else:
                    snapshot['toolCallBudget']['admitted'] = 0
                if variant == 'missing-digest':
                    evidence.pop('environmentSnapshotSha256')
                runtime_path = directory / f'{variant}-runtime.json'
                evidence_path = directory / f'{variant}-evidence.json'
                save_json(runtime_path, runtime)
                evidence['runtimeReport'] = runtime_path.name
                save_json(evidence_path, evidence)
                checked = evaluate(case_path, evidence_path)
                self.assertEqual(checked['outcome'], 'unevaluable')
                self.assertEqual(checked['assertions']['outcome'], 'insufficient_evidence')

    def test_budget_stop_survives_missing_host_report(self):
        adapter = self.directory / 'no-host-report.mjs'
        adapter.write_text("import {createInterface} from 'node:readline'; import {basename} from 'node:path';\n"
                           "const input=createInterface({input:process.stdin});\n"
                           "console.log(JSON.stringify({type:'selection',sessionId:'session'}));\n"
                           "console.log(JSON.stringify({type:'tool-request',bridgeVersion:1,requestId:'one',"
                           "caseRunId:basename(process.argv[3]),sessionId:'session',operation:'delete',arguments:{path:'obsolete.txt'}}));\n"
                           "input.on('line',line=>{if(JSON.parse(line).type==='tool_budget'){input.close();process.stdin.pause();}});\n", encoding='utf-8')
        with patch('dsh_eval.runner.SYNTHETIC_ADAPTER', adapter):
            checked = run_synthetic_case(self.directory / 'case-0.json', self.directory / 'missing-host', scenario='edit-delete')
        self.assertEqual(checked['execution']['status'], 'budget_exceeded')
        self.assertEqual(checked['outcome'], 'unevaluable')
        runtime = load_json(checked['association']['runtimeReport'])
        self.assertTrue(runtime['supervisor']['toolCallBudget']['exhausted'])
        self.assertEqual(runtime['environmentSnapshot']['files'], budget_case(0)['environment']['files'])

    def test_recorded_pre_dispatch_argument_error_does_not_consume_bridge_budget(self):
        # Mirrors a host argument validation rejection: intent is recorded, but
        # the tool body never submits this request to the Python environment.
        source = (ROOT / 'scripts/fixtures/mutation-adapter.js').read_text(encoding='utf-8')
        source = source.replace('../../src/recorder.js', (ROOT / 'src/recorder.js').as_uri())
        source = source.replace('../case-host.js', (ROOT / 'scripts/case-host.js').as_uri())
        anchor = 'for (const [operation, args] of scenarios[scenario]) {'
        self.assertEqual(source.count(anchor), 1)
        extra = """record('tool/call', {callId:'prebridge-invalid', name:'eval_read', arguments:'{}'});
record('tool/result', {message:{toolCallId:'prebridge-invalid',isError:true,
  content:[{type:'text',text:'Error: invalid arguments: missing required property path'}]}});
"""
        adapter = self.directory / 'pre-dispatch.mjs'
        adapter.write_text(source.replace(anchor, extra + anchor), encoding='utf-8')
        with patch('dsh_eval.runner.SYNTHETIC_ADAPTER', adapter):
            result = run_synthetic_case(self.directory / 'case-3.json', self.directory / 'pre-dispatch', scenario='edit-delete')
        self.assertEqual(result['outcome'], 'passed')
        self.assertEqual(result['metrics']['toolCalls'], 4)
        runtime = load_json(result['association']['runtimeReport'])
        self.assertEqual(runtime['environmentSnapshot']['toolCallBudget']['admitted'], 3)
        self.assertFalse(runtime['modelCalled'])

    def test_budget_classification_remains_distinct_even_without_abort_end(self):
        host = {'exitCode': 0, 'signal': None, 'childClosed': True, 'forceStopped': False,
                'protocol': {'valid': True, 'turnEndReason': {'kind': 'completed'}}}
        self.assertEqual(classify_execution(host, {'intervention': 'tool_budget', 'adapterExitCode': 0})['status'], 'budget_exceeded')

    def test_python_budget_through_production_adapter_and_real_fork_ipc_cancels_inflight_edit(self):
        case = budget_case(1)
        case['environment']['stateful']['toolDelaysMs'] = {'eval_edit': [3000]}
        source = self.directory / 'ipc-case.json'
        save_json(source, case)
        with patch('dsh_eval.runner.SYNTHETIC_ADAPTER', ROOT / 'scripts/fixtures/tool-budget-ipc.js'):
            result = run_synthetic_case(source, self.directory / 'ipc', scenario='edit-delete')
        self.assertEqual(result['execution']['status'], 'budget_exceeded')
        self.assertEqual(result['outcome'], 'unevaluable')
        self.assertEqual(result['assertions']['outcome'], 'not_run')
        self.assertEqual(result['recording']['outcome'], 'complete')
        directory = Path(result['association']['casePath']).parent
        proof = load_json(directory / 'tool-budget-proof.json')
        runtime = load_json(result['association']['runtimeReport'])
        self.assertFalse(proof['modelCalled'])
        self.assertFalse(proof['HarnessRuntimeUsed'])
        self.assertEqual(proof['failures'], [])
        self.assertEqual(proof['results'], [
            {'status': 'rejected', 'reason': 'Tool call cancelled'},
            {'status': 'rejected', 'reason': 'TOOL_CALL_LIMIT_EXCEEDED: obsolete.txt'}])
        self.assertTrue(proof['messageListenersRestored'] and proof['disconnectListenersRestored'])
        self.assertEqual(runtime['environmentSnapshot']['files'], case['environment']['files'])
        self.assertFalse(runtime['environmentSnapshot']['complete'])
        self.assertEqual(runtime['supervisor']['toolCallBudget'],
                         {'toolCallBudgetFormatVersion':1,'limit':1,'admitted':1,'rejected':1,'exhausted':True})
        self.assertTrue(runtime['supervisor']['stdinWriterStopped'] and runtime['supervisor']['stdoutReaderStopped'])
        self.assertEqual(runtime['supervisor']['adapterExitCode'], 0)
        self.assertIsNone(runtime['supervisor']['protocolError'])
        self.assertFalse(runtime['supervisor']['forceStopAttempted'])
        self.assertEqual(runtime['host']['childPid'], proof['childPid'])
        self.assertTrue(runtime['host']['childClosed'])
        self.assertEqual(runtime['host']['intervention'], 'tool_budget')
        self.assertFalse(runtime['host']['forceStopped'])


class ToolBudgetSupervisionTests(unittest.TestCase):
    def test_exited_adapter_does_not_admit_queued_requests(self):
        case = budget_case(1)
        environment = StatefulEnvironment(case['environment'], 'case', case['budget'])
        request = {'type':'tool-request','bridgeVersion':1,'requestId':'late','caseRunId':'case',
                   'sessionId':'session','operation':'delete','arguments':{'path':'obsolete.txt'}}
        script = "import json,sys; print(json.dumps({'type':'selection','sessionId':'session'}),flush=True); print(sys.argv[1],flush=True)"
        process = subprocess.Popen([sys.executable,'-u','-c',script,json.dumps(request)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',**_process_options())
        try:
            process.wait(timeout=5)  # Observe a real exit before draining its buffered requests.
            report = supervise(process,10,environment=environment)
            self.assertEqual(process.returncode,0,process.stderr.read())
            self.assertEqual(environment.files,case['environment']['files'])
            self.assertEqual(environment.budget_state()['admitted'],0)
            self.assertIn('after adapter exit or closure',report['protocolError'])
            self.assertEqual(classify_execution({'childClosed':True,'exitCode':0,'signal':None,
                'protocol':{'valid':True,'turnEndReason':{'kind':'completed'}}},report)['status'],'runtime_error')
            self.assertTrue(report['stdinWriterStopped'] and report['stdoutReaderStopped'])
        finally:
            process.stderr.close()

    def test_exited_adapter_cancels_ready_pending_without_execution(self):
        case = budget_case(1)
        case['environment']['stateful']['toolDelaysMs'] = {'eval_delete':[100]}
        environment = StatefulEnvironment(case['environment'], 'case', case['budget'])
        environment.bind('session')
        request = {'type':'tool-request','bridgeVersion':1,'requestId':'pending','caseRunId':'case',
                   'sessionId':'session','operation':'delete','arguments':{'path':'obsolete.txt'}}
        self.assertEqual(environment.submit(request,time.monotonic()),[])
        script = "import json,time; time.sleep(.2); print(json.dumps({'type':'streaming'}),flush=True)"
        process = subprocess.Popen([sys.executable,'-u','-c',script], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',**_process_options())
        try:
            process.wait(timeout=5)
            report = supervise(process,10,environment=environment)
            self.assertEqual(process.returncode,0,process.stderr.read())
            self.assertEqual(environment.files,case['environment']['files'])
            self.assertEqual(environment.responses['pending'][1]['text'],'TOOL_CANCELLED: obsolete.txt')
            self.assertFalse(environment.pending)
            self.assertIn('pending tool requests',report['protocolError'])
            self.assertTrue(report['stdinWriterStopped'] and report['stdoutReaderStopped'])
        finally:
            process.stderr.close()

    def test_closed_adapter_rejects_late_request_while_process_still_running(self):
        case = budget_case(1)
        environment = StatefulEnvironment(case['environment'], 'case', case['budget'])
        request = {'type':'tool-request','bridgeVersion':1,'requestId':'late','caseRunId':'case',
                   'sessionId':'session','operation':'delete','arguments':{'path':'obsolete.txt'}}
        script = """import json,sys
print(json.dumps({'type':'selection','sessionId':'session'}),flush=True)
print(json.dumps({'type':'closed','childClosed':True}),flush=True)
print(sys.argv[1],flush=True)
assert json.loads(sys.stdin.readline())=={'type':'shutdown'}
"""
        process = subprocess.Popen([sys.executable,'-u','-c',script,json.dumps(request)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',**_process_options())
        try:
            report = supervise(process,2,environment=environment)
            self.assertEqual(process.returncode,0,process.stderr.read())
            self.assertEqual(report['intervention'],'shutdown')
            self.assertEqual(environment.files,case['environment']['files'])
            self.assertEqual(environment.budget_state()['admitted'],0)
            self.assertIn('after adapter exit or closure',report['protocolError'])
            self.assertTrue(report['stdinWriterStopped'] and report['stdoutReaderStopped'])
        finally:
            process.stderr.close()

    def test_earlier_task_deadline_remains_timeout_without_budget_admission(self):
        case = budget_case(0)
        environment = StatefulEnvironment(case['environment'], 'case', case['budget'])
        script = "import json,sys; assert json.loads(sys.stdin.readline())['type']=='timeout'"
        process = subprocess.Popen([sys.executable,'-u','-c',script], stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,text=True,encoding='utf-8',**_process_options())
        try:
            report=supervise(process,0,environment=environment)
            self.assertEqual(process.returncode,0,process.stderr.read())
            self.assertEqual(report['intervention'],'timeout')
            self.assertEqual(environment.budget_state()['admitted'],0)
            self.assertFalse(environment.budget_exhausted)
        finally:
            process.stderr.close()

    def test_budget_refusal_precedes_control_and_cancels_delayed_work_over_real_pipes(self):
        case = budget_case(1)
        case['environment']['stateful']['toolDelaysMs'] = {'eval_edit': [3000]}
        environment = StatefulEnvironment(case['environment'], 'case', case['budget'])
        request = {'type':'tool-request','bridgeVersion':1,'requestId':'pending','caseRunId':'case',
                   'sessionId':'session','operation':'edit','arguments':{'path':'settings.txt','oldText':'mode=draft','newText':'mode=ready'}}
        denied = {**request, 'requestId':'denied','operation':'delete','arguments':{'path':'obsolete.txt'}}
        script = """import json,sys
print(json.dumps({'type':'selection','sessionId':'session'}),flush=True)
print(sys.argv[1],flush=True)
print(sys.argv[2],flush=True)
refusal=json.loads(sys.stdin.readline())
control=json.loads(sys.stdin.readline())
assert refusal['requestId']=='denied' and refusal['errorCode']=='TOOL_CALL_LIMIT_EXCEEDED'
assert control=={'type':'tool_budget'}
"""
        process = subprocess.Popen([sys.executable,'-u','-c',script,json.dumps(request),json.dumps(denied)],
                                   stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                   text=True,encoding='utf-8',**_process_options())
        try:
            report=supervise(process,10,environment=environment,event_log=io.StringIO())
            self.assertEqual(process.returncode,0,process.stderr.read())
            self.assertEqual(report['intervention'],'tool_budget')
            self.assertIsNone(report['protocolError'])
            self.assertTrue(report['stdinWriterStopped'] and report['stdoutReaderStopped'])
            self.assertEqual(environment.files,case['environment']['files'])
            self.assertFalse(environment.pending)
            self.assertEqual(environment.poll(1e20),[])
            self.assertEqual(environment.responses['pending'][1]['text'],'TOOL_CANCELLED: settings.txt')
        finally:
            process.stderr.close()


if __name__ == '__main__':
    unittest.main()
