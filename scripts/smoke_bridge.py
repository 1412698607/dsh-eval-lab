"""Real host tool registration / IPC check. Does not call a model."""
import json
import argparse
import subprocess
from uuid import uuid4

from dsh_eval.environment import StatefulEnvironment
from dsh_eval.formats import load_json
from dsh_eval.runner import ROOT, _process_options, supervise


def main():
    parser = argparse.ArgumentParser(description="Real tool registration and IPC; no model calls")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--writes", action="store_true")
    mode.add_argument("--mutations", action="store_true")
    args = parser.parse_args()
    case_run_id = str(uuid4())
    writes, mutations = args.writes, args.mutations
    scenario = "mutations" if mutations else "writes" if writes else "reads"
    name = {"mutations": "edit-delete-timeout", "writes": "write-retry", "reads": "retry-read"}[scenario]
    case = load_json(ROOT / "fixtures/evaluation" / (name + ".case.json"))
    environment = StatefulEnvironment(case["environment"], case_run_id, case["budget"])
    if writes:
        environment.delays["eval_write"].append(1500)  # Third write is cancelled before its commit.
    if mutations:
        for tool in ("eval_edit", "eval_delete"):
            environment.delays[tool].append(1500)  # Third call is cancelled before committing.
    environment.bind("bridge-smoke-session")
    process = subprocess.Popen(["node", str(ROOT / "scripts/smoke-bridge.js"), "parent", case_run_id, scenario],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
                               **_process_options())
    report = supervise(process, 20, environment=environment)
    assert report["adapterExitCode"] == 0 and report["protocolError"] is None and report["intervention"] is None, report
    assert len(environment.responses) == (15 if mutations else 6 if writes else 4)
    if writes:
        assert environment.files == {"guard.txt": "keep\n", "result.txt": "done\n"}, environment.files
    if mutations:
        assert environment.files == {"guard.txt": "keep\n", "settings.txt": "mode=ready\nowner=评测\n"}, environment.files
    print(json.dumps({"bridgeSmoke": "passed", "modelCalled": False, "writes": writes,
                      "scenario": scenario, "requests": len(environment.responses)}))


if __name__ == "__main__":
    main()
