"""Generation backends for prompt-to-Java source."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

from eagle.candidate import CandidatePrompt

from .validation import validate_java_source


class GenerationBackend(ABC):
    @abstractmethod
    def generate(self, candidate: CandidatePrompt) -> str:
        """Return Java source code for a candidate prompt."""


class TemplateGenerationBackend(GenerationBackend):
    """Offline backend used for smoke tests until an LLM code generator is wired."""

    def generate(self, candidate: CandidatePrompt) -> str:
        class_name = generated_class_name(candidate.candidate_id)
        source = f"""package ai.generated;

import ai.RandomBiasedAI;
import rts.units.UnitTypeTable;

public class {class_name} extends RandomBiasedAI {{
    public static final String CANDIDATE_ID = "{candidate.candidate_id}";

    public {class_name}(UnitTypeTable utt) {{
        super(utt);
    }}
}}
"""
        validate_java_source(source)
        return source


def generated_class_name(candidate_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", candidate_id)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"Candidate_{cleaned}"
    return f"GeneratedAgent_{cleaned}"


def build_generation_backend(name: str) -> GenerationBackend:
    if name == "template":
        return TemplateGenerationBackend()
    raise ValueError(f"Unknown generation backend: {name}")

