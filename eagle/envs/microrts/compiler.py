"""Compilation helpers for the vendored MicroRTS environment."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from ...project import PROJECT_ROOT


def locate_microrts_root(project_root: Path | None = None) -> Path:
    """Return the vendored MicroRTS root inside the EAGLE repository."""
    root = (project_root or PROJECT_ROOT).resolve()
    candidate = root / "third_party" / "microrts"
    if candidate.exists():
        return candidate
    if (root / "src").exists() and (root / "resources").exists():
        return root
    raise FileNotFoundError(
        f"Unable to locate MicroRTS under {root}. Expected {candidate}."
    )


def compile_microrts(project_root: Path | None = None) -> Path:
    """Compile the vendored MicroRTS Java sources into `bin/`."""
    microrts_root = locate_microrts_root(project_root)
    src_dir = microrts_root / "src"
    lib_dir = microrts_root / "lib"
    bin_dir = microrts_root / "bin"
    sources = sorted(src_dir.rglob("*.java"))
    if not sources:
        raise FileNotFoundError(f"No Java sources found under {src_dir}.")

    bin_dir.mkdir(parents=True, exist_ok=True)
    classpath = f"{lib_dir / '*'}{os.pathsep}{bin_dir}"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".sources",
        prefix="microrts_",
        dir=microrts_root,
        delete=False,
    ) as argfile:
        for path in sources:
            argfile.write(f"{path}\n")
        argfile_path = Path(argfile.name)

    command = [
        "javac",
        "-cp",
        classpath,
        "-d",
        str(bin_dir),
        f"@{argfile_path}",
    ]
    try:
        try:
            subprocess.run(
                command,
                cwd=microrts_root,
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Failed to compile MicroRTS because `javac` was not found on PATH. "
                "Install a JDK or add `javac` to PATH before running gameplay matches."
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            detail = stderr or stdout or "No compiler output was captured."
            raise RuntimeError(
                "MicroRTS compilation failed.\n"
                f"Command: {' '.join(command[:-1])} @<sources>\n"
                f"Details:\n{detail}"
            ) from exc
    finally:
        try:
            argfile_path.unlink(missing_ok=True)
        except PermissionError:
            pass
    return bin_dir
