"""Compilation helpers for the vendored MicroRTS environment."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
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


def compile_microrts(project_root: Path | None = None, *, force: bool = False) -> Path:
    """Compile the vendored MicroRTS Java sources into `bin/` when sources changed."""
    microrts_root = locate_microrts_root(project_root)
    src_dir = microrts_root / "src"
    lib_dir = microrts_root / "lib"
    bin_dir = microrts_root / "bin"
    stamp_path = bin_dir / ".microrts_compile_stamp"
    sources = sorted(src_dir.rglob("*.java"))
    if not sources:
        raise FileNotFoundError(f"No Java sources found under {src_dir}.")

    bin_dir.mkdir(parents=True, exist_ok=True)
    if not force and stamp_path.exists() and any(bin_dir.rglob("*.class")):
        newest_source = max(path.stat().st_mtime for path in sources)
        if newest_source <= stamp_path.stat().st_mtime:
            print("[DEBUG] microrts compile skipped; classes are up to date", flush=True)
            return bin_dir

    started = time.perf_counter()
    classpath = f"{src_dir}{os.pathsep}{lib_dir / '*'}"
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
        stamp_path.write_text(
            f"compiled_at={time.time()}\nelapsed_sec={time.perf_counter() - started:.6f}\n",
            encoding="utf-8",
        )
        print(
            "[DEBUG] microrts compile complete "
            f"elapsed={time.perf_counter() - started:.2f}s",
            flush=True,
        )
    finally:
        try:
            argfile_path.unlink(missing_ok=True)
        except PermissionError:
            pass
    return bin_dir
