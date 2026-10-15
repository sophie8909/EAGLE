"""Strict, deterministic framework-slot genotype materialization.

This module deliberately has no configuration, Candidate, artifact, or LLM
dependencies.  It validates one immutable framework bundle, validates typed
candidate genomes against that bundle, and renders Java by replacing each
declared marker exactly once.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from eagle.evaluation.determinism import derive_seed


FRAMEWORK_BUNDLE_SCHEMA_VERSION = "eagle-framework-bundle-v1"
SLOT_KINDS = ("integer", "number", "expression_choice")

_BUNDLE_KEYS = {
    "schema_version",
    "framework_id",
    "java_template",
    "slots",
    "slot_generation_prompt",
    "report",
}
_SLOT_KEYS = {
    "slot_id",
    "kind",
    "marker",
    "default",
    "minimum",
    "maximum",
    "step",
    "choices",
    "purpose",
}
_CHOICE_KEYS = {"choice_id", "java_expression", "description"}
_REPORT_KEYS = {
    "architecture_summary",
    "decision_flow",
    "invariants",
    "slot_rationale",
    "assumptions",
    "risks",
}
_SLOT_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_FRAMEWORK_ID_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,127}\Z")
_MARKER_PATTERN = re.compile(r"\{\{EAGLE_SLOT:([a-z][a-z0-9_]{0,63})\}\}")
_MARKER_PREFIX = "{{EAGLE_SLOT:"


GenomeValue = int | float | str


@dataclass(frozen=True)
class ExpressionChoice:
    choice_id: str
    java_expression: str
    description: str

    def to_json_dict(self) -> dict[str, str]:
        return {
            "choice_id": self.choice_id,
            "java_expression": self.java_expression,
            "description": self.description,
        }


@dataclass(frozen=True)
class FrameworkSlot:
    slot_id: str
    kind: str
    marker: str
    default: GenomeValue
    minimum: int | float | None
    maximum: int | float | None
    step: int | float | None
    choices: tuple[ExpressionChoice, ...]
    purpose: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "kind": self.kind,
            "marker": self.marker,
            "default": self.default,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "step": self.step,
            "choices": [choice.to_json_dict() for choice in self.choices],
            "purpose": self.purpose,
        }


@dataclass(frozen=True)
class FrameworkReport:
    architecture_summary: str
    decision_flow: tuple[str, ...]
    invariants: tuple[str, ...]
    slot_rationale: tuple[tuple[str, str], ...]
    assumptions: tuple[str, ...]
    risks: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "architecture_summary": self.architecture_summary,
            "decision_flow": list(self.decision_flow),
            "invariants": list(self.invariants),
            "slot_rationale": dict(self.slot_rationale),
            "assumptions": list(self.assumptions),
            "risks": list(self.risks),
        }


@dataclass(frozen=True)
class FrameworkBundle:
    schema_version: str
    framework_id: str
    java_template: str
    slots: tuple[FrameworkSlot, ...]
    slot_generation_prompt: str
    report: FrameworkReport

    @property
    def slot_ids(self) -> tuple[str, ...]:
        return tuple(slot.slot_id for slot in self.slots)

    @property
    def bundle_sha256(self) -> str:
        return sha256_text(canonical_json(self.to_json_dict()))

    @property
    def template_sha256(self) -> str:
        return sha256_text(self.java_template)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "framework_id": self.framework_id,
            "java_template": self.java_template,
            "slots": [slot.to_json_dict() for slot in self.slots],
            "slot_generation_prompt": self.slot_generation_prompt,
            "report": self.report.to_json_dict(),
        }


@dataclass(frozen=True)
class RenderedFramework:
    source: str
    bundle_sha256: str
    template_sha256: str
    genome_sha256: str
    source_sha256: str


def canonical_slot_marker(slot_id: str) -> str:
    """Return the only accepted marker spelling for a slot identifier."""

    if not isinstance(slot_id, str) or _SLOT_ID_PATTERN.fullmatch(slot_id) is None:
        raise ValueError(f"Invalid framework slot_id: {slot_id!r}")
    return "{{EAGLE_SLOT:" + slot_id + "}}"


def canonical_json(value: Any) -> str:
    """Serialize a validated framework value with stable JSON spelling."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_framework_bundle(payload: Mapping[str, Any]) -> FrameworkBundle:
    """Validate and normalize one exact-schema Gemini framework bundle."""

    data = _require_mapping(payload, "framework bundle")
    _require_exact_keys(data, _BUNDLE_KEYS, "framework bundle")
    if data["schema_version"] != FRAMEWORK_BUNDLE_SCHEMA_VERSION:
        raise ValueError(
            "framework bundle schema_version must be "
            f"{FRAMEWORK_BUNDLE_SCHEMA_VERSION!r}"
        )
    framework_id = _nonempty_string(data["framework_id"], "framework_id")
    if _FRAMEWORK_ID_PATTERN.fullmatch(framework_id) is None:
        raise ValueError(f"Invalid framework_id: {framework_id!r}")
    java_template = _nonempty_string(data["java_template"], "java_template")
    slot_generation_prompt = _nonempty_string(
        data["slot_generation_prompt"], "slot_generation_prompt"
    )

    raw_slots = data["slots"]
    if not isinstance(raw_slots, list) or not raw_slots:
        raise ValueError("framework bundle slots must be a non-empty list")
    slots = tuple(_validate_slot(item, index) for index, item in enumerate(raw_slots))
    slot_ids = tuple(slot.slot_id for slot in slots)
    if len(set(slot_ids)) != len(slot_ids):
        raise ValueError("framework bundle slot_id values must be unique")
    markers = tuple(slot.marker for slot in slots)
    if len(set(markers)) != len(markers):
        raise ValueError("framework bundle markers must be unique")

    declared_markers = set(markers)
    observed_markers = {match.group(0) for match in _MARKER_PATTERN.finditer(java_template)}
    if observed_markers != declared_markers:
        missing = sorted(declared_markers - observed_markers)
        unknown = sorted(observed_markers - declared_markers)
        raise ValueError(
            f"java_template marker set mismatch; missing={missing}, unknown={unknown}"
        )
    for marker in markers:
        count = java_template.count(marker)
        if count != 1:
            raise ValueError(f"java_template marker {marker!r} must occur exactly once; found {count}")
    if java_template.count(_MARKER_PREFIX) != len(markers):
        raise ValueError("java_template contains a malformed EAGLE slot marker")

    report = _validate_report(data["report"], slot_ids)
    return FrameworkBundle(
        schema_version=FRAMEWORK_BUNDLE_SCHEMA_VERSION,
        framework_id=framework_id,
        java_template=java_template,
        slots=slots,
        slot_generation_prompt=slot_generation_prompt,
        report=report,
    )


def load_framework_bundle(
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> FrameworkBundle:
    """Load one UTF-8 JSON bundle and optionally verify its exact file bytes."""

    raw = Path(path).read_bytes()
    file_sha256 = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and file_sha256 != expected_sha256:
        raise ValueError(
            "framework bundle exact-byte SHA-256 mismatch: "
            f"expected {expected_sha256}, got {file_sha256}"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"framework bundle must contain UTF-8 JSON: {path}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("framework bundle must contain a JSON object")
    return validate_framework_bundle(payload)


def validate_genome(
    bundle: FrameworkBundle,
    genome: Mapping[str, Any],
) -> dict[str, GenomeValue]:
    """Validate a genome and return it in canonical bundle slot order."""

    data = _require_mapping(genome, "framework slot genome")
    expected = set(bundle.slot_ids)
    _require_exact_keys(data, expected, "framework slot genome")
    return {
        slot.slot_id: _normalize_slot_value(slot, data[slot.slot_id])
        for slot in bundle.slots
    }


def canonical_genome_json(bundle: FrameworkBundle, genome: Mapping[str, Any]) -> str:
    return canonical_json(validate_genome(bundle, genome))


def genome_sha256(bundle: FrameworkBundle, genome: Mapping[str, Any]) -> str:
    return sha256_text(canonical_genome_json(bundle, genome))


def render_framework(
    bundle: FrameworkBundle,
    genome: Mapping[str, Any],
) -> RenderedFramework:
    """Deterministically replace every declared marker with one typed value."""

    normalized = validate_genome(bundle, genome)
    source = bundle.java_template
    for slot in bundle.slots:
        source = source.replace(
            slot.marker,
            _render_slot_value(slot, normalized[slot.slot_id]),
            1,
        )
    if _MARKER_PREFIX in source:
        raise ValueError("rendered framework retains an unresolved EAGLE slot marker")
    canonical_genome = canonical_json(normalized)
    return RenderedFramework(
        source=source,
        bundle_sha256=bundle.bundle_sha256,
        template_sha256=bundle.template_sha256,
        genome_sha256=sha256_text(canonical_genome),
        source_sha256=sha256_text(source),
    )


def sample_initial_genome(
    bundle: FrameworkBundle,
    *,
    random_seed: int,
    sample_index: int = 0,
) -> dict[str, GenomeValue]:
    """Sample one reproducible valid genome using independent per-slot streams."""

    if isinstance(random_seed, bool) or not isinstance(random_seed, int):
        raise TypeError("random_seed must be an integer")
    if isinstance(sample_index, bool) or not isinstance(sample_index, int) or sample_index < 0:
        raise ValueError("sample_index must be a non-negative integer")
    genome: dict[str, GenomeValue] = {}
    for slot in bundle.slots:
        rng = random.Random(
            derive_seed(
                random_seed,
                "framework_slots",
                bundle.framework_id,
                sample_index,
                slot.slot_id,
            )
        )
        genome[slot.slot_id] = slot_value_at(slot, rng.randrange(slot_value_count(slot)))
    return validate_genome(bundle, genome)


def _validate_slot(payload: object, index: int) -> FrameworkSlot:
    data = _require_mapping(payload, f"slots[{index}]")
    _require_exact_keys(data, _SLOT_KEYS, f"slots[{index}]")
    slot_id = _nonempty_string(data["slot_id"], f"slots[{index}].slot_id")
    marker = _nonempty_string(data["marker"], f"slots[{index}].marker")
    expected_marker = canonical_slot_marker(slot_id)
    if marker != expected_marker:
        raise ValueError(
            f"slots[{index}].marker must be the canonical marker {expected_marker!r}"
        )
    kind = data["kind"]
    if kind not in SLOT_KINDS:
        raise ValueError(f"slots[{index}].kind must be one of {SLOT_KINDS}")
    purpose = _nonempty_string(data["purpose"], f"slots[{index}].purpose")

    raw_choices = data["choices"]
    if not isinstance(raw_choices, list):
        raise ValueError(f"slots[{index}].choices must be a list")
    choices = tuple(
        _validate_choice(choice, index, choice_index)
        for choice_index, choice in enumerate(raw_choices)
    )
    choice_ids = tuple(choice.choice_id for choice in choices)
    if len(set(choice_ids)) != len(choice_ids):
        raise ValueError(f"slots[{index}].choices choice_id values must be unique")

    if kind == "expression_choice":
        if any(data[field] is not None for field in ("minimum", "maximum", "step")):
            raise ValueError(
                f"slots[{index}] expression_choice minimum/maximum/step must be null"
            )
        if not choices:
            raise ValueError(f"slots[{index}] expression_choice choices must not be empty")
        default = data["default"]
        if not isinstance(default, str) or default not in set(choice_ids):
            raise ValueError(
                f"slots[{index}].default must name one expression choice"
            )
        return FrameworkSlot(
            slot_id, kind, marker, default, None, None, None, choices, purpose
        )

    if choices:
        raise ValueError(f"slots[{index}] numeric choices must be empty")
    if kind == "integer":
        minimum = _integer(data["minimum"], f"slots[{index}].minimum")
        maximum = _integer(data["maximum"], f"slots[{index}].maximum")
        step = _integer(data["step"], f"slots[{index}].step")
        default = _integer(data["default"], f"slots[{index}].default")
    else:
        minimum = _finite_number(data["minimum"], f"slots[{index}].minimum")
        maximum = _finite_number(data["maximum"], f"slots[{index}].maximum")
        step = _finite_number(data["step"], f"slots[{index}].step")
        default = _finite_number(data["default"], f"slots[{index}].default")
    if step <= 0:
        raise ValueError(f"slots[{index}].step must be positive")
    if maximum < minimum:
        raise ValueError(f"slots[{index}].maximum must be >= minimum")
    slot = FrameworkSlot(
        slot_id, kind, marker, default, minimum, maximum, step, (), purpose
    )
    _validate_numeric_lattice(slot, f"slots[{index}]")
    _normalize_slot_value(slot, default)
    return slot


def _validate_choice(payload: object, slot_index: int, choice_index: int) -> ExpressionChoice:
    label = f"slots[{slot_index}].choices[{choice_index}]"
    data = _require_mapping(payload, label)
    _require_exact_keys(data, _CHOICE_KEYS, label)
    choice_id = _nonempty_string(data["choice_id"], f"{label}.choice_id")
    if _SLOT_ID_PATTERN.fullmatch(choice_id) is None:
        raise ValueError(f"Invalid expression choice_id: {choice_id!r}")
    java_expression = _nonempty_string(
        data["java_expression"], f"{label}.java_expression"
    )
    if _MARKER_PREFIX in java_expression:
        raise ValueError(f"{label}.java_expression must not contain EAGLE slot markers")
    description = _nonempty_string(data["description"], f"{label}.description")
    return ExpressionChoice(choice_id, java_expression, description)


def _validate_report(payload: object, slot_ids: tuple[str, ...]) -> FrameworkReport:
    data = _require_mapping(payload, "report")
    _require_exact_keys(data, _REPORT_KEYS, "report")
    rationale = _require_mapping(data["slot_rationale"], "report.slot_rationale")
    _require_exact_keys(rationale, set(slot_ids), "report.slot_rationale")
    return FrameworkReport(
        architecture_summary=_nonempty_string(
            data["architecture_summary"], "report.architecture_summary"
        ),
        decision_flow=_string_list(data["decision_flow"], "report.decision_flow"),
        invariants=_string_list(data["invariants"], "report.invariants"),
        slot_rationale=tuple(
            (slot_id, _nonempty_string(rationale[slot_id], f"report.slot_rationale.{slot_id}"))
            for slot_id in slot_ids
        ),
        assumptions=_string_list(data["assumptions"], "report.assumptions"),
        risks=_string_list(data["risks"], "report.risks"),
    )


def _normalize_slot_value(slot: FrameworkSlot, value: Any) -> GenomeValue:
    if slot.kind == "expression_choice":
        if not isinstance(value, str) or value not in {
            choice.choice_id for choice in slot.choices
        }:
            raise ValueError(
                f"genome slot {slot.slot_id!r} must name a declared expression choice"
            )
        return value
    if slot.kind == "integer":
        normalized: int | float = _integer(value, f"genome.{slot.slot_id}")
    else:
        normalized = _finite_number(value, f"genome.{slot.slot_id}")
    assert slot.minimum is not None and slot.maximum is not None and slot.step is not None
    numeric = _decimal(normalized)
    minimum = _decimal(slot.minimum)
    maximum = _decimal(slot.maximum)
    step = _decimal(slot.step)
    if numeric < minimum or numeric > maximum:
        raise ValueError(
            f"genome slot {slot.slot_id!r} must be in [{slot.minimum}, {slot.maximum}]"
        )
    if (numeric - minimum) % step != 0:
        raise ValueError(
            f"genome slot {slot.slot_id!r} must align to step {slot.step} from {slot.minimum}"
        )
    return int(normalized) if slot.kind == "integer" else _normalized_float(normalized)


def _validate_numeric_lattice(slot: FrameworkSlot, label: str) -> None:
    assert slot.minimum is not None and slot.maximum is not None and slot.step is not None
    span = _decimal(slot.maximum) - _decimal(slot.minimum)
    if span % _decimal(slot.step) != 0:
        raise ValueError(f"{label} range must be exactly divisible by step")


def slot_value_count(slot: FrameworkSlot) -> int:
    if slot.kind == "expression_choice":
        return len(slot.choices)
    assert slot.minimum is not None and slot.maximum is not None and slot.step is not None
    return int(
        (_decimal(slot.maximum) - _decimal(slot.minimum)) / _decimal(slot.step)
    ) + 1


def slot_value_at(slot: FrameworkSlot, index: int) -> GenomeValue:
    count = slot_value_count(slot)
    if not 0 <= index < count:
        raise IndexError(f"slot value index {index} is outside [0, {count})")
    if slot.kind == "expression_choice":
        return slot.choices[index].choice_id
    assert slot.minimum is not None and slot.step is not None
    value = _decimal(slot.minimum) + _decimal(slot.step) * index
    return int(value) if slot.kind == "integer" else _normalized_float(float(value))


def slot_value_index(slot: FrameworkSlot, value: GenomeValue) -> int:
    normalized = _normalize_slot_value(slot, value)
    if slot.kind == "expression_choice":
        return next(
            index
            for index, choice in enumerate(slot.choices)
            if choice.choice_id == normalized
        )
    assert slot.minimum is not None and slot.step is not None
    return int((_decimal(normalized) - _decimal(slot.minimum)) / _decimal(slot.step))


def _render_slot_value(slot: FrameworkSlot, value: GenomeValue) -> str:
    if slot.kind == "integer":
        return str(value)
    if slot.kind == "number":
        numeric = float(value)
        if numeric == 0:
            numeric = 0.0
        rendered = repr(numeric)
        return rendered if any(character in rendered for character in ".eE") else rendered + ".0"
    return next(
        choice.java_expression for choice in slot.choices if choice.choice_id == value
    )


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} keys must be strings")
    return value


def _require_exact_keys(
    value: Mapping[str, Any], expected: set[str], label: str
) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{label} keys must be exactly {sorted(expected)}; "
            f"missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}"
        )


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list of strings")
    return tuple(
        _nonempty_string(item, f"{label}[{index}]")
        for index, item in enumerate(value)
    )


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    try:
        normalized = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(normalized):
        raise ValueError(f"{label} must be a finite number")
    return _normalized_float(normalized)


def _normalized_float(value: int | float) -> float:
    normalized = float(value)
    return 0.0 if normalized == 0 else normalized


def _decimal(value: int | float) -> Decimal:
    return Decimal(str(value))


__all__ = [
    "FRAMEWORK_BUNDLE_SCHEMA_VERSION",
    "SLOT_KINDS",
    "ExpressionChoice",
    "FrameworkBundle",
    "FrameworkReport",
    "FrameworkSlot",
    "GenomeValue",
    "RenderedFramework",
    "canonical_genome_json",
    "canonical_json",
    "canonical_slot_marker",
    "genome_sha256",
    "load_framework_bundle",
    "render_framework",
    "sample_initial_genome",
    "sha256_text",
    "slot_value_at",
    "slot_value_count",
    "slot_value_index",
    "validate_framework_bundle",
    "validate_genome",
]
