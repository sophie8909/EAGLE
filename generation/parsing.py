"""Parsing helpers for model outputs that contain Java source."""

from __future__ import annotations

import re


JAVA_FENCE_RE = re.compile(r"```(?:java)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_java_source(output: str) -> str:
    match = JAVA_FENCE_RE.search(output)
    if match:
        return match.group(1).strip()
    return output.strip()

