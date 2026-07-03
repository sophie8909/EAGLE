"""Generated Java source validation."""

from __future__ import annotations


def validate_java_source(source: str) -> None:
    required = ["package ai.generated;", "public class", "UnitTypeTable"]
    missing = [token for token in required if token not in source]
    if missing:
        raise ValueError(f"Generated Java source is missing required tokens: {', '.join(missing)}")

