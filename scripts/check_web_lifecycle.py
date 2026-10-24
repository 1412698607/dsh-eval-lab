"""Run M6.4 synthetic process checks and independently inspect every new capture."""
import json
from pathlib import Path
import subprocess
import sys

from .verify_web_lifecycle import verify_launch

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        print("Usage: python -m scripts.check_web_lifecycle [new-output-directory]", file=sys.stderr)
        return 2
    try:
        process = subprocess.run(["node", str(ROOT / "scripts/check-web-lifecycle.js"), *args], cwd=ROOT,
                                 capture_output=True, text=True, encoding="utf-8", timeout=100)
        if not process.stdout.strip():
            raise ValueError(f"Lifecycle capture failed ({process.returncode}): {process.stderr.strip()}")
        captured = json.loads(process.stdout)
        results = []
        for item in captured["captures"]:
            directory = Path(item["directory"])
            result = verify_launch(directory)
            with (directory / "verification.json").open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            results.append({"scenario": item["scenario"], "directory": str(directory),
                            "verified": result["verified"], "execution": result["execution"]["status"],
                            "recording": result["recording"]["outcome"], "outcome": result["outcome"], "reasons": result["reasons"]})
        summary = {"source": "synthetic", "modelCalled": False, "liveWebVerified": False,
                   "directory": captured["directory"], "checks": results}
        with (Path(captured["directory"]) / "summary.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(summary, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if process.returncode == 0 and len(results) == 3 and all(item["verified"] for item in results) else 1
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({"source": "synthetic", "liveWebVerified": False, "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
