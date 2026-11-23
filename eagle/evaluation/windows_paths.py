"""Translate evaluation paths between Windows filesystem and Java arguments."""

import os
from pathlib import Path


_EXTENDED = "\\\\?\\"
_EXTENDED_UNC = _EXTENDED + "UNC\\"


def windows_output_path(path: Path) -> Path:
    """Use the extended namespace before creating deeply nested artifacts."""
    if os.name != "nt" or str(path).startswith(_EXTENDED):
        return path
    name = str(path.resolve())
    if name.startswith("\\\\"):
        return Path(_EXTENDED_UNC + name[2:])
    return Path(_EXTENDED + name)


def resolve_evaluation_path(path: Path) -> Path:
    """Keep the extended namespace even when resolving a short parent."""
    return path if str(path).startswith(_EXTENDED) else path.resolve()


def java_path(path: Path) -> str:
    """Java on Windows accepts normal absolute paths, including long ones."""
    name = str(path)
    if name.startswith(_EXTENDED_UNC):
        return "\\\\" + name[len(_EXTENDED_UNC):]
    return name.removeprefix(_EXTENDED)
