"""Compilation adapter for generated Java agents."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CompileResult:
    ok: bool
    command: list[str]
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0

    @property
    def status(self) -> str:
        return "success" if self.ok else "failed"


def compile_generated_agent(
    source_path: Path,
    *,
    microrts_dir: Path,
    output_dir: Path,
    mock: bool = False,
) -> CompileResult:
    source_path = source_path.resolve()
    microrts_dir = microrts_dir.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "javac",
        "-cp",
        os.pathsep.join([str(microrts_dir / "bin"), str(microrts_dir / "lib" / "*")]),
        "-d",
        str(output_dir),
        str(source_path),
    ]
    if mock:
        return CompileResult(ok=True, command=command, stdout="mock compile ok")
    completed = subprocess.run(command, cwd=microrts_dir, capture_output=True, text=True, check=False)
    return CompileResult(
        ok=completed.returncode == 0,
        command=command,
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
    )

