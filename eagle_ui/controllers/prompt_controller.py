"""Initial-candidate and meta-prompt editing through canonical builders."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.prompts import PromptTemplate, load_prompt_templates, save_prompt_template
from generation.agent_template import JavaTemplatePaths, load_java_template, validate_java_template

from .config_controller import update_minimal_yaml


@dataclass(frozen=True)
class InitialPromptData:
    config_path: Path
    strategy_prompts: tuple[str, ...]
    generation_prompt: str
    java_template_path: Path
    java_context: str


class InitialPromptController:
    def load(self, config_path: Path) -> InitialPromptData:
        config = ExperimentConfig.from_file(config_path)
        java_path = config.agent_template_path
        return InitialPromptData(
            config_path=config_path,
            strategy_prompts=config.seed_prompts,
            generation_prompt=config.generation_prompt,
            java_template_path=java_path,
            java_context=load_java_template(JavaTemplatePaths(java_path)),
        )

    def validate(self, strategy_prompts: tuple[str, ...], generation_prompt: str, java_context: str) -> None:
        if not strategy_prompts or any(not value.strip() for value in strategy_prompts):
            raise ValueError("At least one non-empty strategy prompt is required.")
        if not generation_prompt.strip():
            raise ValueError("Generation instructions must not be empty.")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory) / "CandidateAgent.java"
            temporary.write_text(java_context, encoding="utf-8")
            validate_java_template(JavaTemplatePaths(temporary))

    def preview(self, strategy_prompt: str, generation_prompt: str, java_context: str) -> str:
        candidate = Candidate(
            strategy_prompt=strategy_prompt,
            generation_prompt=generation_prompt,
            previous_code=java_context,
        )
        return candidate.generation_input(class_name="CandidateAgent")

    def save(self, data: InitialPromptData, strategy_prompts: tuple[str, ...], generation_prompt: str, java_context: str) -> None:
        self.validate(strategy_prompts, generation_prompt, java_context)
        update_minimal_yaml(
            data.config_path,
            {"seed_prompts": strategy_prompts, "generation_prompt": generation_prompt},
            delete_keys=("seed_prompt_template",),
        )
        data.java_template_path.write_text(java_context, encoding="utf-8")
        ExperimentConfig.from_file(data.config_path).validate()


class MetaPromptController:
    def __init__(self, source_path: Path) -> None:
        self.source_path = source_path

    def load(self) -> dict[str, PromptTemplate]:
        return load_prompt_templates(self.source_path)

    def preview(self, prompt_id: str, body: str) -> str:
        template = self.load()[prompt_id]
        return template.render(template.mock_context(), body=body)

    def save(self, prompt_id: str, body: str) -> None:
        save_prompt_template(prompt_id, body, path=self.source_path)
