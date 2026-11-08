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
    mode.add_argument("--control", action="store_true")
    mode.add_argument("--rename", action="store_true")
    mode.add_argument("--rename-retry", action="store_true")
    args = parser.parse_args()
    case_run_id = str(uuid4())
    writes, mutations, control = args.writes, args.mutations, args.control
    scenario = "control" if control else "mutations" if mutations else "writes" if writes else "reads"
    if args.rename:
        scenario = "rename"
    if args.rename_retry:
        scenario = "rename-retry"
    name = {"control": "edit-delete", "mutations": "edit-delete-timeout", "writes": "write-retry",
            "reads": "retry-read", "rename": "rename-no-overwrite", "rename-retry": "rename-timeout-retry"}[scenario]
    case = load_json(ROOT / "fixtures/evaluation" / (name + ".case.json"))
    if control:
        case["budget"] = {"timeoutSeconds": 20, "toolTimeoutMs": 5000,
                          "toolTimeoutsMs": {"eval_read": 100, "eval_edit": 2000, "eval_delete": 3000}}
        case["environment"]["stateful"]["toolDelaysMs"] = {"eval_read": [600], "eval_edit": [250], "eval_delete": [1000]}
    environment = StatefulEnvironment(case["environment"], case_run_id, case["budget"])
    if writes:
        environment.delays["eval_write"].append(1500)  # Third write is cancelled before its commit.
    if mutations:
        for tool in ("eval_edit", "eval_delete"):
            environment.delays[tool].append(1500)  # Third call is cancelled before committing.
    environment.bind("bridge-smoke-session")
    command = ["node", str(ROOT / "scripts/smoke-bridge.js"), "parent", case_run_id, scenario]
    if control:
        command.append(json.dumps(case["budget"]))
    process = subprocess.Popen(command,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
                               **_process_options())
    report = supervise(process, 20, environment=environment)
    assert report["adapterExitCode"] == 0 and report["protocolError"] is None and report["intervention"] is None, report
    assert len(environment.responses) == {"mutations": 15, "writes": 6, "control": 6, "reads": 4, "rename": 5, "rename-retry": 6}[scenario]
    if args.rename or args.rename_retry:
        assert environment.files == {"archive/final.txt": "评测\r\n", "guard.txt": "keep\n"}
    if writes:
        assert environment.files == {"guard.txt": "keep\n", "result.txt": "done\n"}, environment.files
    if mutations:
        assert environment.files == {"guard.txt": "keep\n", "settings.txt": "mode=ready\nowner=评测\n"}, environment.files
    if control:
        assert environment.files == {"guard.txt": "keep\n", "settings.txt": "mode=ready\nowner=评测\n", "obsolete.txt": "remove\n"}, environment.files
        assert environment.cancelled and not environment.pending
    print(json.dumps({"bridgeSmoke": "passed", "modelCalled": False, "writes": writes,
                      "scenario": scenario, "requests": len(environment.responses)}))


if __name__ == "__main__":
    main()
