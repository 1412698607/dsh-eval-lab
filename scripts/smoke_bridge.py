"""Real host tool registration / IPC check. Does not call a model."""
import json
import subprocess
import sys
from uuid import uuid4

from dsh_eval.environment import StatefulEnvironment
from dsh_eval.formats import load_json
from dsh_eval.runner import ROOT, _process_options, supervise


def main():
    case_run_id = str(uuid4())
    writes = "--writes" in sys.argv[1:]
    case = load_json(ROOT / "fixtures/evaluation" / ("write-retry.case.json" if writes else "retry-read.case.json"))
    environment = StatefulEnvironment(case["environment"], case_run_id, case["budget"])
    if writes:
        environment.delays["eval_write"].append(1500)  # Third write is cancelled before its commit.
    environment.bind("bridge-smoke-session")
    process = subprocess.Popen(["node", str(ROOT / "scripts/smoke-bridge.js"), "parent", case_run_id, "writes" if writes else "reads"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
                               **_process_options())
    report = supervise(process, 20, environment=environment)
    assert report["adapterExitCode"] == 0 and report["protocolError"] is None and report["intervention"] is None, report
    assert len(environment.responses) == (6 if writes else 4)
    if writes:
        assert environment.files == {"guard.txt": "keep\n", "result.txt": "done\n"}, environment.files
    print(json.dumps({"bridgeSmoke": "passed", "modelCalled": False, "writes": writes, "requests": len(environment.responses)}))


if __name__ == "__main__":
    main()
