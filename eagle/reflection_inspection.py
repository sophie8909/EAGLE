"""Standalone, repeatable inspection of EAGLE's three reflection operators.

The inspection owns one evaluated Worker Rush parent, clones the same mutation
subject for every trial, and runs each production reflection operator without
entering the evolutionary search loop.  Its artifacts are intentionally
redundant and human-oriented: the production mutation artifacts remain intact,
while per-trial indexes and diffs make request/response auditing inexpensive.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from generation.backend import InitialJavaSeedBackend

from .artifacts import write_candidate_inputs
from .candidate import Candidate
from .config import ExperimentConfig
from .evaluation import evaluate_population
from .reflection_context import ReflectionContext, build_reflection_context
from .runtime.config import runtime_config_from_experiment
from .runtime.processes import RuntimeManager
from .search_runtime import build_search_runtime
from .strategy_reflection import normalize_mutation_intent


INSPECTION_SCHEMA_VERSION = "eagle-reflection-inspection-v2"
REFLECTION_TYPES = ("strategy", "code", "prompt_compliance")
EXPECTED_CHANGED_FIELDS = {
    "strategy": ("strategy_prompt",),
    "code": ("generation_prompt",),
    "prompt_compliance": ("strategy_prompt", "generation_prompt"),
}
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ReflectionInspectionConfig:
    """Small wrapper around one canonical ExperimentConfig."""

    name: str
    experiment_config_path: Path
    output_root: Path
    trials_per_reflection: int = 3
    strategy_mutation_intent: str = "REFINE"
    reflection_order: tuple[str, ...] = REFLECTION_TYPES

    @classmethod
    def from_file(cls, path: str | Path) -> "ReflectionInspectionConfig":
        source = Path(path).expanduser().resolve()
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Reflection inspection config must contain a YAML mapping.")
        if payload.get("schema_version") != INSPECTION_SCHEMA_VERSION:
            raise ValueError(
                "Unsupported reflection inspection schema version: "
                f"{payload.get('schema_version')!r}"
            )
        allowed = {
            "schema_version",
            "name",
            "experiment_config",
            "output_root",
            "trials_per_reflection",
            "strategy_mutation_intent",
            "reflection_order",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError("Unknown reflection inspection fields: " + ", ".join(unknown))

        name = str(payload.get("name") or "worker_rush_reflection_inspection").strip()
        if not name:
            raise ValueError("Reflection inspection name must not be empty.")
        experiment_path = _repository_path(payload.get("experiment_config"), "experiment_config")
        output_root = _repository_path(
            payload.get("output_root", "runs/reflection_inspections"),
            "output_root",
            require_exists=False,
        )
        trials = int(payload.get("trials_per_reflection", 3))
        if trials < 1:
            raise ValueError("trials_per_reflection must be positive.")
        intent = str(payload.get("strategy_mutation_intent") or "REFINE").strip().upper()
        if normalize_mutation_intent(intent) is None:
            raise ValueError(f"Unsupported strategy_mutation_intent: {intent!r}")
        order = tuple(str(item).strip().lower() for item in payload.get("reflection_order", REFLECTION_TYPES))
        if len(order) != len(REFLECTION_TYPES) or set(order) != set(REFLECTION_TYPES):
            raise ValueError(
                "reflection_order must contain strategy, code, and prompt_compliance exactly once."
            )
        return cls(name, experiment_path, output_root, trials, intent, order)

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": INSPECTION_SCHEMA_VERSION,
            "name": self.name,
            "experiment_config": str(self.experiment_config_path),
            "output_root": str(self.output_root),
            "trials_per_reflection": self.trials_per_reflection,
            "strategy_mutation_intent": self.strategy_mutation_intent,
            "reflection_order": list(self.reflection_order),
        }


@dataclass(frozen=True)
class ReflectionInspectionResult:
    run_dir: Path
    parent: Candidate
    trial_summaries: tuple[dict[str, object], ...]

    @property
    def all_trials_match_expected_scope(self) -> bool:
        return all(bool(item["scope_matches_expectation"]) for item in self.trial_summaries)


def run_reflection_inspection(
    inspection: ReflectionInspectionConfig,
    *,
    mock: bool = False,
    output_dir: Path | None = None,
    runtime_factory=RuntimeManager,
) -> ReflectionInspectionResult:
    """Evaluate Worker Rush once, then independently inspect 3xN mutations."""

    experiment = ExperimentConfig.from_file(inspection.experiment_config_path)
    experiment.validate()
    run_dir = (output_dir or _new_run_dir(inspection)).expanduser().resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    started_at = _utc_now()
    manifest: dict[str, object] = {
        "schema_version": INSPECTION_SCHEMA_VERSION,
        "name": inspection.name,
        "status": "running",
        "execution_mode": "mock" if mock else experiment.execution_mode,
        "started_at": started_at,
        "finished_at": None,
        "experiment_config": str(inspection.experiment_config_path),
        "trials_per_reflection": inspection.trials_per_reflection,
        "reflection_order": list(inspection.reflection_order),
        "strategy_mutation_intent": inspection.strategy_mutation_intent,
        "trial_count_expected": len(inspection.reflection_order) * inspection.trials_per_reflection,
        "trial_count_completed": 0,
        "error": None,
    }
    _write_json(run_dir / "manifest.json", manifest)
    _write_yaml(run_dir / "inspection_config.yaml", inspection.to_mapping())
    _write_yaml(run_dir / "resolved_experiment_config.yaml", experiment.to_mapping(mock=mock))

    manager: RuntimeManager | None = None
    try:
        if not mock:
            runtime_config = runtime_config_from_experiment(experiment)
            manager = runtime_factory()
            status = manager.ensure(runtime_config)
            if status.state != "healthy":
                raise RuntimeError(
                    f"Configured llama.cpp runtime is not healthy: {status.detail}"
                )

        runtime = build_search_runtime(
            experiment,
            mock=mock,
            run_dir=run_dir,
            candidates_dir=run_dir / "trials",
        )
        parent = _evaluate_worker_rush_parent(
            experiment,
            run_dir=run_dir,
            mock=mock,
            llm_client=runtime.client,
        )
        subject = _build_fixed_subject(parent)
        _write_subject_inputs(run_dir, parent, subject, experiment)

        summaries: list[dict[str, object]] = []
        for reflection_type in inspection.reflection_order:
            context = build_reflection_context(
                parent,
                generation=subject.generation,
                index=0,
                reflection_type=reflection_type,
                evolution_candidate=subject,
                parent_objectives={parent.id: parent.fitness_objectives},
                reference_candidates={parent.id: parent},
            )
            context_payload = _context_payload(context)
            context_fingerprint = _sha256_json(context_payload)
            context_dir = run_dir / "inputs" / reflection_type
            _write_json(context_dir / "reflection_context.json", context_payload)
            _write_json(
                context_dir / "input_identity.json",
                {
                    "parent_candidate_id": parent.id,
                    "subject_candidate_id": subject.id,
                    "context_sha256": context_fingerprint,
                    "parent_genotype_sha256": _genotype_hashes(subject),
                    "context_index": context.index,
                    "generation_index": context.evolution.generation_index,
                    "strategy_mutation_intent": (
                        inspection.strategy_mutation_intent
                        if reflection_type == "strategy"
                        else None
                    ),
                },
            )

            for trial_number in range(1, inspection.trials_per_reflection + 1):
                trial_dir = (
                    run_dir
                    / "trials"
                    / reflection_type
                    / f"trial_{trial_number:02d}"
                )
                trial_dir.mkdir(parents=True, exist_ok=False)
                print(
                    f"[reflection inspection] type={reflection_type} "
                    f"trial={trial_number}/{inspection.trials_per_reflection} status=started",
                    flush=True,
                )
                mutation = runtime.mutations[reflection_type]
                if reflection_type == "strategy":
                    child = mutation.mutate(
                        subject,
                        context,
                        artifact_dir=trial_dir,
                        mutation_intent=inspection.strategy_mutation_intent,
                    )
                else:
                    child = mutation.mutate(subject, context, artifact_dir=trial_dir)
                summary = _write_trial_review(
                    trial_dir,
                    reflection_type=reflection_type,
                    trial_number=trial_number,
                    subject=subject,
                    child=child,
                    context_fingerprint=context_fingerprint,
                )
                summaries.append(summary)
                print(
                    f"[reflection inspection] type={reflection_type} "
                    f"trial={trial_number}/{inspection.trials_per_reflection} "
                    f"status={summary['mutation_status']} "
                    f"scope_matches={str(summary['scope_matches_expectation']).lower()}",
                    flush=True,
                )
                manifest["trial_count_completed"] = len(summaries)
                _write_json(run_dir / "manifest.json", manifest)

        grouped = _group_summary(summaries, inspection.reflection_order)
        _write_json(
            run_dir / "summary.json",
            {
                "schema_version": INSPECTION_SCHEMA_VERSION,
                "parent_candidate_id": parent.id,
                "subject_candidate_id": subject.id,
                "all_trials_match_expected_scope": all(
                    bool(item["scope_matches_expectation"]) for item in summaries
                ),
                "groups": grouped,
                "trials": summaries,
            },
        )
        (run_dir / "summary.md").write_text(
            _render_markdown_summary(
                inspection,
                parent=parent,
                subject=subject,
                summaries=summaries,
                grouped=grouped,
                mock=mock,
            ),
            encoding="utf-8",
        )
        manifest.update(
            {
                "status": "complete",
                "finished_at": _utc_now(),
                "trial_count_completed": len(summaries),
                "all_trials_match_expected_scope": all(
                    bool(item["scope_matches_expectation"]) for item in summaries
                ),
                "summary": "summary.md",
            }
        )
        _write_json(run_dir / "manifest.json", manifest)
        return ReflectionInspectionResult(run_dir, parent, tuple(summaries))
    except BaseException as exc:
        manifest.update(
            {
                "status": "failed",
                "finished_at": _utc_now(),
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        _write_json(run_dir / "manifest.json", manifest)
        raise
    finally:
        if manager is not None:
            manager.stop_owned()


def _evaluate_worker_rush_parent(
    experiment: ExperimentConfig,
    *,
    run_dir: Path,
    mock: bool,
    llm_client: object,
) -> Candidate:
    """Create exactly one parent from the configured policy and Java seed."""

    if len(experiment.seed_prompts) != 1:
        raise ValueError(
            "Reflection inspection requires exactly one configured seed policy."
        )
    source = experiment.initial_java_seed_path.read_text(encoding="utf-8")
    if "runWorkerRush(" not in source:
        raise ValueError(
            "Reflection inspection requires the checked-in Worker Rush Java seed."
        )
    parent = Candidate(
        id="worker_rush_parent",
        generation=0,
        strategy_prompt=experiment.seed_prompts[0],
        generation_prompt=experiment.generation_prompt,
        inherited_java=source,
        operator="seed",
        metadata={
            "seed_index": 0,
            "inspection_source": "configured_worker_rush_seed",
        },
    )
    baseline_dir = run_dir / "baseline"
    candidates_dir = baseline_dir / "candidates"
    generated_agents_dir = baseline_dir / "generated_agents"
    classes_dir = baseline_dir / "classes"
    for path in (candidates_dir, generated_agents_dir, classes_dir):
        path.mkdir(parents=True, exist_ok=False)
    evaluated = evaluate_population(
        [parent],
        generation=0,
        config=experiment,
        backend=InitialJavaSeedBackend(experiment.initial_java_seed_path),
        generated_agents_dir=generated_agents_dir,
        classes_dir=classes_dir,
        candidates_dir=candidates_dir,
        mock=mock,
        llm_client=llm_client,
    )[0]
    if evaluated.status != "evaluated":
        raise RuntimeError(
            "Worker Rush baseline evaluation failed at "
            f"{evaluated.failure_stage}: {evaluated.failure_reason}"
        )
    # The canonical Java assembler removes only the file-final newline. Compare
    # normalized text so this harmless serialization detail does not obscure
    # whether the executable Worker Rush implementation changed.
    if evaluated.generated_java.rstrip("\r\n") != source.rstrip("\r\n"):
        raise RuntimeError(
            "Worker Rush baseline phenotype differs from the configured checked-in Java seed."
        )
    return evaluated


def _build_fixed_subject(parent: Candidate) -> Candidate:
    """Mirror a generation-one inherited-Java child without changing its input."""

    return Candidate(
        id="worker_rush_reflection_subject",
        generation=1,
        parent_ids=(parent.id,),
        strategy_prompt=parent.strategy_prompt,
        generation_prompt=parent.generation_prompt,
        inherited_java=parent.generated_java,
        operator="copy",
        strategy_parent_id=parent.id,
        generation_prompt_parent_id=parent.id,
        java_parent_id=parent.id,
        source_candidate_ids=(parent.id,),
    )


def _write_subject_inputs(
    run_dir: Path,
    parent: Candidate,
    subject: Candidate,
    experiment: ExperimentConfig,
) -> None:
    root = run_dir / "inputs"
    write_candidate_inputs(root / "subject", subject)
    _write_json(
        root / "fixed_input_identity.json",
        {
            "parent_candidate_id": parent.id,
            "subject_candidate_id": subject.id,
            "policy_source": str(experiment.seed_prompt_files[0]),
            "java_source": str(experiment.initial_java_seed_path),
            "parent_evaluation_artifact": (
                f"../baseline/candidates/{parent.id}/candidate.json"
            ),
            "genotype_sha256": _genotype_hashes(subject),
            "independence_contract": (
                "Every trial starts from this subject; no trial consumes another trial's output."
            ),
        },
    )


def _write_trial_review(
    trial_dir: Path,
    *,
    reflection_type: str,
    trial_number: int,
    subject: Candidate,
    child: Candidate,
    context_fingerprint: str,
) -> dict[str, object]:
    output_dir = trial_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "strategy_prompt.txt").write_text(child.strategy_prompt, encoding="utf-8")
    (output_dir / "code_generation_prompt.txt").write_text(
        child.generation_prompt, encoding="utf-8"
    )
    (output_dir / "inherited_java.java").write_text(child.inherited_java, encoding="utf-8")

    compared = {
        "strategy_prompt": (subject.strategy_prompt, child.strategy_prompt),
        "generation_prompt": (subject.generation_prompt, child.generation_prompt),
        "inherited_java": (subject.inherited_java, child.inherited_java),
        "generated_java": (subject.generated_java, child.generated_java),
    }
    changed = tuple(name for name, (before, after) in compared.items() if before != after)
    expected = EXPECTED_CHANGED_FIELDS[reflection_type]
    forbidden = tuple(name for name in changed if name not in expected)
    missing = tuple(name for name in expected if name not in changed)
    mutation_record = child.metadata.get("mutation") or {}
    applied = bool(mutation_record.get("applied"))
    scope_matches = applied and not forbidden and not missing

    changes_dir = trial_dir / "changes"
    changes_dir.mkdir(parents=True, exist_ok=True)
    for name, (before, after) in compared.items():
        suffix = ".java.diff" if "java" in name else ".diff"
        (changes_dir / f"{name}{suffix}").write_text(
            _unified_diff(before, after, name=name),
            encoding="utf-8",
        )

    index = _request_response_index(trial_dir)
    _write_json(trial_dir / "request_response_index.json", index)
    summary: dict[str, object] = {
        "schema_version": INSPECTION_SCHEMA_VERSION,
        "reflection_type": reflection_type,
        "trial": trial_number,
        "parent_candidate_id": subject.parent_ids[0],
        "subject_candidate_id": subject.id,
        "context_sha256": context_fingerprint,
        "root_request_set_sha256": index["root_request_set_sha256"],
        "pipeline_request_set_sha256": index["pipeline_request_set_sha256"],
        "mutation_status": "applied" if applied else "failed",
        "mutation_error": (
            mutation_record.get("reflection_error")
            or mutation_record.get("rewrite_error")
        ),
        "expected_changed_fields": list(expected),
        "actual_changed_fields": list(changed),
        "missing_expected_changes": list(missing),
        "forbidden_changes": list(forbidden),
        "scope_matches_expectation": scope_matches,
        "input_genotype_sha256": _genotype_hashes(subject),
        "output_genotype_sha256": _genotype_hashes(child),
        "request_count": len(index["requests"]),
        "response_attempt_count": len(index["responses"]),
        "parsed_artifact_count": len(index["parsed_outputs"]),
        "artifacts": {
            "request_response_index": "request_response_index.json",
            "mutation": f"mutation/{reflection_type}_reflection/",
            "output": "output/",
            "changes": "changes/",
        },
    }
    _write_json(trial_dir / "trial_summary.json", summary)
    return summary


def _request_response_index(trial_dir: Path) -> dict[str, object]:
    mutation_dir = trial_dir / "mutation"
    request_paths: list[Path] = []
    response_paths: list[Path] = []
    parsed_paths: list[Path] = []
    if mutation_dir.is_dir():
        for path in sorted(item for item in mutation_dir.rglob("*") if item.is_file()):
            name = path.name
            if "request" in name and path.suffix in {".txt", ".json"}:
                request_paths.append(path)
            if (
                (path.suffix == ".json" and "response_attempt_" in name)
                or (
                    path.suffix == ".txt"
                    and re.search(r"attempt_\d+_response_raw$", path.stem)
                )
            ):
                response_paths.append(path)
            if (
                re.fullmatch(r"commentator_\d+\.json", name)
                or name == "coach_output.json"
                or name == "metadata.json"
            ):
                parsed_paths.append(path)

    requests = [_indexed_file(path, trial_dir, request=True) for path in request_paths]
    responses = [_indexed_file(path, trial_dir, response=True) for path in response_paths]
    parsed = [_indexed_file(path, trial_dir) for path in parsed_paths]
    request_identity = [
        {"path": item["path"], "prompt_sha256": item["payload_sha256"]}
        for item in requests
    ]
    root_request_identity = [
        item for item in request_identity if _is_root_request_path(str(item["path"]))
    ]
    return {
        "schema_version": INSPECTION_SCHEMA_VERSION,
        "requests": requests,
        "root_requests": root_request_identity,
        "responses": responses,
        "parsed_outputs": parsed,
        "root_request_set_sha256": _sha256_json(root_request_identity),
        "pipeline_request_set_sha256": _sha256_json(request_identity),
    }


def _is_root_request_path(path: str) -> bool:
    """Identify requests whose inputs precede every stochastic role output."""

    if path.endswith("/reflector_request.txt"):
        return True
    return "/strategy_reflection/commentary/" in path and path.endswith("/request.json")


def _indexed_file(
    path: Path,
    root: Path,
    *,
    request: bool = False,
    response: bool = False,
) -> dict[str, object]:
    raw = path.read_text(encoding="utf-8")
    payload = raw
    status: object = None
    error: object = None
    if path.suffix == ".json":
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            if request and isinstance(decoded.get("prompt"), str):
                payload = decoded["prompt"]
            if response and isinstance(decoded.get("response"), str):
                payload = decoded["response"]
                status = decoded.get("status")
                error = decoded.get("error")
    result: dict[str, object] = {
        "path": str(path.relative_to(root)),
        "file_sha256": _sha256_text(raw),
        "payload_sha256": _sha256_text(payload),
        "payload_chars": len(payload),
    }
    if response:
        result.update({"status": status, "error": error})
    return result


def _group_summary(
    summaries: Iterable[dict[str, object]],
    order: Iterable[str],
) -> list[dict[str, object]]:
    rows = list(summaries)
    groups: list[dict[str, object]] = []
    for reflection_type in order:
        trials = [item for item in rows if item["reflection_type"] == reflection_type]
        root_request_hashes = {str(item["root_request_set_sha256"]) for item in trials}
        pipeline_request_hashes = {
            str(item["pipeline_request_set_sha256"]) for item in trials
        }
        context_hashes = {str(item["context_sha256"]) for item in trials}
        groups.append(
            {
                "reflection_type": reflection_type,
                "expected_changed_fields": list(EXPECTED_CHANGED_FIELDS[reflection_type]),
                "trial_count": len(trials),
                "applied_count": sum(item["mutation_status"] == "applied" for item in trials),
                "scope_match_count": sum(bool(item["scope_matches_expectation"]) for item in trials),
                "same_context_across_trials": len(context_hashes) == 1,
                "same_root_requests_across_trials": len(root_request_hashes) == 1,
                "same_pipeline_requests_across_trials": len(pipeline_request_hashes) == 1,
                "root_request_set_sha256": (
                    next(iter(root_request_hashes))
                    if len(root_request_hashes) == 1
                    else None
                ),
                "response_attempt_count": sum(int(item["response_attempt_count"]) for item in trials),
            }
        )
    return groups


def _render_markdown_summary(
    inspection: ReflectionInspectionConfig,
    *,
    parent: Candidate,
    subject: Candidate,
    summaries: list[dict[str, object]],
    grouped: list[dict[str, object]],
    mock: bool,
) -> str:
    lines = [
        f"# {inspection.name}",
        "",
        f"- 執行模式：`{'mock' if mock else 'openai'}`",
        f"- 固定父代：`{parent.id}`（Worker Rush policy + checked-in Worker Rush Java）",
        f"- 固定 mutation subject：`{subject.id}`",
        f"- 每種 reflection 次數：`{inspection.trials_per_reflection}`",
        f"- Strategy mutation intent：`{inspection.strategy_mutation_intent}`",
        "- 獨立性：每次 trial 都重新從同一 subject 開始，不使用前一次輸出。",
        "",
        "## 一致性總覽",
        "",
        "| Reflection | 預期改動 | 成功套用 | Scope 符合 | Context 相同 | Root request 相同 | 全 pipeline request 相同 | Response attempts |",
        "|---|---|---:|---:|---|---|---|---:|",
    ]
    for group in grouped:
        expected = ", ".join(str(item) for item in group["expected_changed_fields"])
        lines.append(
            f"| {group['reflection_type']} | {expected} | "
            f"{group['applied_count']}/{group['trial_count']} | "
            f"{group['scope_match_count']}/{group['trial_count']} | "
            f"{'是' if group['same_context_across_trials'] else '否'} | "
            f"{'是' if group['same_root_requests_across_trials'] else '否'} | "
            f"{'是' if group['same_pipeline_requests_across_trials'] else '否'} | "
            f"{group['response_attempt_count']} |"
        )
    lines.extend(
        [
            "",
            "## Trial 明細",
            "",
            "| Reflection | Trial | 執行 | 實際改動 | 符合預期 | Response attempts | Request / response | Diff |",
            "|---|---:|---|---|---|---:|---|---|",
        ]
    )
    for item in summaries:
        kind = str(item["reflection_type"])
        trial = int(item["trial"])
        root = f"trials/{kind}/trial_{trial:02d}"
        changed = ", ".join(str(value) for value in item["actual_changed_fields"]) or "無"
        lines.append(
            f"| {kind} | {trial} | {item['mutation_status']} | {changed} | "
            f"{'是' if item['scope_matches_expectation'] else '否'} | "
            f"{item['response_attempt_count']} | "
            f"[索引]({root}/request_response_index.json) | "
            f"[changes]({root}/changes/) |"
        )
    lines.extend(
        [
            "",
            "## 人工確認順序",
            "",
            "1. 先確認 `Root request 相同=是`：Strategy 比對 10 個 commentator request；Code/Prompt Compliance 比對 reflector request。後續 request 會包含前一角色的隨機輸出，本來就可能不同。",
            "2. 再看 `mutation/<type>_reflection/` 內的解析結果與 validation/retry artifact。",
            "3. 最後看 `changes/`：Strategy 只能改 policy prompt；Code 只能改 code-generation prompt；Prompt Compliance 必須同時改兩者；Java 必須保持不變。",
            "4. `scope_matches_expectation=false` 代表 reflection 失敗、缺少預期改動，或動到不該動的欄位，需人工判讀原因。",
            "",
            "Baseline 完整評估證據位於 `baseline/`，固定輸入與 hash 位於 `inputs/`。",
            "",
        ]
    )
    return "\n".join(lines)


def _context_payload(context: ReflectionContext) -> dict[str, object]:
    return {
        "structured_context": context.to_dict(),
        "per_match_results": [dict(item) for item in context.per_match_results],
        "compatibility": {
            "generation": context.generation,
            "index": context.index,
            "candidate_id": context.candidate_id,
            "evaluation_status": context.evaluation_status,
            "game_evidence": context.game_evidence,
            "code_quality_evidence": context.code_quality_evidence,
        },
    }


def _genotype_hashes(candidate: Candidate) -> dict[str, str]:
    return {
        "strategy_prompt": _sha256_text(candidate.strategy_prompt),
        "generation_prompt": _sha256_text(candidate.generation_prompt),
        "inherited_java": _sha256_text(candidate.inherited_java),
        "generated_java": _sha256_text(candidate.generated_java),
    }


def _unified_diff(before: str, after: str, *, name: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"parent/{name}",
            tofile=f"child/{name}",
        )
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return _sha256_text(serialized)


def _repository_path(
    raw: object,
    field: str,
    *,
    require_exists: bool = True,
) -> Path:
    if not isinstance(raw, (str, Path)) or not str(raw).strip():
        raise ValueError(f"{field} must be a non-empty path.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    if require_exists and not path.is_file():
        raise ValueError(f"{field} does not exist or is not a file: {path}")
    return path


def _new_run_dir(config: ReflectionInspectionConfig) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", config.name).strip("_")
    return config.output_root / f"{stamp}_{safe_name}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_yaml(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run each EAGLE reflection operator repeatedly from one Worker Rush parent."
    )
    parser.add_argument("--config", required=True, help="reflection-inspection-v1 YAML")
    parser.add_argument("--mock", action="store_true", help="use deterministic mock LLM and matches")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="exact new output directory (primarily useful for tests)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    inspection = ReflectionInspectionConfig.from_file(args.config)
    result = run_reflection_inspection(
        inspection,
        mock=args.mock,
        output_dir=args.output_dir,
    )
    print(f"Reflection inspection complete: {result.run_dir}")
    print(f"Manual review summary: {result.run_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
