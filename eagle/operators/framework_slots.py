"""Per-slot variation operators for framework-slot genomes."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Mapping

from eagle.evaluation.determinism import derive_seed
from eagle.generation.framework_slots import (
    FrameworkBundle,
    GenomeValue,
    slot_value_at,
    slot_value_count,
    slot_value_index,
    validate_genome,
)


@dataclass(frozen=True)
class SlotCrossoverResult:
    genome: dict[str, GenomeValue]
    slot_parent_ids: dict[str, str]
    source_parent_ids: tuple[str, ...]

    @property
    def slot_provenance(self) -> dict[str, dict[str, str]]:
        return {
            slot_id: {"parent_id": parent_id, "operation": "crossover"}
            for slot_id, parent_id in self.slot_parent_ids.items()
        }


@dataclass(frozen=True)
class SlotMutationResult:
    genome: dict[str, GenomeValue]
    slot_parent_ids: dict[str, str]
    source_parent_ids: tuple[str, ...]
    mutated_slot_id: str | None
    previous_value: GenomeValue | None
    new_value: GenomeValue | None
    applied: bool

    @property
    def slot_provenance(self) -> dict[str, dict[str, str]]:
        return {
            slot_id: {
                "parent_id": parent_id,
                "operation": (
                    "mutation" if self.applied and slot_id == self.mutated_slot_id else "copy"
                ),
            }
            for slot_id, parent_id in self.slot_parent_ids.items()
        }


def crossover_framework_slots(
    bundle: FrameworkBundle,
    parent_a_genome: Mapping[str, Any],
    parent_b_genome: Mapping[str, Any],
    *,
    parent_a_id: str,
    parent_b_id: str,
    random_seed: int,
    generation: int,
    child_index: int,
) -> SlotCrossoverResult:
    """Choose each slot independently and retain its exact source parent."""

    _validate_identity(parent_a_id, "parent_a_id")
    _validate_identity(parent_b_id, "parent_b_id")
    _validate_context(random_seed, generation, child_index)
    parent_a = validate_genome(bundle, parent_a_genome)
    parent_b = validate_genome(bundle, parent_b_genome)
    child: dict[str, GenomeValue] = {}
    provenance: dict[str, str] = {}
    for slot in bundle.slots:
        rng = random.Random(
            derive_seed(
                random_seed,
                "framework_slots",
                "crossover",
                bundle.framework_id,
                generation,
                child_index,
                parent_a_id,
                parent_b_id,
                slot.slot_id,
            )
        )
        if rng.randrange(2) == 0:
            child[slot.slot_id] = parent_a[slot.slot_id]
            provenance[slot.slot_id] = parent_a_id
        else:
            child[slot.slot_id] = parent_b[slot.slot_id]
            provenance[slot.slot_id] = parent_b_id
    normalized = validate_genome(bundle, child)
    return SlotCrossoverResult(
        genome=normalized,
        slot_parent_ids=provenance,
        source_parent_ids=_ordered_unique(
            provenance[slot.slot_id] for slot in bundle.slots
        ),
    )


def mutate_framework_slot(
    bundle: FrameworkBundle,
    genome: Mapping[str, Any],
    *,
    random_seed: int,
    generation: int,
    child_index: int,
    parent_id: str | None = None,
    slot_parent_ids: Mapping[str, str] | None = None,
    slot_id: str | None = None,
) -> SlotMutationResult:
    """Mutate exactly one selected slot to a different legal value.

    ``slot_parent_ids`` can carry component provenance from crossover.  A
    direct one-parent mutation may instead provide ``parent_id``, which is
    expanded to every slot.  Mutation changes provenance operation metadata,
    but the evidence/source parent for the mutated value remains explicit.
    """

    _validate_context(random_seed, generation, child_index)
    normalized = validate_genome(bundle, genome)
    provenance = _normalize_provenance(
        bundle,
        parent_id=parent_id,
        slot_parent_ids=slot_parent_ids,
    )
    mutable_slots = [
        slot for slot in bundle.slots if slot_value_count(slot) > 1
    ]
    selected = None
    if slot_id is not None:
        selected = next((slot for slot in bundle.slots if slot.slot_id == slot_id), None)
        if selected is None:
            raise ValueError(f"Unknown framework slot_id for mutation: {slot_id!r}")
    elif mutable_slots:
        rng = random.Random(
            derive_seed(
                random_seed,
                "framework_slots",
                "mutation_slot",
                bundle.framework_id,
                generation,
                child_index,
            )
        )
        selected = mutable_slots[rng.randrange(len(mutable_slots))]

    if selected is None or slot_value_count(selected) <= 1:
        return SlotMutationResult(
            genome=normalized,
            slot_parent_ids=provenance,
            source_parent_ids=_ordered_unique(
                provenance[item.slot_id] for item in bundle.slots
            ),
            mutated_slot_id=None if selected is None else selected.slot_id,
            previous_value=None if selected is None else normalized[selected.slot_id],
            new_value=None if selected is None else normalized[selected.slot_id],
            applied=False,
        )

    previous = normalized[selected.slot_id]
    old_index = slot_value_index(selected, previous)
    count = slot_value_count(selected)
    value_rng = random.Random(
        derive_seed(
            random_seed,
            "framework_slots",
            "mutation_value",
            bundle.framework_id,
            generation,
            child_index,
            selected.slot_id,
        )
    )
    new_index = value_rng.randrange(count - 1)
    if new_index >= old_index:
        new_index += 1
    new_value = slot_value_at(selected, new_index)
    child = dict(normalized)
    child[selected.slot_id] = new_value
    child = validate_genome(bundle, child)
    return SlotMutationResult(
        genome=child,
        slot_parent_ids=provenance,
        source_parent_ids=_ordered_unique(
            provenance[item.slot_id] for item in bundle.slots
        ),
        mutated_slot_id=selected.slot_id,
        previous_value=previous,
        new_value=child[selected.slot_id],
        applied=True,
    )


# Clear aliases for callers that describe these operations in genotype terms.
crossover_slot_genomes = crossover_framework_slots
mutate_slot_genome = mutate_framework_slot


def _normalize_provenance(
    bundle: FrameworkBundle,
    *,
    parent_id: str | None,
    slot_parent_ids: Mapping[str, str] | None,
) -> dict[str, str]:
    if slot_parent_ids is None:
        if parent_id is None:
            raise ValueError("mutation requires parent_id or slot_parent_ids")
        _validate_identity(parent_id, "parent_id")
        return {slot.slot_id: parent_id for slot in bundle.slots}
    if not isinstance(slot_parent_ids, Mapping):
        raise ValueError("slot_parent_ids must be a mapping")
    expected = set(bundle.slot_ids)
    actual = set(slot_parent_ids)
    if actual != expected:
        raise ValueError(
            "slot_parent_ids must contain exactly the framework slot IDs; "
            f"missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}"
        )
    normalized: dict[str, str] = {}
    for slot in bundle.slots:
        source_id = slot_parent_ids[slot.slot_id]
        _validate_identity(source_id, f"slot_parent_ids.{slot.slot_id}")
        normalized[slot.slot_id] = source_id
    if parent_id is not None:
        _validate_identity(parent_id, "parent_id")
    return normalized


def _validate_identity(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


def _validate_context(random_seed: object, generation: object, child_index: object) -> None:
    if isinstance(random_seed, bool) or not isinstance(random_seed, int):
        raise ValueError("random_seed must be an integer")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise ValueError("generation must be a non-negative integer")
    if isinstance(child_index, bool) or not isinstance(child_index, int) or child_index < 0:
        raise ValueError("child_index must be a non-negative integer")


def _ordered_unique(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


__all__ = [
    "SlotCrossoverResult",
    "SlotMutationResult",
    "crossover_framework_slots",
    "crossover_slot_genomes",
    "mutate_framework_slot",
    "mutate_slot_genome",
]
