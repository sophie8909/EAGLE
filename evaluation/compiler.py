"""Compilation adapter with structured javac diagnostics."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class CompilerDiagnostic:
    severity: str
    code: str | None
    message: str
    file: str | None
    line: int | None
    column: int | None
    raw: str = ""

    def to_json_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "raw": self.raw,
        }


@dataclass(frozen=True)
class CompileResult:
    ok: bool
    command: list[str]
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    diagnostics: tuple[CompilerDiagnostic, ...] = field(default_factory=tuple)

    @property
    def status(self) -> str:
        return "success" if self.ok else "failed"

    @property
    def warnings(self) -> tuple[CompilerDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == "warning")

    @property
    def errors(self) -> tuple[CompilerDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == "error")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "status": self.status,
            "command": list(self.command),
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "diagnostics": [item.to_json_dict() for item in self.diagnostics],
            "warning_count": len(self.warnings),
            "error_count": len(self.errors),
        }


_DIAGNOSTIC_PATTERN = re.compile(
    r"^(?P<file>.*?):(?P<line>\d+)(?::(?P<column>\d+))?:\s*"
    r"(?P<severity>error|warning|note):\s*(?P<message>.*)$",
    re.IGNORECASE,
)
_CODE_PATTERN = re.compile(r"^\[(?P<code>[^\]]+)\]\s*(?P<message>.*)$")


def parse_compiler_diagnostics(output: str | Iterable[str]) -> tuple[CompilerDiagnostic, ...]:
    lines = output.splitlines() if isinstance(output, str) else list(output)
    diagnostics: list[CompilerDiagnostic] = []
    seen: set[tuple[object, ...]] = set()
    for raw_line in lines:
        line = raw_line.strip()
        match = _DIAGNOSTIC_PATTERN.match(line)
        if match is None:
            continue
        severity = match.group("severity").lower()
        message = match.group("message").strip()
        code_match = _CODE_PATTERN.match(message)
        code = code_match.group("code").strip() if code_match else None
        if code_match:
            message = code_match.group("message").strip()
        diagnostic = CompilerDiagnostic(
            severity=severity,
            code=code,
            message=message,
            file=match.group("file").strip() or None,
            line=int(match.group("line")),
            column=int(match.group("column")) if match.group("column") else None,
            raw=raw_line.rstrip(),
        )
        identity = (
            diagnostic.severity,
            diagnostic.code,
            diagnostic.message,
            diagnostic.file,
            diagnostic.line,
            diagnostic.column,
        )
        if identity not in seen:
            seen.add(identity)
            diagnostics.append(diagnostic)
    return tuple(diagnostics)


def compile_generated_agent(
    source_path: Path | tuple[Path, ...],
    *,
    microrts_dir: Path,
    output_dir: Path,
    mock: bool = False,
) -> CompileResult:
    source_paths = (source_path,) if isinstance(source_path, Path) else source_path
    source_paths = tuple(path.resolve() for path in source_paths)
    for path in source_paths:
        if "EAGLE_BODY" in path.read_text(encoding="utf-8"):
            raise ValueError(f"Refusing to compile unresolved Java behavior template: {path}")
    microrts_dir = microrts_dir.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "javac",
        "-Xlint:all",
        "-cp",
        os.pathsep.join([str(microrts_dir / "bin"), str(microrts_dir / "lib" / "*")]),
        "-d",
        str(output_dir),
        *(str(path) for path in source_paths),
    ]
    if mock:
        return CompileResult(ok=True, command=command, stdout="mock compile ok")
    completed = subprocess.run(command, cwd=microrts_dir, capture_output=True, text=True, check=False)
    diagnostics = parse_compiler_diagnostics(completed.stdout + "\n" + completed.stderr)
    return CompileResult(
        ok=completed.returncode == 0,
        command=command,
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
        diagnostics=diagnostics,
    )
