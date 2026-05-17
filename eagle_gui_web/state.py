"""Shared state for the NiceGUI EAGLE workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eagle.utils.component_pool import ComponentPool

from . import services


@dataclass
class ConfigState:
    """Config form state mirrored to the generated JSON schema."""

    base_config_path: str = field(default_factory=lambda: str(services.DEFAULT_CONFIG))
    config_name: str = field(default_factory=lambda: services.timestamped_stem("gui_web_evolution"))
    generated_config_path: Path | None = None
    application: str = "microrts"
    algorithm: str = "nsga2"
    evaluator: str = "gameplay"
    surrogate: str = "round"
    population_size: str = "10"
    num_generations: str = "50"
    tick_limit: str = "5000"
    llm_call_limit: str = "50"
    gameplay_map_dir: str = "8x8"
    gameplay_rate: str = "0.25"
    gameplay_refresh_interval: str = "5"
    surrogate_top_ratio: str = "0.3"
    archive_parent_ratio: str = "0.25"
    min_token_length: str = "1"
    one_eval_rounds: str = "8"
    final_test_max_front: str = "1"
    opponents_text: str = "ai.abstraction.LightRush, ai.abstraction.HeavyRush"
    component_pool_path: str = ""
    include_strategy_identity_in_prompt: bool = True
    non_evolving_prompt_components: set[str] = field(
        default_factory=lambda: set(ComponentPool.DEFAULT_NON_EVOLVING_COMPONENT_KEYS)
    )
    training_example_fixed_count: bool = False
    training_example_sample_min: str = "0"
    training_example_sample_max: str = "4"
    training_example_fixed_sample_count: str = "4"


@dataclass
class ComponentState:
    """Loaded component JSON and prompt preview state."""

    loaded_path: Path | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    selected_category: str = ""
    selected_candidate: int = 0
    editor_text: str = ""
    prompt_selection: dict[str, int] = field(default_factory=dict)
    rendered_prompt: str = ""
    prompt_token_summary: str = "Prompt tokens: 0"
    status: str = "No component loaded"


@dataclass
class ObjectiveState:
    """Objective mode and per-objective selections."""

    mode: str = "multi"
    single_objective: str = "resource_advantage"
    selected: set[str] = field(default_factory=set)
    weights: dict[str, str] = field(default_factory=dict)
    detail: str = "No objective selected."


@dataclass
class OperatorState:
    """Evolution operator selections and weights."""

    parent_selection_operator: str = "nsga2_tournament"
    crossover_operator: str = "uniform"
    mutation_operator: str = "mix"
    env_selection_operator: str = "nsga2_environmental"
    crossover_repair_enabled: bool = True
    enable_reflection_operator: bool = True
    reproduction_weights: dict[str, str] = field(
        default_factory=lambda: {"crossover": "0.7", "mutation": "0.2", "reflection": "0.1"}
    )
    mutation_weights: dict[str, str] = field(
        default_factory=lambda: {
            "pool_replacement": "0.4",
            "identity_preserving_rewrite": "0.35",
            "identity_shift_rewrite": "0.25",
            "bitmask_flip": "0.0",
        }
    )


@dataclass
class RunState:
    """Experiment process and run artifact state."""

    quick_run: bool = False
    skip_final_test: bool = False
    precompile_python: bool = False
    current_run_dir: Path | None = None
    status_text: str = "not running"
    log_text: str = ""


@dataclass
class FinalTestState:
    """Final-test launch state for an existing run folder."""

    selected_run_dir: Path | None = None
    max_front: str = ""
    quick_run: bool = False
    precompile_python: bool = False
    status_text: str = "not running"
    log_text: str = ""


@dataclass
class AnalysisState:
    """Live analysis payloads refreshed independently from process logs."""

    summary: str = "No run selected"
    body: str = ""
    timing_summary: str = "No run selected"
    timing_body: str = ""
    timing_rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PromptState:
    """Prompt inspection records for the selected run."""

    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    selected_record_id: str = ""
    selected_prompt: str = ""
    selected_llm_output: str = ""
    metadata: str = "No prompt selected"
    last_run_key: str | None = None


@dataclass
class MicroRTSState:
    """Visible Java MicroRTS launch and trace controls."""

    status: str = "Java GUI not running"
    opponent: str = "ai.abstraction.HeavyRush"
    map_dir: str = "8x8"
    map_file: str = "basesWorkers8x8.xml"
    update_interval: str = "50"
    llm_interval: str = "1"
    save_trace: bool = False
    prompt_text: str = ""
    log_text: str = ""
    selected_trace: str = ""


@dataclass
class AppState:
    """Single mutable NiceGUI state object shared by all views."""

    config: ConfigState = field(default_factory=ConfigState)
    components: ComponentState = field(default_factory=ComponentState)
    objectives: ObjectiveState = field(default_factory=ObjectiveState)
    operators: OperatorState = field(default_factory=OperatorState)
    run: RunState = field(default_factory=RunState)
    final_test: FinalTestState = field(default_factory=FinalTestState)
    analysis: AnalysisState = field(default_factory=AnalysisState)
    prompts: PromptState = field(default_factory=PromptState)
    microrts: MicroRTSState = field(default_factory=MicroRTSState)
    is_stopping: bool = False
    is_shutting_down: bool = False
    connected_clients: int = 0
    active_processes: list[Any] = field(default_factory=list)
    active_timers: list[Any] = field(default_factory=list)
    active_tasks: list[Any] = field(default_factory=list)
