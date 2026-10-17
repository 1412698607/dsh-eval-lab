import argparse
import json
from pathlib import Path
import sys

from .evaluate import evaluate


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate one offline case using fresh Node inspect")
    parser.add_argument("--case", required=True, help="Version 1 case JSON")
    parser.add_argument("--evidence", required=True, help="Version 1 evidence manifest")
    parser.add_argument("--output", help="Create a new result JSON; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        if args.output and Path(args.output).resolve() in (Path(args.case).resolve(), Path(args.evidence).resolve()):
            raise ValueError("Output must differ from input paths")
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
