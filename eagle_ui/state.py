"""Explicit in-memory state for the EAGLE GUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RunState:
    config_path: Path = Path("configs/eagle_minimal.yaml")
    effective_run_dir: Path | None = None
    mock: bool = False
    running: bool = False
    returncode: int | None = None
    current_generation: int | None = None
    current_candidate: str | None = None
    completed_candidates: int = 0
    failed_candidates: int = 0
    log_lines: list[str] = field(default_factory=list)


@dataclass
class SelectionState:
    run_dir: Path | None = None
    candidate_id: str | None = None


@dataclass
class EditorState:
    source_path: Path | None = None
    loaded_text: str = ""
    edited_text: str = ""

    @property
    def dirty(self) -> bool:
        return self.edited_text != self.loaded_text

    def restore(self) -> None:
        self.edited_text = self.loaded_text


@dataclass
class AppState:
    repository_root: Path
    run: RunState = field(default_factory=RunState)
    selection: SelectionState = field(default_factory=SelectionState)
    llm_editor: EditorState = field(default_factory=EditorState)
    prompt_editor: EditorState = field(default_factory=EditorState)
    meta_prompt_editor: EditorState = field(default_factory=EditorState)
