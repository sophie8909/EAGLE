"""Canonical, repository-backed LLM prompt templates."""

from __future__ import annotations

import json
import re
import string
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPT_TEMPLATE_PATH = REPOSITORY_ROOT / "config" / "prompt_templates.toml"


class PromptTemplateError(ValueError):
    """Raised for malformed prompt template metadata or content."""


@dataclass(frozen=True)
class PromptTemplate:
    prompt_id: str
    role: str
    stages: tuple[str, ...]
    required_variables: tuple[str, ...]
    template: str
    source_path: Path

    @property
    def placeholders(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(_placeholders(self.template)))

    def validate(self, body: str | None = None) -> tuple[str, ...]:
        content = self.template if body is None else body
        if not content.strip():
            raise PromptTemplateError(f"{self.prompt_id}: template must not be empty.")
        placeholders = set(_placeholders(content))
        required = set(self.required_variables)
        missing = sorted(required - placeholders)
        unsupported = sorted(placeholders - required)
        if missing:
            raise PromptTemplateError(f"{self.prompt_id}: missing required placeholders: {', '.join(missing)}")
        if unsupported:
            raise PromptTemplateError(f"{self.prompt_id}: unsupported placeholders: {', '.join(unsupported)}")
        try:
            string.Template(content).substitute({name: "" for name in required})
        except (KeyError, ValueError) as exc:
            raise PromptTemplateError(f"{self.prompt_id}: malformed template syntax: {exc}") from exc
        return tuple(sorted(placeholders))

    def render(self, values: Mapping[str, object], *, body: str | None = None) -> str:
        content = self.template if body is None else body
        self.validate(content)
        missing_values = [name for name in self.required_variables if name not in values]
        if missing_values:
            raise PromptTemplateError(f"{self.prompt_id}: missing render values: {', '.join(missing_values)}")
        return string.Template(content).substitute({name: str(values[name]) for name in self.required_variables})

    def mock_context(self) -> dict[str, str]:
        return {name: f"<{name}>" for name in self.required_variables}


def load_prompt_templates(path: str | Path = DEFAULT_PROMPT_TEMPLATE_PATH) -> dict[str, PromptTemplate]:
    source = Path(path)
    try:
        payload = tomllib.loads(source.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PromptTemplateError(f"Cannot load prompt templates from {source}: {exc}") from exc
    raw_templates = payload.get("templates")
    if not isinstance(raw_templates, dict) or not raw_templates:
        raise PromptTemplateError(f"Prompt template file has no [templates.*] sections: {source}")
    templates: dict[str, PromptTemplate] = {}
    for prompt_id, raw in raw_templates.items():
        if not isinstance(raw, dict):
            raise PromptTemplateError(f"{prompt_id}: template section must be a table.")
        item = PromptTemplate(
            prompt_id=str(prompt_id),
            role=str(raw.get("role", "")),
            stages=tuple(str(value) for value in raw.get("stages", ())),
            required_variables=tuple(str(value) for value in raw.get("required_variables", ())),
            template=str(raw.get("template", "")),
            source_path=source,
        )
        if item.role not in {"reflector", "rewriter", "generator"}:
            raise PromptTemplateError(f"{prompt_id}: role must be reflector, rewriter, or generator.")
        item.validate()
        templates[item.prompt_id] = item
    return templates


def render_prompt(prompt_id: str, values: Mapping[str, object], *, path: str | Path = DEFAULT_PROMPT_TEMPLATE_PATH) -> str:
    try:
        template = load_prompt_templates(path)[prompt_id]
    except KeyError as exc:
        raise PromptTemplateError(f"Unknown prompt template: {prompt_id}") from exc
    return template.render(values)


def save_prompt_template(prompt_id: str, body: str, *, path: str | Path = DEFAULT_PROMPT_TEMPLATE_PATH) -> None:
    """Replace one body while preserving other TOML sections and comments."""
    source = Path(path)
    templates = load_prompt_templates(source)
    if prompt_id not in templates:
        raise PromptTemplateError(f"Unknown prompt template: {prompt_id}")
    templates[prompt_id].validate(body)
    lines = source.read_text(encoding="utf-8").splitlines()
    section = f"[templates.{prompt_id}]"
    start = next((index for index, line in enumerate(lines) if line.strip() == section), None)
    if start is None:
        raise PromptTemplateError(f"Cannot locate {section} in {source}")
    end = next((index for index in range(start + 1, len(lines)) if lines[index].strip().startswith("[templates.")), len(lines))
    template_start = next((index for index in range(start + 1, end) if lines[index].lstrip().startswith("template =")), None)
    if template_start is None:
        raise PromptTemplateError(f"{prompt_id}: template assignment is missing.")
    assignment = lines[template_start].split("=", 1)[1].strip()
    template_end = template_start + 1
    if assignment.startswith(('"""', "'''")):
        delimiter = assignment[:3]
        if assignment.count(delimiter) < 2:
            while template_end < end and delimiter not in lines[template_end]:
                template_end += 1
            template_end += 1
    lines[template_start:template_end] = [f"template = {json.dumps(body, ensure_ascii=False)}"]
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _placeholders(template: str) -> list[str]:
    names: list[str] = []
    for match in string.Template.pattern.finditer(template):
        if match.group("invalid") is not None:
            raise PromptTemplateError(f"Malformed template placeholder near {match.group(0)!r}")
        name = match.group("named") or match.group("braced")
        if name:
            names.append(name)
    return names
