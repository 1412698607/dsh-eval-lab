import argparse
import json
from pathlib import Path
import sys

from .evaluate import evaluate


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate offline evidence or run one isolated Harness case")
    parser.add_argument("--case", required=True, help="Version 1 or 2 case JSON")
    parser.add_argument("--evidence", help="Version 1 or 2 offline evidence manifest")
    parser.add_argument("--run", action="store_true", help="Execute one real headless task; may call the configured model")
    parser.add_argument("--runs-root", help="Parent directory for new isolated case runs")
    parser.add_argument("--host-modules", help="Explicit installed Harness node_modules directory")
    parser.add_argument("--cancel-after-stream", action="store_true", help="Exercise cancellation after the first real model stream chunk")
    parser.add_argument("--output", help="Create a new result JSON; existing files are never overwritten")
    args = parser.parse_args(argv)
    if args.run == bool(args.evidence):
        parser.error("Choose --run or --evidence")
    if args.run and args.output:
        parser.error("--run saves evaluation.json in its new run directory; omit --output")
    if not args.run and (args.runs_root or args.host_modules or args.cancel_after_stream):
        parser.error("Run controls require --run")
    try:
        if args.output and Path(args.output).resolve() in (Path(args.case).resolve(), Path(args.evidence).resolve()):
            raise ValueError("Output must differ from input paths")
        if args.run:
            from .runner import run_case
            result = run_case(args.case, args.runs_root, args.host_modules, args.cancel_after_stream)
        else:
            result = evaluate(args.case, args.evidence)
        text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            with Path(args.output).open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
        print(text, end="")
        return {"passed": 0, "failed": 1, "unevaluable": 2}[result["outcome"]]
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"evaluationFormatVersion": 1, "outcome": "unevaluable", "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
