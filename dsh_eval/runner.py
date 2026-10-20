"""One isolated headless case. Node owns the dedicated Harness child; Python owns policy."""
import os
from pathlib import Path, PureWindowsPath
import queue
import signal
import subprocess
import threading
import time
from uuid import UUID, uuid4
import json

from .evaluate import ROOT, evaluate
from .formats import load_json, parse_json, require, validate_case
from .environment import StatefulEnvironment

ADAPTER = ROOT / "scripts" / "case-host.js"
PREPARE_TIMEOUT = 150
CLEANUP_TIMEOUT = 15


def save_json(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def prepare_workspace(directory, case):
    """Write only into a fresh directory, with portable Windows-safe fixture names."""
    workspace = Path(directory) / "workspace"
    names = set()
    for name in case["environment"]["files"]:
        for part in name.split("/"):
            require(part == part.rstrip(" .") and not PureWindowsPath(part).is_reserved()
                    and not any(character in part for character in '<>"|?*\x00'), "Unsupported fixture filename")
        folded = name.casefold()
        require(folded not in names, "Case-insensitive fixture path collision")
        names.add(folded)
    require(not any(parent.casefold() in names for name in names for parent in
                    (str(path).replace("\\", "/") for path in Path(name).parents) if parent != "."),
            "Case-insensitive file/directory collision")
    workspace.mkdir()
    if "stateful" in case["environment"]:
        return workspace  # Virtual files must only be accessible through the live bridge.
    for name, content in case["environment"]["files"].items():
        path = workspace / name
        require(path.resolve().is_relative_to(workspace.resolve()), "Fixture escaped workspace")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    return workspace


def _process_options():
    return ({"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt" else {"start_new_session": True})


def stop_process_tree(process):
    """Only terminate a tree this invocation created and still owns."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        stopped = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                 capture_output=True, timeout=10, **_process_options())
        require(stopped.returncode == 0 or process.poll() is not None, "Could not terminate owned process tree")
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=10)


def _prepare(directory, modules_dir, report=None):
    command = ["node", str(ADAPTER), "prepare", str(directory)]
    if modules_dir is not None:
        command.append(str(Path(modules_dir).resolve()))
    with (directory / "prepare.stdout.log").open("x", encoding="utf-8") as stdout, \
            (directory / "prepare.stderr.log").open("x", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, **_process_options())
        if report is not None:
            report.update(processStarted=True, processExited=False)
        try:
            code = process.wait(timeout=PREPARE_TIMEOUT)
            require(code == 0, f"Harness preparation exited {code}; see prepare.stderr.log")
        finally:
            try:
                stop_process_tree(process)
            finally:
                if report is not None:
                    report["processExited"] = process.poll() is not None


def supervise(process, timeout_seconds, cancel_after_stream=False, event_log=None, report=None, environment=None):
    """Keep pipe I/O off the deadline loop, and always reap our adapter tree."""
    events = queue.Queue()
    outgoing = queue.Queue()
    writer_stopping = threading.Event()
    report = {} if report is None else report
    intervention = None
    intervention_time = None
    protocol_error = None
    input_error = None
    forced = False
    user_interrupted = False

    def read_events():
        try:
            for line in process.stdout:
                if event_log:
                    event_log.write(line)
                    event_log.flush()
                events.put(line)
        except (OSError, UnicodeError) as error:
            events.put(error)
        finally:
            events.put(None)

    def write_messages():
        nonlocal input_error
        try:
            while not writer_stopping.is_set():
                message = outgoing.get()
                if message is None or writer_stopping.is_set():
                    break
                if message["type"] == "tool-response" and intervention is not None:
                    continue
                process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
                process.stdin.flush()
        except (OSError, UnicodeError) as error:
            input_error = f"Cannot write adapter input: {type(error).__name__}"
            events.put(("input-error", input_error))
        finally:
            # Only this thread owns stdin, including close: closing it on the
            # supervisor thread could block on the same TextIO lock as write().
            try:
                process.stdin.close()
            except (OSError, UnicodeError) as error:
                if input_error is None:
                    input_error = f"Cannot close adapter input: {type(error).__name__}"

    reader = threading.Thread(target=read_events, daemon=True)
    writer = threading.Thread(target=write_messages, daemon=True)
    reader.start()
    writer.start()
    started = time.monotonic()

    def stop(kind):
        nonlocal intervention, intervention_time
        if intervention is not None or process.poll() is not None:
            return
        intervention, intervention_time = kind, time.monotonic()
        outgoing.put({"type": kind})

    try:
        while process.poll() is None or reader.is_alive() or not events.empty():
            try:
                if intervention is None and time.monotonic() - started >= timeout_seconds:
                    stop("timeout")
                if intervention_time is not None and time.monotonic() - intervention_time >= CLEANUP_TIMEOUT:
                    forced = process.poll() is None
                    stop_process_tree(process)
                    break
                try:
                    line = events.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line is None:
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        protocol_error = "Adapter stdout closed before process exit"
                        stop("shutdown")
                    continue
                if isinstance(line, Exception):
                    protocol_error = f"Cannot decode adapter event stream: {type(line).__name__}"
                    stop("shutdown")
                    continue
                if isinstance(line, tuple):
                    protocol_error = line[1]
                    stop("shutdown")
                    continue
                try:
                    event = parse_json(line)
                    require(isinstance(event, dict) and event.get("type") in
                            ("launched", "selection", "request-route", "streaming", "closed", "tool-request", "bridge-error"), "Invalid adapter event")
                    if event["type"] == "bridge-error":
                        raise ValueError("Tool bridge infrastructure failed")
                    if environment is not None and event["type"] == "selection":
                        environment.bind(event.get("sessionId"))
                    if event["type"] == "tool-request":
                        require(environment is not None and intervention is None, "Tool request outside active environment")
                        response = environment.handle(event)
                        outgoing.put(response)
                except ValueError as error:
                    protocol_error = str(error)
                    stop("shutdown")
                    continue
                if event.get("type") == "streaming" and cancel_after_stream:
                    stop("cancel")
            except KeyboardInterrupt:
                user_interrupted = True
                stop("cancel")
        process.wait(timeout=5)
    finally:
        # Preserve an already-issued timeout/cancel even if the OS refuses cleanup.
        report.update(intervention=intervention, forceStopAttempted=forced,
                      protocolError=protocol_error, adapterExitCode=process.poll(), userInterrupted=user_interrupted)
        writer_stopping.set()
        outgoing.put(None)
        stop_process_tree(process)
        writer.join(timeout=5)
        reader.join(timeout=5)
        if not reader.is_alive():
            process.stdout.close()
        if input_error is not None and intervention is None:
            protocol_error = input_error
        if writer.is_alive() or reader.is_alive():
            protocol_error = "Adapter pipe workers did not stop after process cleanup"
        report.update(protocolError=protocol_error, stdinWriterStopped=not writer.is_alive())
    report["adapterExitCode"] = process.returncode
    return report


def classify_execution(host, supervisor):
    execution = {"status": "runtime_error", "exitCode": host.get("exitCode"), "signal": host.get("signal")}
    intervention = supervisor.get("intervention") or host.get("intervention")
    reason = host.get("protocol", {}).get("turnEndReason") if isinstance(host.get("protocol"), dict) else None
    if intervention == "timeout":
        execution.update(status="timed_out", reason="Task wall-time deadline reached; cleanup grace is separate")
    elif intervention == "cancel":
        execution.update(status="cancelled" if reason == {"kind": "aborted", "reason": {"kind": "user"}} else "unknown",
                         reason="User cancellation requested")
    elif host.get("error") or supervisor.get("protocolError") or supervisor.get("adapterExitCode") != 0:
        execution["reason"] = "Host adapter failed; see private runtime artifacts"
    elif not host.get("childClosed") or host.get("forceStopped") or intervention:
        execution["reason"] = "Host did not finish cleanly"
    elif host.get("exitCode") == 0 and host.get("signal") is None and host.get("protocol", {}).get("valid") \
            and reason == {"kind": "completed"}:
        execution["status"] = "completed"
    else:
        execution["reason"] = "Harness startup, routing or task runtime error; see stderr.log and host-result.json"
    return execution


def validate_live_case(case):
    validate_case(case)
    require(case["configRef"]["profile"] == "headless", "Only the headless profile is supported")
    require(case["configRef"]["pluginVersion"] == load_json(ROOT / "package.json")["version"], "Case requires a different recorder version")
    return case


def run_case(case_path, runs_root=None, modules_dir=None, cancel_after_stream=False, *, batch_id=None, case_run_id=None):
    case = validate_live_case(load_json(case_path))
    case_run_id = str(UUID(case_run_id)) if case_run_id is not None else str(uuid4())
    if batch_id is not None:
        require(isinstance(batch_id, str) and bool(batch_id.strip()), "batchId must be nonempty")
    directory = Path(runs_root or ROOT / "runs" / "evaluation").resolve() / case_run_id
    directory.mkdir(parents=True, exist_ok=False)
    case_snapshot = directory / "case.json"
    save_json(case_snapshot, case)
    host, supervisor = {}, {}
    error_info = None
    preparation = {"processStarted": False, "processExited": True}
    adapter_started = False
    user_interrupted = False
    stage = "workspace"
    execution = None
    started = time.monotonic()
    try:
        prepare_workspace(directory, case)
        stage = "prepare"
        _prepare(directory, modules_dir, preparation)
        stage = "run"
        with (directory / "adapter.stderr.log").open("x", encoding="utf-8") as stderr, \
                (directory / "adapter.stdout.jsonl").open("x", encoding="utf-8") as event_log:
            adapter_started = None  # Interrupted creation may leave the start unknown.
            try:
                process = subprocess.Popen(["node", str(ADAPTER), "run", str(directory)], cwd=ROOT,
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                                           text=True, encoding="utf-8", **_process_options())
            except OSError:
                adapter_started = False
                raise
            adapter_started = True
            environment = StatefulEnvironment(case["environment"], case_run_id) if "stateful" in case["environment"] else None
            supervise(process, case["budget"]["timeoutSeconds"], cancel_after_stream, event_log, supervisor, environment)
        host = load_json(directory / "host-result.json")
        execution = classify_execution(host, supervisor)
    except (OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        error_info = {"type": type(error).__name__, "message": str(error)}
        user_interrupted = isinstance(error, KeyboardInterrupt)
        status = ("timed_out" if supervisor.get("intervention") == "timeout" else
                  "unknown" if supervisor.get("intervention") == "cancel" else
                  "cancelled" if isinstance(error, KeyboardInterrupt) else "runtime_error")
        execution = {"status": status,
                     "reason": f"{stage}: {type(error).__name__}; see private runtime artifacts"}
    # Startup can fail before a recorder or session exists. Never invent those identities.
    run_directories = sorted((directory / "traces").glob("*/run.json"))
    run_dir = run_directories[0].parent if len(run_directories) == 1 else None
    try:
        manifest = load_json(run_dir / "run.json") if run_dir else {}
    except (OSError, ValueError):
        manifest = {}
    requests = host.get("requests", [])
    routes = {(item.get("provider"), item.get("model")) for item in requests}
    configuration = None
    if manifest.get("pluginVersion") and len(routes) == 1 and all(isinstance(item, str) and item for item in next(iter(routes))):
        provider, model = next(iter(routes))
        configuration = {"provider": provider, "model": model, "profile": "headless", "pluginVersion": manifest.get("pluginVersion")}
    if execution["status"] == "completed" and configuration is None:
        execution.update(status="runtime_error", reason="No unique actual request route was observed")
    evidence = {"evidenceFormatVersion": 2, "caseRunId": case_run_id, "caseId": case["caseId"],
                "runId": manifest.get("runId"), "sessionId": host.get("sessionId"),
                "runDir": str(run_dir.relative_to(directory)) if run_dir else None, "source": "live",
                "configuration": configuration, "budgetEnforcement": {"timeoutSeconds": stage == "run" and bool(supervisor)},
                "execution": execution, "runtimeReport": "runtime.json"}
    if batch_id is not None:
        evidence["batchId"] = batch_id
    save_json(directory / "runtime.json", {"runtimeFormatVersion": 1, "caseRunId": case_run_id, "stage": stage,
                                          "host": host, "supervisor": supervisor, "error": error_info,
                                          "preparation": preparation, "adapterProcessStarted": adapter_started,
                                          "userInterrupted": user_interrupted or supervisor.get("userInterrupted", False),
                                          "elapsedSeconds": time.monotonic() - started})
    save_json(directory / "evidence.json", evidence)
    result = evaluate(case_snapshot, directory / "evidence.json")
    save_json(directory / "evaluation.json", result)
    return result
