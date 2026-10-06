"""Stable seed derivation for reproducible MicroRTS match invocations."""

from __future__ import annotations

import hashlib


def derive_match_seed(
    random_seed: int,
    *,
    candidate_id: str,
    opponent_id: str,
    map_id: str,
    round_index: int,
    candidate_player: int,
    match_index: int,
) -> int:
    """Derive one JVM-safe seed from the run seed and immutable match identity.

    SHA-256 avoids Python's process-randomized ``hash()`` and the result is
    restricted to a positive signed Java ``long`` so it can be passed through
    ``-Deagle.match.seed`` and parsed by MicroRTS on every supported JVM.
    """

    identity = "\x1f".join(
        (
            str(int(random_seed)),
            candidate_id,
            opponent_id,
            map_id,
            str(int(round_index)),
            str(int(candidate_player)),
            str(int(match_index)),
        )
    ).encode("utf-8")
    value = int.from_bytes(hashlib.sha256(identity).digest()[:8], "big")
    return value & 0x7FFF_FFFF_FFFF_FFFF


def derive_candidate_id(
    random_seed: int,
    *,
    generation: int,
    index: int,
    role: str,
    parent_ids: tuple[str, ...] = (),
) -> str:
    """Create a stable generation-qualified candidate identity for deterministic mode."""

    identity = "\x1f".join(
        (
            str(int(random_seed)),
            str(int(generation)),
            str(int(index)),
            role,
            *parent_ids,
        )
    ).encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:12]
    return f"gen_{int(generation):04d}_{digest}"
