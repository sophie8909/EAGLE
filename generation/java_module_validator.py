"""Structural validation for generated Java behavior bodies."""
from __future__ import annotations
import re

FORBIDDEN = re.compile(r"\b(package|import|class|interface|enum|record)\b")
METHOD = re.compile(r"\b(?:public|private|protected|static|final)\s+[\w<>\[\], ?]+\s+\w+\s*\([^;{}]*\)\s*\{")

def validate_function_module(source: str, module: str) -> None:
    if not source.strip(): raise ValueError(f"Generated function body {module} must not be empty.")
    if "```" in source: raise ValueError(f"Generated function body {module} contains markdown fences.")
    cleaned = re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '', source, flags=re.DOTALL)
    bad = FORBIDDEN.search(cleaned)
    if bad: raise ValueError(f"Generated function body {module} must not declare {bad.group(1)}.")
    if METHOD.search(cleaned): raise ValueError(f"Generated function body {module} must not declare methods.")
    depth = 0
    for char in cleaned:
        if char == '{': depth += 1
        elif char == '}':
            depth -= 1
            if depth < 0: raise ValueError(f"Generated function body {module} closes the predefined scope.")
    if depth: raise ValueError(f"Generated function body {module} has unbalanced braces.")
