"""Canonical loader for the repository's one-file-per-prompt resources."""

from __future__ import annotations

import re
import string
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


def normalize_prompt(prompt: str, *, max_chars: int, max_lines: int) -> str:
    """Normalize a prompt before it becomes part of the candidate genotype.

    Prompt limits are enforced at the genotype boundary so every mutation,
    crossover, and resume path sees the same bounded representation.
    """

    lines: list[str] = []
    previous_blank = False
    for line in str(prompt).strip().splitlines():
        if not line.strip():
            if lines and not previous_blank:
                lines.append("")
            previous_blank = True
            continue
        lines.append(line.rstrip())
        previous_blank = False

    while lines and not lines[-1]:
        lines.pop()

    bounded = "\n".join(lines[:max_lines])
    return bounded[:max_chars].rstrip()


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPT_DIR = REPOSITORY_ROOT / "prompts"
DEFAULT_PROMPT_MANIFEST_PATH = DEFAULT_PROMPT_DIR / "manifest.toml"
# Compatibility name for callers that used the old combined TOML path.
DEFAULT_PROMPT_TEMPLATE_PATH = DEFAULT_PROMPT_MANIFEST_PATH


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


def _manifest_path(path: str | Path) -> Path:
    source = Path(path)
    return source / "manifest.toml" if source.is_dir() else source


def load_prompt_templates(path: str | Path = DEFAULT_PROMPT_MANIFEST_PATH) -> dict[str, PromptTemplate]:
    source = _manifest_path(path)
    try:
        payload = tomllib.loads(source.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PromptTemplateError(f"Cannot load prompt manifest from {source}: {exc}") from exc
    raw_templates = payload.get("prompts")
    if not isinstance(raw_templates, dict) or not raw_templates:
        raise PromptTemplateError(f"Prompt manifest has no [prompts.*] sections: {source}")
    templates: dict[str, PromptTemplate] = {}
    seen_files: set[Path] = set()
    for prompt_id, raw in raw_templates.items():
        if not isinstance(raw, dict):
            raise PromptTemplateError(f"{prompt_id}: prompt metadata must be a table.")
        filename = str(raw.get("file", "")).strip()
        if not filename:
            raise PromptTemplateError(f"{prompt_id}: file is required.")
        prompt_path = (source.parent / filename).resolve()
        try:
            prompt_path.relative_to(source.parent.resolve())
        except ValueError as exc:
            raise PromptTemplateError(f"{prompt_id}: prompt file must stay inside {source.parent}.") from exc
        if prompt_path in seen_files:
            raise PromptTemplateError(f"{prompt_id}: prompt file is already assigned: {prompt_path.name}")
        seen_files.add(prompt_path)
        try:
            body = prompt_path.read_text(encoding="utf-8").rstrip()
        except OSError as exc:
            raise PromptTemplateError(f"{prompt_id}: cannot read prompt file {prompt_path}: {exc}") from exc
        item = PromptTemplate(
            prompt_id=str(prompt_id),
            role=str(raw.get("role", "")),
            stages=tuple(str(value) for value in raw.get("stages", ())),
            required_variables=tuple(str(value) for value in raw.get("required_variables", ())),
            template=body,
            source_path=prompt_path,
        )
        if item.role not in {"reflector", "rewriter", "generator", "match_commentator", "coach", "seed", "preflight", "reference"}:
            raise PromptTemplateError(f"{prompt_id}: unsupported role {item.role!r}.")
        item.validate()
        templates[item.prompt_id] = item
    return templates


def render_prompt(prompt_id: str, values: Mapping[str, object], *, path: str | Path = DEFAULT_PROMPT_MANIFEST_PATH) -> str:
    try:
        template = load_prompt_templates(path)[prompt_id]
    except KeyError as exc:
        raise PromptTemplateError(f"Unknown prompt template: {prompt_id}") from exc
    return template.render(values)


def load_prompt(prompt_id: str, *, path: str | Path = DEFAULT_PROMPT_MANIFEST_PATH) -> str:
    """Load a static prompt or prompt fragment that has no variables."""

    return render_prompt(prompt_id, {}, path=path)


def save_prompt_template(prompt_id: str, body: str, *, path: str | Path = DEFAULT_PROMPT_MANIFEST_PATH) -> None:
    """Replace exactly one prompt body without rewriting any other prompt file."""

    templates = load_prompt_templates(path)
    if prompt_id not in templates:
        raise PromptTemplateError(f"Unknown prompt template: {prompt_id}")
    template = templates[prompt_id]
    template.validate(body)
    template.source_path.write_text(body.rstrip() + "\n", encoding="utf-8")


def _placeholders(template: str) -> list[str]:
    names: list[str] = []
    for match in string.Template.pattern.finditer(template):
        if match.group("invalid") is not None:
            raise PromptTemplateError(f"Malformed template placeholder near {match.group(0)!r}")
        name = match.group("named") or match.group("braced")
        if name:
            names.append(name)
    return names
