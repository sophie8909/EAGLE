"""Compile the generated eagleJava agent into the vendored MicroRTS build."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ...envs.microrts.compiler import compile_microrts, locate_microrts_root
from ...project import PROJECT_ROOT


EAGLE_JAVA_CLASS_NAME = "eagleJava"


def compile_eagle_java_agent(java_code: str, tmp_dir: str) -> bool:
    """Save `eagleJava.java` and compile it into the MicroRTS class output."""
    tmp_root = Path(tmp_dir).resolve()
    tmp_root.mkdir(parents=True, exist_ok=True)

    source_dir = tmp_root / "ai" / "abstraction"
    source_dir.mkdir(parents=True, exist_ok=True)
    java_path = source_dir / f"{EAGLE_JAVA_CLASS_NAME}.java"
    java_path.write_text(java_code, encoding="utf-8")

    try:
        microrts_root = locate_microrts_root(PROJECT_ROOT)
        bin_dir = compile_microrts(PROJECT_ROOT)
        lib_dir = microrts_root / "lib"
        classpath = f"{lib_dir / '*'}{os.pathsep}{bin_dir}"
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
        return True
    except (FileNotFoundError, subprocess.CalledProcessError, RuntimeError):
        return False
