"""Parent replica construction and audit sidecars."""

from __future__ import annotations

import hashlib
from pathlib import Path

from eagle.candidate import Candidate
from eagle.evaluation.determinism import derive_candidate_id
from eagle.run_artifacts import atomic_json


def build_parent_evaluation_replicas(
    parents: list[Candidate],
    *,
    generation: int,
    random_seed: int = 0,
) -> list[Candidate]:
    """Create unevaluated, separately identifiable parent re-materializations.

    This is intentionally a diagnostic-only construction.  A replica keeps the
    source parent's complete pre-generation genotype and component provenance,
    but does not inherit its phenotype, objective, failure, or artifact state.
    """

    replicas: list[Candidate] = []
    for index, parent in enumerate(parents):
        replicas.append(Candidate(
            id=(
                derive_candidate_id(
                    random_seed,
                    generation=generation,
                    index=index,
                    role="parent_rematerialization",
                    parent_ids=(parent.id,),
                )
            ),
            generation=generation,
            parent_ids=parent.parent_ids,
            strategy_prompt=parent.strategy_prompt,
            generation_prompt=parent.generation_prompt,
            inherited_java=parent.inherited_java,
            java_parent_id=parent.java_parent_id,
            operator="experimental_parent_rematerialization",
            mutation_type=None,
            strategy_parent_id=parent.strategy_parent_id,
            generation_prompt_parent_id=parent.generation_prompt_parent_id,
            source_candidate_ids=parent.source_candidate_ids,
            # Re-materialization may change the executable phenotype.
            semantic_signature={},
            strategy_signature=dict(parent.strategy_signature),
            strategy_niche=parent.strategy_niche,
            metadata={
                "experimental_parent_evaluation": {
                    "source_parent_id": parent.id,
                    "source_birth_generation": parent.generation,
                },
            },
        ))
    return replicas


def build_self_play_fitness_refresh_replicas(
    parents: list[Candidate],
    *,
    generation: int,
    random_seed: int = 0,
) -> list[Candidate]:
    """Create fresh identities that preserve parent genotypes and phenotypes exactly."""

    return [
        Candidate(
            id=(
                derive_candidate_id(
                    random_seed,
                    generation=generation,
                    index=index,
                    role="self_play_fitness_refresh",
                    parent_ids=(parent.id,),
                )
            ),
            generation=generation,
            parent_ids=(parent.id,),
            strategy_prompt=parent.strategy_prompt,
            generation_prompt=parent.generation_prompt,
            inherited_java=parent.inherited_java,
            java_parent_id=parent.id,
            generated_java=parent.generated_java,
            operator="self_play_fitness_refresh",
            mutation_type=None,
            strategy_parent_id=parent.id,
            generation_prompt_parent_id=parent.id,
            source_candidate_ids=(parent.id,),
            # The refresh reuses byte-identical Java and the immutable probe
            # suite, so its semantic evidence remains valid and cacheable.
            semantic_signature=dict(parent.semantic_signature),
            strategy_signature=dict(parent.strategy_signature),
            strategy_niche=parent.strategy_niche,
            metadata={
                "self_play_fitness_refresh": {
                    "source_parent_id": parent.id,
                    "source_birth_generation": parent.generation,
                },
            },
        )
        for index, parent in enumerate(parents)
    ]


def write_self_play_parent_refresh_sidecar(
    run_dir: Path,
    *,
    generation: int,
    source_parents: list[Candidate],
    replicas: list[Candidate],
    selected_ids: set[str],
) -> None:
    records = []
    for source, replica in zip(source_parents, replicas, strict=True):
        source_hash = hashlib.sha256(source.generated_java.encode("utf-8")).hexdigest()
        replica_hash = hashlib.sha256(replica.generated_java.encode("utf-8")).hexdigest()
        records.append({
            "source_parent_id": source.id,
            "source_birth_generation": source.generation,
            "replica_candidate_id": replica.id,
            "source_generated_java_sha256": source_hash,
            "replica_generated_java_sha256": replica_hash,
            "generated_java_preserved": source_hash == replica_hash,
            "source_evaluation_context_id": source.game_eval_result.get("evaluation_context_id"),
            "replica_evaluation_context_id": replica.game_eval_result.get("evaluation_context_id"),
            "selected": replica.id in selected_ids,
        })
    atomic_json(
        run_dir / "generations" / f"generation_{generation:04d}_self_play_parent_refresh.json",
        {
            "schema_version": "eagle-self-play-parent-refresh-v1",
            "generation": generation,
            "mode": "phenotype_preserving_fitness_refresh",
            "records": records,
        },
    )


def write_parent_evaluation_sidecar(
    run_dir: Path,
    *,
    generation: int,
    source_parents: list[Candidate],
    replicas: list[Candidate],
    selected_ids: set[str],
) -> None:
    """Persist the source-to-replica audit trail for the diagnostic treatment."""

    def digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    records = []
    for source, replica in zip(source_parents, replicas, strict=True):
        source_genotype_hashes = {
            "strategy_prompt": digest(source.strategy_prompt),
            "generation_prompt": digest(source.generation_prompt),
            "inherited_java": digest(source.inherited_java),
        }
        replica_genotype_hashes = {
            "strategy_prompt": digest(replica.strategy_prompt),
            "generation_prompt": digest(replica.generation_prompt),
            "inherited_java": digest(replica.inherited_java),
        }
        source_java_hash = digest(source.generated_java)
        replica_java_hash = digest(replica.generated_java)
        records.append({
            "source_parent_id": source.id,
            "source_birth_generation": source.generation,
            "replica_candidate_id": replica.id,
            "genotype_sha256": {
                "source": source_genotype_hashes,
                "replica": replica_genotype_hashes,
            },
            "genotype_hashes_match": source_genotype_hashes == replica_genotype_hashes,
            "source_generated_java_sha256": source_java_hash,
            "replica_generated_java_sha256": replica_java_hash,
            "generated_java_changed": source_java_hash != replica_java_hash,
            "source_fitness_objectives": dict(source.fitness_objectives),
            "replica_fitness_objectives": dict(replica.fitness_objectives),
            "source_status": source.status,
            "replica_status": replica.status,
            "selected": replica.id in selected_ids,
        })
    atomic_json(
        run_dir / "generations" / f"generation_{generation:04d}_parent_rematerialization.json",
        {
            "schema_version": "eagle-parent-rematerialization-v1",
            "generation": generation,
            "mode": "regenerate_same_genotype",
            "records": records,
        },
    )
