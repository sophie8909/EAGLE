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
    config_name: str = field(default_factory=lambda: services.timestamped_stem("eagle_ui_evolution"))
    generated_config_path: Path | None = None
    application: str = "microrts"
    algorithm: str = "nsga2"
    evaluator: str = "gameplay"
    surrogate: str = "round"
    population_size: str = "10"
    num_generations: str = "50"
    tick_limit: str = "5000"
    llm_call_limit: str = "50"
    llm_model: str = "local"
    llm_base_url: str = "http://127.0.0.1:8080/v1"
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
    use_few_shot_examples: bool = True
    min_examples: str = "0"
    max_examples: str = "3"
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
    example_reproduction_weights: dict[str, str] = field(
        default_factory=lambda: {"crossover": "0.5", "mutation": "0.5"}
    )
    example_mutation_source_weights: dict[str, str] = field(
        default_factory=lambda: {"fresh": "0.5", "pool": "0.5"}
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
    experiment_current_run_dir: Path | None = None
    status_text: str = "not running"
    log_text: str = ""


@dataclass
class FinalTestState:
    """Final-test launch state for an existing run folder."""

    selected_run_dir: Path | None = None
    map: str = "all"
    opponent: str = "all"
    analysis_metric: str = "win_rate"
    analysis_aggregation: str = "mean"
    analysis_individual: str = "all"
    weight_resources: str = "1.0"
    weight_base: str = "1.0"
    weight_barracks: str = "1.0"
    weight_worker: str = "1.0"
    weight_light: str = "1.0"
    weight_heavy: str = "1.0"
    weight_ranged: str = "1.0"
    max_front: str = ""
    quick_run: bool = False
    precompile_python: bool = False
    status_text: str = "not running"
    log_text: str = ""
    analysis_text: str = "No final test results found."
    analysis_output_path: str = ""


@dataclass
class AnalysisState:
    """Live analysis payloads refreshed independently from process logs."""

    analysis_selected_run_dir: Path | None = None
    analysis_run_selected_manually: bool = False
    summary: str = "No run selected"
    body: str = ""
    timing_summary: str = "No run selected"
    timing_body: str = ""
    timing_rows: list[dict[str, Any]] = field(default_factory=list)
    mo_visible: bool = False
    mo_summary: str = "No multi-objective data found."
    mo_animation_path: str = ""
    mo_generation_choices: list[str] = field(default_factory=list)
    mo_selected_generation: str = ""
    mo_static_plot_paths: dict[str, str] = field(default_factory=dict)


@dataclass
class PromptState:
    """Prompt inspection records for the selected run."""

    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    trace_records: list[dict[str, Any]] = field(default_factory=list)
    selected_generation: str = ""
    selected_individual_id: str = ""
    selected_call_id: str = ""
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
class RuntimeState:
    """Runtime handles owned by the NiceGUI process."""

    is_running: bool = False
    is_stopping: bool = False
    is_shutting_down: bool = False
    connected_client_count: int = 0
    current_page: str = "experiment"
    config_summary_refresh: Any | None = None
    analysis_runs_refresh: Any | None = None
    last_heartbeat_monotonic: float | None = None
    last_heartbeat_timestamp: str = ""
    active_tasks: list[Any] = field(default_factory=list)
    active_processes: list[Any] = field(default_factory=list)
    active_timers: list[Any] = field(default_factory=list)


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
    runtime: RuntimeState = field(default_factory=RuntimeState)

    @property
    def is_stopping(self) -> bool:
        return self.runtime.is_stopping

    @is_stopping.setter
    def is_stopping(self, value: bool) -> None:
        self.runtime.is_stopping = bool(value)

    @property
    def is_shutting_down(self) -> bool:
        return self.runtime.is_shutting_down

    @is_shutting_down.setter
    def is_shutting_down(self, value: bool) -> None:
        self.runtime.is_shutting_down = bool(value)

    @property
    def active_processes(self) -> list[Any]:
        return self.runtime.active_processes

    @property
    def active_timers(self) -> list[Any]:
        return self.runtime.active_timers

    @property
    def active_tasks(self) -> list[Any]:
        return self.runtime.active_tasks
