"""Compile the generated eagleJava agent into the vendored MicroRTS build."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ...envs.microrts.compiler import compile_microrts, locate_microrts_root
from ...project import PROJECT_ROOT


EAGLE_JAVA_CLASS_NAME = "eagleJava"


def compile_eagle_java_agent(java_code: str, tmp_dir: str) -> None:
    """Save `eagleJava.java` and compile it into the MicroRTS class output.

    Args:
        java_code: Complete Java source for the generated `eagleJava` class.
        tmp_dir: Directory used to store the generated source before compilation.

    Raises:
        RuntimeError: If `javac` is missing or compilation fails.
    """
    tmp_root = Path(tmp_dir).resolve()
    tmp_root.mkdir(parents=True, exist_ok=True)

    source_dir = tmp_root / "ai" / "abstraction"
    source_dir.mkdir(parents=True, exist_ok=True)
    java_path = source_dir / f"{EAGLE_JAVA_CLASS_NAME}.java"
    java_path.write_text(java_code, encoding="utf-8")

    microrts_root = locate_microrts_root(PROJECT_ROOT)
    bin_dir = compile_microrts(PROJECT_ROOT)
    lib_dir = microrts_root / "lib"
    classpath = f"{lib_dir / '*'}{os.pathsep}{bin_dir}"
    try:
        subprocess.run(
            [
                "javac",
                "-cp",
                classpath,
                "-d",
                str(bin_dir),
                str(java_path),
            ],
            cwd=microrts_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Failed to compile eagleJava because `javac` was not found on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        detail = stderr or stdout or "No compiler output was captured."
        raise RuntimeError(f"eagleJava compilation failed:\n{detail}") from exc
