"""Preflight the known Windows Harness installer directory limit."""
from pathlib import Path
import sys
from uuid import UUID

from .formats import require


def check_output_root(runs_root, *, kind):
    if sys.platform != "win32":
        return
    reserved = str(UUID(int=0))
    layouts = {
        "case": (reserved,),
        "batch": (reserved, "cases", reserved),
        "experiment": (reserved, "batches", reserved, "cases", reserved),
        "resume-batch": (reserved, "batches", reserved, "cases", reserved),
        "resume-experiment": (reserved, "continuations", reserved, "batches", reserved, "cases", reserved),
    }
    operation = Path(runs_root).resolve().joinpath(*layouts[kind], "home", "profiles", "headless",
                                                ".plugin-manager", "logs", "operation-XXXXXX")
    length = len(str(operation).encode("utf-16-le")) // 2
    boundary = "no continuation was claimed" if kind.startswith("resume-") else "no execution output was created"
    require(length < 248, f"Windows Harness preparation path requires {length} UTF-16 code units (limit 247); "
            f"choose a shorter --runs-root; {boundary}")
