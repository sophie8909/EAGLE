"""Optional Python bytecode precompilation for EAGLE startup paths."""

from __future__ import annotations

import compileall
import time
from pathlib import Path

from eagle.project import PROJECT_ROOT


def precompile_python_sources(project_root: str | Path | None = None) -> dict[str, float | int]:
    """Compile EAGLE Python modules to bytecode and return timing metadata."""
    root = Path(project_root or PROJECT_ROOT).resolve()
    targets = [root / "eagle", root / "eagle_ui", root / "scripts"]
    started = time.perf_counter()
    attempted = 0
    ok = True
    for target in targets:
        if not target.exists():
            continue
        attempted += 1
        ok = compileall.compile_dir(
            str(target),
            quiet=1,
            force=False,
            legacy=False,
        ) and ok
    return {
        "targets": attempted,
        "ok": int(bool(ok)),
        "elapsed_sec": time.perf_counter() - started,
    }
