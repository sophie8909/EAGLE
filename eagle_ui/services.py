"""Service helpers for the NiceGUI EAGLE workflow."""

from __future__ import annotations

import json
import logging
import os
import random
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from eagle.config import normalize_algorithm_name
from eagle.envs.microrts.runner import save_prompt as save_microrts_prompt
from eagle.envs.microrts.runner import set_config_property
from eagle.analysis.evolution_result_analysis import parse_final_test_analysis
from eagle.eval.microrts.final_test_batch import run_final_test_batch
from eagle.objectives.registry import get_objectives, list_objective_names, normalize_objective_key
from eagle.operators.registry import list_operator_names
from eagle.prompt.example_memory import ExampleMemory
from eagle.utils.component_pool import ComponentPool
from eagle.utils.token_count import count_prompt_tokens
from eagle_ui.service_helpers import analysis_service, config_service, process_service


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_LOG_PATH = ROOT / "logs" / "gui_runtime.log"
CONFIG_DIR = ROOT / "configs" / "evolution"
EXPERIMENT_DIR = ROOT / "configs" / "experiments"
LOG_DIR = ROOT / "logs" / "eagle"
MICRORTS_LOG_DIR = ROOT / "logs" / "microrts"
DEFAULT_CONFIG = CONFIG_DIR / "default.json"
GUI_PROCESS_STATE_PATH = LOG_DIR / "eagle_ui_process_state.json"
LOG_TAIL_LIMIT = 18_000
ANALYSIS_SUBPROCESS_TIMEOUT_SEC = 600

APPLICATION_CHOICES = ("microrts",)
ALGORITHM_CHOICES = ("ga", "nsga2", "ga_surrogate", "nsga2_surrogate")
EVALUATOR_CHOICES = ("gameplay",)
SURROGATE_CHOICES = ("round", "policy_agent", "java_agent")
AGGRESSIVENESS_MODE_CHOICES = ("component_only", "llm_only", "hybrid")
MUTATION_SELECTION_MODE_CHOICES = {
    "fixed": "Fixed",
    "aos": "AOS (Adaptive Operator Selection)",
}
GA_ALGORITHMS = {"ga", "ga_surrogate"}
MO_ALGORITHMS = {"nsga2", "nsga2_surrogate"}
SURROGATE_ALGORITHMS = {"ga_surrogate", "nsga2_surrogate"}
PARENT_SELECTION_BY_ALGORITHM = {
    "ga": "ga_fitness_tournament",
    "ga_surrogate": "ga_fitness_tournament",
    "nsga2": "nsga2_tournament",
    "nsga2_surrogate": "nsga2_tournament",
}
ENV_SELECTION_BY_ALGORITHM = {
    "ga": "ga_fitness_elitism",
    "ga_surrogate": "ga_fitness_elitism",
    "nsga2": "nsga2_environmental",
    "nsga2_surrogate": "nsga2_environmental",
}
MICRORTS_OPPONENT_CHOICES = (
    "ai.abstraction.HeavyRush",
    "ai.abstraction.LightRush",
    "ai.RandomBiasedAI",
    "ai.RandomAI",
    "ai.PassiveAI",
)

_microrts_process: subprocess.Popen | None = None
_microrts_log_path: Path | None = None
LOGGER = logging.getLogger(__name__)


def is_surrogate_algorithm(algorithm: str) -> bool:
    """Return whether an algorithm name uses a surrogate flow."""
    return "surrogate" in str(algorithm or "").lower()


def configure_runtime_logging() -> None:
    """Configure terminal and file logging for NiceGUI runtime diagnostics."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    if not any(getattr(handler, "_eagle_ui_runtime_stream", False) for handler in root_logger.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler._eagle_ui_runtime_stream = True
        root_logger.addHandler(stream_handler)

    if any(getattr(handler, "_eagle_ui_runtime_file", False) for handler in root_logger.handlers):
        return

    try:
        RUNTIME_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(RUNTIME_LOG_PATH, encoding="utf-8")
    except OSError as exc:
        LOGGER.warning("GUI runtime file logging unavailable path=%s error=%s", RUNTIME_LOG_PATH, exc)
        return
    file_handler.setFormatter(formatter)
    file_handler._eagle_ui_runtime_file = True
    root_logger.addHandler(file_handler)


class LoggedOperation:
    """Log duration for one GUI-triggered operation without handling failures."""

    def __init__(self, name: str, **details: Any) -> None:
        self.name = name
        self.details = details
        self.started_at = 0.0

    def __enter__(self) -> "LoggedOperation":
        self.started_at = time.monotonic()
        LOGGER.info("operation start name=%s %s", self.name, format_log_details(self.details))
        return self

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> bool:
        duration = time.monotonic() - self.started_at
        if exc_type is None:
            LOGGER.info(
                "operation end name=%s duration_sec=%.3f %s",
                self.name,
                duration,
                format_log_details(self.details),
            )
        else:
            LOGGER.info(
                "operation failed name=%s duration_sec=%.3f error_type=%s %s",
                self.name,
                duration,
                getattr(exc_type, "__name__", str(exc_type)),
                format_log_details(self.details),
            )
        return False


def format_log_details(details: dict[str, Any]) -> str:
    """Return stable key-value detail text for runtime logs."""
    return " ".join(f"{key}={value}" for key, value in details.items() if value is not None)


def timestamped_stem(prefix: str) -> str:
    """Return a filename stem with a timestamp suffix."""
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"


def find_available_port(start: int = 8080, attempts: int = 50) -> int:
    """Return the first available local TCP port at or above the start port."""
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("0.0.0.0", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No available port found from {start} to {start + attempts - 1}.")


def config_choices() -> list[str]:
    """Return available evolution config paths."""
    paths: list[Path] = []
    for root in (CONFIG_DIR, EXPERIMENT_DIR):
        if root.exists():
            paths.extend(path for path in root.rglob("*.json") if path.is_file())
    paths = sorted(set(paths))
    if DEFAULT_CONFIG in paths:
        paths.remove(DEFAULT_CONFIG)
        paths.insert(0, DEFAULT_CONFIG)
    return [str(path) for path in paths] or [str(DEFAULT_CONFIG)]


def component_json_choices() -> list[str]:
    """Return repository-relative component or prompt JSON candidates."""
    roots = [ROOT / "eagle" / "prompts", EXPERIMENT_DIR, ROOT / "configs"]
    default_path = ROOT / "eagle" / "prompts" / "components.json"
    paths: set[Path] = set()
    if default_path.exists():
        paths.add(default_path.resolve())
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.json"):
            text = str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path).lower()
            if any(marker in text for marker in ("component", "components", "prompt")):
                paths.add(path.resolve())
    return sorted(relative_or_absolute(path) for path in paths)


def examples_pool_path(state: Any) -> Path:
    """Return the runtime examples pool path for the active component file."""
    run_dir = getattr(getattr(state, "run", None), "experiment_current_run_dir", None)
    if run_dir is not None:
        return Path(run_dir) / "examples_pool.jsonl"
    configured = str(getattr(getattr(state, "config", None), "examples_pool_path", "") or "").strip()
    if configured:
        return resolve_repo_path(configured)
    return ROOT / "eagle" / "prompts" / "examples_pool.jsonl"


def load_examples_pool(state: Any) -> tuple[Path, list[dict[str, Any]]]:
    """Load display rows from the runtime examples JSONL pool."""
    path = examples_pool_path(state)
    if not path.exists():
        return path, []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("validator_passed") is not True:
                continue
            for move_index, move in enumerate(_example_record_moves(record), start=1):
                rows.append(
                    {
                        "id": f"{line_number}:{move_index}",
                        "source": line_number,
                        "raw_move": str(move.get("raw_move", "")),
                        "unit_position": _format_unit_position(move.get("unit_position")),
                        "unit_type": str(move.get("unit_type", "")),
                        "action_type": str(move.get("action_type", "")),
                    }
                )
    return path, rows


def examples_validation_log_path(state: Any) -> Path:
    """Return the validation log path paired with the active examples pool."""
    return examples_pool_path(state).with_name("examples_validation.jsonl")


def load_examples_validation_logs(state: Any) -> tuple[Path, list[dict[str, Any]]]:
    """Load invalid/skipped example-validation records when the log exists."""
    path = examples_validation_log_path(state)
    if not path.exists():
        return path, []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for index, line in enumerate(stream, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                record.setdefault("id", str(index))
                rows.append(record)
    return path, rows


def load_example_records(state: Any) -> tuple[Path, list[dict[str, Any]]]:
    """Load editable example records from the runtime examples JSONL pool."""
    path = examples_pool_path(state)
    if not path.exists():
        return path, []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("validator_passed") is not True:
                continue
            content = record.get("content", [])
            loaded = {
                "id": str(index),
                "name": str(record.get("name", f"example_{index}")),
                "content": [str(item) for item in content] if isinstance(content, list) else [str(content)],
            }
            for key in ("moves", "source", "generation", "round_id", "turn", "validator_passed", "legality_level"):
                if key in record:
                    loaded[key] = record.get(key)
            records.append(loaded)
    return path, records


def save_example_records(state: Any, records: list[dict[str, Any]]) -> Path:
    """Write editable example records back to the runtime examples JSONL pool."""
    path = examples_pool_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    valid_records = [record for record in records if isinstance(record, dict)]
    if len(valid_records) > ExampleMemory.DEFAULT_MAX_EXAMPLES:
        valid_records = random.sample(valid_records, ExampleMemory.DEFAULT_MAX_EXAMPLES)
    with path.open("w", encoding="utf-8") as stream:
        for index, record in enumerate(valid_records):
            payload = {
                "name": str(record.get("name") or f"example_{index}"),
                "content": [
                    str(line)
                    for line in list(record.get("content") or [])
                ],
            }
            for key in ("moves", "source", "generation", "round_id", "turn", "validator_passed", "legality_level"):
                if key in record:
                    payload[key] = record.get(key)
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return path


def _example_record_moves(record: Any) -> list[dict[str, Any]]:
    """Extract schema move objects from one examples-pool record."""
    if not isinstance(record, dict):
        return []
    moves = record.get("moves")
    if not isinstance(moves, list):
        moves = _moves_from_example_content(record.get("content"))
    return [move for move in moves if _is_displayable_move(move)]


def _moves_from_example_content(content: Any) -> list[dict[str, Any]]:
    """Parse legacy example content lines and return moves when possible."""
    if not isinstance(content, list):
        return []
    lines = [str(line) for line in content]
    try:
        output_index = next(index for index, line in enumerate(lines) if line.strip().upper() == "OUTPUT:")
    except StopIteration:
        output_index = -1
    text = "\n".join(lines[output_index + 1 :]).strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    moves = payload.get("moves") if isinstance(payload, dict) else None
    return moves if isinstance(moves, list) else []


def _is_displayable_move(move: Any) -> bool:
    """Return whether a move has the required example display fields."""
    return (
        isinstance(move, dict)
        and isinstance(move.get("raw_move"), str)
        and isinstance(move.get("unit_position"), list)
        and isinstance(move.get("unit_type"), str)
        and isinstance(move.get("action_type"), str)
    )


def _format_unit_position(value: Any) -> str:
    """Format a unit position for compact table display."""
    if isinstance(value, list) and len(value) == 2:
        return f"[{value[0]}, {value[1]}]"
    return ""


def run_choices() -> list[str]:
    """Return EAGLE run directories newest first."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return [str(path) for path in sorted(LOG_DIR.iterdir(), reverse=True) if path.is_dir()]


def latest_experiment_run_dir() -> Path | None:
    """Return the newest timestamped experiment run directory with a config file."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    candidates = [
        path
        for path in LOG_DIR.iterdir()
        if path.is_dir() and re.fullmatch(r"\d{8}_\d{6}", path.name) and (path / "config.json").exists()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name))


def load_config_payload(config_path: Path) -> dict[str, Any]:
    """Load a config merged with the default schema base."""
    return config_service.load_complete_config_payload(config_path, DEFAULT_CONFIG)


def apply_config_payload(state: Any, payload: dict[str, Any], config_path: Path) -> None:
    """Copy a loaded config payload into the shared state."""
    cfg = state.config
    cfg.base_config_path = str(config_path)
    cfg.algorithm = normalize_algorithm_name(
        payload.get("algorithm", cfg.algorithm),
        evaluator=payload.get("evaluator"),
        surrogate=payload.get("surrogate"),
        warn=True,
    )
    if cfg.algorithm not in ALGORITHM_CHOICES:
        cfg.algorithm = "nsga2"
    cfg.application = str(payload.get("application", cfg.application))
    cfg.evaluator = "gameplay"
    cfg.surrogate = str(payload.get("surrogate", cfg.surrogate)).strip().lower().replace("-", "_").replace(" ", "_")
    if cfg.surrogate not in SURROGATE_CHOICES:
        cfg.surrogate = SURROGATE_CHOICES[0]
    for field_name in (
        "population_size",
        "num_generations",
        "tick_limit",
        "llm_call_limit",
        "llm_model",
        "llm_base_url",
        "gameplay_map_dir",
        "gameplay_rate",
        "gameplay_refresh_interval",
        "surrogate_top_ratio",
        "archive_parent_ratio",
        "min_token_length",
        "aggressiveness_mode",
        "aggressiveness_llm_weight",
        "aggressiveness_component_weight",
        "aggressiveness_judge_model",
        "aggressiveness_judge_temperature",
        "one_eval_rounds",
        "final_test_max_front",
    ):
        setattr(cfg, field_name, str(payload.get(field_name, getattr(cfg, field_name))))
    cfg.aggressiveness_objective_enabled = bool(payload.get("aggressiveness_objective_enabled", False))
    cfg.opponents_text = ", ".join(parse_target_list(payload.get("gameplay_opponents", []))) or cfg.opponents_text
    cfg.component_pool_path = str(payload.get("component_pool_path", cfg.component_pool_path))
    cfg.include_strategy_identity_in_prompt = bool(payload.get("include_strategy_identity_in_prompt", True))
    cfg.use_few_shot_examples = bool(payload.get("use_few_shot_examples", True))
    cfg.min_examples = str(parse_nonnegative_int(payload.get("min_examples", 0), "min_examples"))
    cfg.max_examples = str(parse_nonnegative_int(payload.get("max_examples", 3), "max_examples"))
    if int(cfg.max_examples) < int(cfg.min_examples):
        raise ValueError("max_examples must be >= min_examples.")
    cfg.non_evolving_prompt_components = set(
        str(key)
        for key in payload.get(
            "non_evolving_prompt_components",
            payload.get("non_evolving_component_keys", list(ComponentPool.DEFAULT_NON_EVOLVING_COMPONENT_KEYS)),
        )
    )
    apply_training_example_sample_config(state, payload)
    apply_objective_config(state, payload.get("objective_config", {}))
    apply_operator_config(state, payload)
    cfg.generated_config_path = config_path
    cfg.config_name = config_path.stem


def apply_training_example_sample_config(state: Any, payload: dict[str, Any]) -> None:
    """Load training-example sample controls from config values."""
    value = payload.get("training_example_sample_count", "random_0_4")
    fixed = payload.get("training_example_fixed_count")
    cfg = state.config
    if fixed is not None:
        cfg.training_example_fixed_count = bool(fixed)
    text = str(value or "").strip().lower().replace("_", " ")
    if isinstance(value, int) or text.isdigit():
        cfg.training_example_fixed_count = True if fixed is None else bool(fixed)
        cfg.training_example_fixed_sample_count = str(parse_nonnegative_int(text, "training_example_sample_count"))
        return
    lower, upper = parse_range(text, default=(0, 4))
    if fixed is None:
        cfg.training_example_fixed_count = False
    cfg.training_example_sample_min = str(lower)
    cfg.training_example_sample_max = str(upper)


def apply_objective_config(state: Any, objective_config: Any) -> None:
    """Load objective config into objective state."""
    config = dict(objective_config or {})
    objectives = state.objectives
    mode = str(config.get("mode", objectives.mode)).strip().lower()
    if mode in {"single", "multi"}:
        objectives.mode = mode
    elif mode == "weighted_mix":
        objectives.mode = "multi"
    objective = normalize_objective_key(str(config.get("objective", objectives.single_objective)))
    if objective:
        objectives.single_objective = objective
    if objectives.mode == "single" and objective:
        objectives.selected = {objective}
    weights = dict(config.get("weights") or {})
    if weights:
        objectives.weights = {normalize_objective_key(str(key)): str(value) for key, value in weights.items()}
        objectives.selected = set(objectives.weights)
    configured = [normalize_objective_key(str(key)) for key in config.get("objectives", [])]
    if configured:
        objectives.selected = set(configured)


def apply_operator_config(state: Any, payload: dict[str, Any]) -> None:
    """Load operator selections and weights from config."""
    operators = state.operators
    operators.parent_selection_operator = str(
        payload.get("parent_selection_operator", operators.parent_selection_operator)
    )
    operators.crossover_operator = str(payload.get("crossover_operator", operators.crossover_operator))
    operators.mutation_operator = str(payload.get("mutation_operator", operators.mutation_operator))
    operators.mutation_selection_mode = normalize_mutation_selection_mode(
        payload.get("mutation_selection_mode", operators.mutation_selection_mode)
    )
    operators.env_selection_operator = str(
        payload.get("env_selection_operator", payload.get("environment_selection_method", operators.env_selection_operator))
    )
    operators.crossover_repair_enabled = bool(payload.get("crossover_repair_enabled", True))
    operators.enable_reflection_operator = bool(payload.get("enable_reflection_operator", True))
    for key, value in dict(payload.get("reproduction_operator_probs") or {}).items():
        operators.reproduction_weights[str(key)] = str(value)
    for key, value in dict(payload.get("example_reproduction_operator_probs") or {}).items():
        operators.example_reproduction_weights[str(key)] = str(value)
    for key, value in dict(payload.get("example_mutation_source_probs") or {}).items():
        operators.example_mutation_source_weights[str(key)] = str(value)
    for key, value in dict(payload.get("strategy_mutation") or {}).items():
        operators.mutation_weights[str(key)] = str(value)
    sync_algorithm_operator_defaults(state)


def load_component_json(path: Path) -> dict[str, Any]:
    """Load one component JSON file as a mapping."""
    return config_service.read_json_mapping_strict(path)


def load_components(path: Path) -> dict[str, Any]:
    """Load a component JSON payload without changing its schema."""
    return config_service.read_json_mapping_strict(path)


def save_components(path: Path, data: dict[str, Any]) -> None:
    """Atomically save a component JSON payload without normalizing it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def list_component_keys(data: dict[str, Any]) -> list[str]:
    """Return editable top-level component keys in file order."""
    if not isinstance(data, dict):
        return []
    return [str(key) for key in data if str(key) != "metadata"]


def apply_component_payload(state: Any, payload: dict[str, Any], path: Path) -> None:
    """Copy a component payload into state and initialize selection fields."""
    state.components.payload = payload
    state.components.loaded_path = path
    pool = ComponentPool(payload)
    keys = list_component_keys(payload)
    state.components.prompt_selection = {key: 0 for key in pool.component_keys}
    state.components.selected_category = keys[0] if keys else ""
    state.components.selected_candidate = 0
    state.components.editor_text = component_candidate_text(state, state.components.selected_category, 0)
    state.components.status = f"Loaded {path}"
    state.config.component_pool_path = relative_or_absolute(path)


def component_keys(state: Any) -> list[str]:
    """Return editable component keys in display order."""
    if not state.components.payload:
        return []
    return list_component_keys(state.components.payload)


def component_candidate_count(state: Any, key: str) -> int:
    """Return candidate count for one component key."""
    value = state.components.payload.get(key)
    if key == ComponentPool.TRAINING_EXAMPLES_KEY and isinstance(value, list):
        return len(value)
    if not isinstance(value, list):
        return 0
    if value and all(isinstance(item, str) for item in value):
        return 1
    return len(value)


def component_candidate_text(state: Any, key: str, index: int) -> str:
    """Return the editable text for one component candidate."""
    value = state.components.payload.get(key)
    if key == ComponentPool.TRAINING_EXAMPLES_KEY and isinstance(value, list):
        if 0 <= index < len(value):
            item = value[index]
            content = item.get("content", []) if isinstance(item, dict) else item
            return "\n".join(str(line) for line in (content if isinstance(content, list) else [content]))
        return ""
    if not isinstance(value, list):
        return ""
    if value and all(isinstance(item, str) for item in value):
        return "\n".join(str(line) for line in value) if index == 0 else ""
    if 0 <= index < len(value):
        item = value[index]
        return "\n".join(str(line) for line in (item if isinstance(item, list) else [item]))
    return ""


def update_component_candidate(state: Any) -> None:
    """Persist the visible component editor text into the in-memory payload."""
    key = state.components.selected_category
    index = int(state.components.selected_candidate)
    lines = [line.rstrip() for line in state.components.editor_text.splitlines() if line.strip()]
    if not key or key not in component_keys(state):
        raise ValueError("Load a component JSON and select a component first.")
    value = state.components.payload.get(key)
    if isinstance(value, list) and not value and not lines:
        return
    if not lines:
        raise ValueError("Component content must contain at least one non-empty line.")
    if key == ComponentPool.TRAINING_EXAMPLES_KEY and isinstance(value, list):
        item = value[index]
        if isinstance(item, dict):
            item["content"] = lines
        else:
            value[index] = {"name": f"example_{index}", "content": lines}
        return
    if isinstance(value, list) and value and all(isinstance(item, str) for item in value) and index == 0:
        state.components.payload[key] = lines
        return
    if not isinstance(value, list) or index < 0 or index >= len(value):
        raise ValueError(f"Candidate index out of range for {key}.")
    value[index] = lines


def render_component_prompt(state: Any) -> str:
    """Render and cache the selected component prompt."""
    if not state.components.payload:
        state.components.rendered_prompt = ""
        state.components.prompt_token_summary = "Prompt tokens: 0"
        return ""
    update_component_candidate(state)
    pool = ComponentPool(state.components.payload)
    pool.configure_non_evolving_keys(list(state.config.non_evolving_prompt_components))
    selected = {key: state.components.prompt_selection.get(key, 0) for key in pool.component_keys}
    prompt = "\n".join(
        pool.render_prompt_lines(
            selected,
            include_identity_component=state.config.include_strategy_identity_in_prompt,
            use_few_shot_examples=state.config.use_few_shot_examples,
            min_examples=parse_nonnegative_int(state.config.min_examples, "min_examples"),
            max_examples=parse_example_max(state),
        )
    )
    token_count, exact = count_prompt_tokens(prompt)
    state.components.rendered_prompt = prompt
    state.components.prompt_token_summary = f"{'Prompt tokens' if exact else 'Prompt tokens ~'}: {token_count:,}"
    return prompt


def save_component_json(state: Any, destination: Path | None = None) -> Path:
    """Write the current component payload."""
    update_component_candidate(state)
    path = destination or state.components.loaded_path
    if path is None:
        raise ValueError("No component JSON path selected.")
    save_components(path, state.components.payload)
    state.components.loaded_path = path
    state.config.component_pool_path = relative_or_absolute(path)
    return path


def save_generated_config(state: Any) -> Path:
    """Persist the current state as an experiment config and sibling component JSON."""
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPERIMENT_DIR / safe_config_filename(state.config.config_name)
    component_path_override = None
    if state.components.payload:
        component_path = path.with_name(f"{path.stem}_components.json")
        save_component_json(state, component_path)
        component_path_override = relative_or_absolute(component_path)
    payload = build_config_payload(state, component_path_override=component_path_override)
    config_service.write_json_file(path, payload)
    state.config.generated_config_path = path
    state.config.base_config_path = str(path)
    return path


def build_config_payload(state: Any, component_path_override: str | None = None) -> dict[str, Any]:
    """Build one EAGLE config payload without changing its schema."""
    cfg = state.config
    sync_algorithm_operator_defaults(state)
    payload = load_config_payload(Path(cfg.base_config_path))
    component_path = component_path_override or cfg.component_pool_path
    if not component_path:
        raise ValueError("Runtime component path is required.")
    if not resolve_repo_path(component_path).exists():
        raise ValueError(f"Runtime component path does not exist: {component_path}")
    payload.update(
        {
            "application": cfg.application,
            "evaluator": cfg.evaluator,
            "algorithm": cfg.algorithm,
            "surrogate": cfg.surrogate,
            "population_size": parse_int(cfg.population_size, "population_size"),
            "num_generations": parse_int(cfg.num_generations, "num_generations"),
            "tick_limit": parse_int(cfg.tick_limit, "tick_limit"),
            "llm_call_limit": parse_int(cfg.llm_call_limit, "llm_call_limit"),
            "llm_model": cfg.llm_model.strip(),
            "llm_base_url": cfg.llm_base_url.strip(),
            "gameplay_map_dir": cfg.gameplay_map_dir.strip(),
            "gameplay_rate": parse_float(cfg.gameplay_rate, "gameplay_rate"),
            "gameplay_refresh_interval": parse_int(cfg.gameplay_refresh_interval, "gameplay_refresh_interval"),
            "surrogate_top_ratio": parse_float(cfg.surrogate_top_ratio, "surrogate_top_ratio"),
            "archive_parent_ratio": parse_float(cfg.archive_parent_ratio, "archive_parent_ratio"),
            "min_token_length": parse_int(cfg.min_token_length, "min_token_length"),
            "aggressiveness_objective_enabled": bool(cfg.aggressiveness_objective_enabled),
            "aggressiveness_mode": cfg.aggressiveness_mode
            if cfg.aggressiveness_mode in AGGRESSIVENESS_MODE_CHOICES
            else "hybrid",
            "aggressiveness_llm_weight": parse_float(
                cfg.aggressiveness_llm_weight,
                "aggressiveness_llm_weight",
            ),
            "aggressiveness_component_weight": parse_float(
                cfg.aggressiveness_component_weight,
                "aggressiveness_component_weight",
            ),
            "aggressiveness_judge_model": cfg.aggressiveness_judge_model.strip() or cfg.llm_model.strip(),
            "aggressiveness_judge_temperature": parse_float(
                cfg.aggressiveness_judge_temperature,
                "aggressiveness_judge_temperature",
            ),
            "objective_config": build_objective_config(state),
            "use_few_shot_examples": bool(cfg.use_few_shot_examples),
            "min_examples": parse_nonnegative_int(cfg.min_examples, "min_examples"),
            "max_examples": parse_example_max(state),
            "training_example_sample_count": training_example_selection_value(state),
            "training_example_fixed_count": bool(cfg.training_example_fixed_count),
            "final_test_max_front": parse_optional_nonnegative_int(cfg.final_test_max_front, "final_test_max_front"),
            "selection_method": "random",
            "parent_selection_operator": state.operators.parent_selection_operator,
            "tournament_size": 3,
            "crossover": state.operators.crossover_operator,
            "crossover_operator": state.operators.crossover_operator,
            "mutation_operator": state.operators.mutation_operator,
            "mutation_selection_mode": normalize_mutation_selection_mode(
                state.operators.mutation_selection_mode
            ),
            "environment_selection_method": state.operators.env_selection_operator,
            "env_selection_operator": state.operators.env_selection_operator,
            "crossover_repair_enabled": state.operators.crossover_repair_enabled
            if state.operators.crossover_operator == "uniform"
            else False,
            "enable_reflection_operator": bool(state.operators.enable_reflection_operator),
            "component_pool_path": component_path,
            "non_evolving_prompt_components": sorted(cfg.non_evolving_prompt_components),
            "gameplay_opponents": parse_target_list(cfg.opponents_text),
            "one_eval_rounds": parse_int(cfg.one_eval_rounds, "one_eval_rounds"),
            "reproduction_operator_probs": normalized_float_map(state.operators.reproduction_weights, "reproduction_operator_probs"),
            "example_reproduction_operator_probs": normalized_float_map(
                state.operators.example_reproduction_weights,
                "example_reproduction_operator_probs",
            ),
            "example_mutation_source_probs": normalized_float_map(
                state.operators.example_mutation_source_weights,
                "example_mutation_source_probs",
            ),
            "strategy_mutation": build_strategy_mutation_weights(state),
        }
    )
    if not payload["gameplay_opponents"]:
        raise ValueError("At least one gameplay opponent is required.")
    return payload


def objective_choices(state: Any) -> tuple[str, ...]:
    """Return objective registry names for the current application/eval mode."""
    names = list(list_objective_names(state.config.application, "full_game"))
    if (
        state.config.algorithm not in MO_ALGORITHMS
        or not state.config.aggressiveness_objective_enabled
    ):
        names = [name for name in names if name != "strategic_aggressiveness"]
    return tuple(names)


def objective_rows(state: Any) -> list[dict[str, str]]:
    """Return objective table rows."""
    rows = []
    for objective in get_objectives(state.config.application, "full_game"):
        state.objectives.weights.setdefault(objective.key, "1.0")
        rows.append(
            {
                "key": objective.key,
                "label": objective.label,
                "direction": objective.direction,
                "selected": "yes" if objective.key in state.objectives.selected else "no",
                "weight": state.objectives.weights.get(objective.key, "1.0"),
            }
        )
    return rows


def build_objective_config(state: Any) -> dict[str, Any]:
    """Build objective_config for GA and multi-objective algorithms."""
    choices = set(objective_choices(state))
    objectives = state.objectives
    if objectives.mode == "single":
        objective = objectives.single_objective
        if objective not in choices:
            raise ValueError(f"Objective {objective!r} is not available.")
        return {"mode": "single", "objective": objective}
    selected = [key for key in objective_choices(state) if key in objectives.selected]
    if state.config.algorithm in GA_ALGORITHMS:
        weights = {
            key: parse_float(value, f"weight for {key}")
            for key, value in objectives.weights.items()
            if key in choices and key in selected
        }
        weights = {key: value for key, value in weights.items() if value > 0}
        if not weights:
            raise ValueError("weighted_mix requires at least one positive weight.")
        total = sum(weights.values())
        return {"mode": "weighted_mix", "weights": {key: value / total for key, value in weights.items()}}
    if len(selected) < 2:
        raise ValueError("multi mode requires at least two objectives.")
    return {"mode": "multi", "objectives": selected}


def sync_algorithm_operator_defaults(state: Any) -> None:
    """Keep operator selections compatible with the chosen algorithm family."""
    algorithm = state.config.algorithm
    if algorithm not in ALGORITHM_CHOICES:
        state.config.algorithm = "nsga2"
        algorithm = "nsga2"
    state.operators.parent_selection_operator = ensure_operator_choice(
        state.operators.parent_selection_operator,
        "parent_selection",
        PARENT_SELECTION_BY_ALGORITHM[algorithm],
    )
    state.operators.env_selection_operator = ensure_operator_choice(
        state.operators.env_selection_operator,
        "env_selection",
        ENV_SELECTION_BY_ALGORITHM[algorithm],
    )
    state.operators.crossover_operator = ensure_operator_choice(state.operators.crossover_operator, "crossover", "uniform")
    state.operators.mutation_operator = ensure_operator_choice(state.operators.mutation_operator, "mutation", "mix")


def operator_choices(operator_type: str) -> tuple[str, ...]:
    """Return registered operator names for one operator kind."""
    return list_operator_names(operator_type)


def ensure_operator_choice(value: str, operator_type: str, default: str) -> str:
    """Return a registered operator, falling back to the supplied default."""
    choices = operator_choices(operator_type)
    if value in choices:
        return value
    return default if default in choices else (choices[0] if choices else value)


def build_strategy_mutation_weights(state: Any) -> dict[str, float]:
    """Return mutation weights according to the selected mutation operator."""
    selected = state.operators.mutation_operator
    if selected != "mix":
        return {selected: 1.0}
    choices = set(operator_choices("mutation")) - {"mix"}
    return normalized_float_map(
        {key: value for key, value in state.operators.mutation_weights.items() if key in choices},
        "strategy_mutation",
    )


def normalize_mutation_selection_mode(value: Any) -> str:
    """Return the current mutation-selection mode key."""
    normalized = str(value or "fixed").strip().lower()
    return normalized if normalized in MUTATION_SELECTION_MODE_CHOICES else "fixed"

def load_process_state() -> dict[str, Any]:
    """Load persisted web process state."""
    try:
        return process_service.load_process_state(GUI_PROCESS_STATE_PATH)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def monitored_pid() -> int | None:
    """Return the currently persisted experiment PID."""
    return process_service.parse_optional_pid(load_process_state().get("pid"))


def process_running() -> bool:
    """Return whether the persisted experiment is alive."""
    return process_service.process_is_running(monitored_pid())


def process_status_text(state: Any | None = None) -> str:
    """Return compact process status text."""
    pid = monitored_pid()
    tracked_returncode = _tracked_process_returncode(state, pid)
    if tracked_returncode is not None:
        status = "complete" if tracked_returncode == 0 else "failed"
        process_service.mark_process_state(GUI_PROCESS_STATE_PATH, status=status, returncode=tracked_returncode)
        if state is not None:
            state.runtime.is_running = False
            state.run.status_text = status
        return status
    if process_service.process_is_running(pid):
        return f"running pid {pid}"
    stored = load_process_state()
    stored_status = str(stored.get("status") or "")
    if stored_status in {"complete", "failed"}:
        return stored_status
    if pid is not None and stored.get("status") == "running":
        process_service.mark_process_state(GUI_PROCESS_STATE_PATH, status="exited")
        if state is not None:
            state.runtime.is_running = False
            state.run.status_text = "exited"
        return "exited"
    return "not running"


def _tracked_process_returncode(state: Any | None, pid: int | None) -> int | None:
    """Return the known return code for a GUI-owned process, reaping it if needed."""
    if state is None or pid is None:
        return None
    for process in list(getattr(state, "active_processes", []) or []):
        if int(getattr(process, "pid", -1)) != int(pid):
            continue
        returncode = process.poll()
        if returncode is None:
            return None
        try:
            state.active_processes.remove(process)
        except ValueError:
            pass
        return int(returncode)
    return None


def process_log_path() -> Path | None:
    """Return the persisted process log path when available."""
    value = load_process_state().get("log_path")
    if not value:
        return None
    return resolve_repo_path(str(value))


def read_log_tail(limit: int = LOG_TAIL_LIMIT) -> str:
    """Read the current experiment log tail."""
    with LoggedOperation("read experiment log tail", limit=limit):
        path = process_log_path()
        if path is None:
            return "No process log selected."
        if not path.exists():
            return f"Log file does not exist: {path}"
        LOGGER.info("reading large file path=%s", path)
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]


def launch_web_process(
    *,
    state: Any | None = None,
    command: list[str],
    config_path: Path,
    log_prefix: str,
    debug_lines: list[str] | None = None,
) -> tuple[bool, str]:
    """Launch one web-GUI managed process and persist monitor state."""
    with LoggedOperation("launch web process", log_prefix=log_prefix, config_path=config_path):
        if state is not None and getattr(state, "is_stopping", False):
            return False, "Shutdown is already in progress."
        if process_running():
            return False, "An experiment process is already running."
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"{log_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        log_handle = log_path.open("w", encoding="utf-8", errors="replace")
        log_handle.write("Command: " + " ".join(command) + "\n\n")
        for line in debug_lines or []:
            log_handle.write(line + "\n")
        if debug_lines:
            log_handle.write("\n")
        log_handle.flush()
        process = _launch_tracked_process(command, cwd=ROOT, stdout=log_handle, state=state)
        if state is not None:
            state.runtime.is_running = True
        process_service.write_process_state(
            GUI_PROCESS_STATE_PATH,
            pid=int(process.pid),
            command=command,
            cwd=ROOT,
            log_path=log_path,
            config_path=config_path,
        )
        return True, f"Started PID {process.pid}"


def start_experiment(state: Any) -> tuple[bool, str]:
    """Save config and start `python -m eagle.main --config <config>`."""
    with LoggedOperation("starting EA"):
        resume_run_dir = state.run.experiment_current_run_dir
        previous_run_dir = latest_experiment_run_dir()
        if resume_run_dir is None:
            config_path = save_generated_config(state)
            command = [sys.executable, "-m", "eagle.main", "--config", str(config_path)]
        else:
            config_path = Path(resume_run_dir) / "config.json"
            if not config_path.exists():
                raise ValueError(f"Selected run is missing config.json: {config_path}")
            command = [
                sys.executable,
                "-m",
                "eagle.main",
                "--resume-log-dir",
                str(resume_run_dir),
                "--config",
                str(config_path),
            ]
        if state.run.quick_run:
            command.append("--quick-run")
        if state.run.skip_final_test is True:
            command.append("--skip-final-test")
        if state.run.precompile_python:
            command.append("--precompile-python")
        success, message = launch_web_process(
            state=state,
            command=command,
            config_path=config_path,
            log_prefix="eagle_ui_process",
        )
        if success:
            if resume_run_dir is not None:
                state.run.experiment_current_run_dir = Path(resume_run_dir)
                state.analysis.analysis_selected_run_dir = Path(resume_run_dir)
                state.analysis.analysis_run_selected_manually = False
                return success, message
            run_dir = None
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                run_dir = latest_experiment_run_dir()
                if run_dir is not None and run_dir != previous_run_dir:
                    break
                time.sleep(0.1)
            if run_dir is not None and run_dir != previous_run_dir:
                state.run.experiment_current_run_dir = run_dir
                state.analysis.analysis_selected_run_dir = run_dir
                state.analysis.analysis_run_selected_manually = False
        return success, message


def start_final_test(state: Any) -> tuple[bool, str]:
    """Run batch final-test replay for the selected existing run folder."""
    with LoggedOperation("running final test"):
        run_dir = validate_run_dir(state.final_test.selected_run_dir)
        state.final_test.status_text = "running"
        try:
            run_final_test_batch(
                run_dir,
                map_folder=state.final_test.map,
                opponent=state.final_test.opponent,
            )
            results_path = latest_final_test_results_path(run_dir)
            state.final_test.status_text = "final test complete"
            state.final_test.analysis_output_path = str(results_path) if results_path is not None else ""
            state.final_test.analysis_text = build_final_test_results_text(run_dir)
            state.final_test.log_text = state.final_test.analysis_text
            return (
                True,
                f"Saved final test results to {results_path}" if results_path is not None else "Final test complete",
            )
        except (FileNotFoundError, OSError, ValueError, RuntimeError) as exc:
            state.final_test.status_text = "final test failed"
            state.final_test.analysis_text = str(exc)
            state.final_test.log_text = str(exc)
            return False, str(exc)


def validate_run_dir(run_dir: Path | None) -> Path:
    """Return a selected run directory that contains a config."""
    if run_dir is None:
        raise ValueError("Select a run folder first.")
    path = run_dir.expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise ValueError(f"Run folder does not exist: {path}")
    config_path = path / "config.json"
    if not config_path.exists():
        raise ValueError(f"Selected run is missing config.json: {config_path}")
    return path


def apply_final_test_max_front(config_path: Path, max_front: str) -> None:
    """Persist max-front override because `eagle.main` has no CLI flag for it."""
    text = str(max_front or "").strip()
    if not text:
        return
    parsed = parse_optional_nonnegative_int(text, "final_test_max_front")
    payload = config_service.read_json_mapping_strict(config_path)
    payload["final_test_max_front"] = parsed
    config_service.write_json_file(config_path, payload)


def stop_experiment(state: Any | None = None) -> str:
    """Terminate GUI-owned experiment work while keeping NiceGUI alive."""
    with LoggedOperation("stopping EA"):
        if state is not None:
            state.is_stopping = True
            _cancel_tasks(state)
        pid = monitored_pid()
        messages: list[str] = []
        if pid is None or not process_service.process_is_running(pid):
            messages.append("No running experiment process.")
        else:
            process_service.mark_process_state(GUI_PROCESS_STATE_PATH, status="stopping")
            terminate_pid_tree(pid)
            messages.append(f"Stopping PID {pid}")
        if state is not None:
            stop_microrts_gui(wait=True)
            _terminate_active_processes(state)
            _reset_runtime_state(state, clear_logs=False)
            state.is_stopping = False
        return " ".join(messages)


def shutdown_runtime(state: Any) -> str:
    """Stop web-GUI-managed runtime work and leave the GUI process alive."""
    state.is_stopping = True
    _cancel_tasks(state)
    _deactivate_timers(state)
    pid = monitored_pid()
    if pid is not None and process_service.process_is_running(pid):
        process_service.mark_process_state(GUI_PROCESS_STATE_PATH, status="stopping")
        terminate_pid_tree(pid)
    stop_microrts_gui(wait=True)
    _terminate_active_processes(state)
    _reset_runtime_state(state, clear_logs=True)
    state.is_stopping = False
    return "Shutdown complete"


def shutdown_app(state: Any, app_object: Any) -> str:
    """Request a NiceGUI server shutdown after runtime cleanup."""
    state.is_shutting_down = True
    shutdown = getattr(app_object, "shutdown", None)
    if callable(shutdown):
        shutdown()
        return "GUI shutdown requested"
    threading.Timer(0.25, os._exit, args=(0,)).start()
    return "GUI shutdown fallback scheduled"


def _launch_tracked_process(command: list[str], *, cwd: Path, stdout: Any, state: Any | None) -> subprocess.Popen:
    """Launch a subprocess and register only this GUI-owned handle."""
    with LoggedOperation("launching subprocess", cwd=cwd, command=command[0] if command else ""):
        options: dict[str, Any] = {}
        if os.name != "nt":
            options["start_new_session"] = True
        process = subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=subprocess.STDOUT, text=True, **options)
        if state is not None:
            state.active_processes.append(process)
        LOGGER.info("subprocess launched pid=%s command=%s", process.pid, command)
        return process


def terminate_pid_tree(pid: int, timeout_seconds: float = 5.0) -> None:
    """Terminate one tracked process tree, then force-kill it if it remains alive."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        _wait_for_pid_exit(int(pid), timeout_seconds)
        if process_service.process_is_running(pid):
            subprocess.run(
                ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        return
    try:
        os.killpg(int(pid), signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            return
    _wait_for_pid_exit(int(pid), timeout_seconds)
    if process_service.process_is_running(pid):
        try:
            os.killpg(int(pid), signal.SIGKILL)
        except OSError:
            try:
                os.kill(int(pid), signal.SIGKILL)
            except OSError:
                return


def _wait_for_pid_exit(pid: int, timeout_seconds: float) -> None:
    """Wait briefly for a process id to exit."""
    with LoggedOperation("waiting for subprocess", pid=pid, timeout_seconds=timeout_seconds):
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not process_service.process_is_running(pid):
                return
            time.sleep(0.1)


def _cancel_tasks(state: Any) -> None:
    """Cancel asyncio tasks registered by the NiceGUI dashboard."""
    for task in list(getattr(state, "active_tasks", [])):
        if not task.done():
            task.cancel()
    state.active_tasks.clear()


def _deactivate_timers(state: Any) -> None:
    """Deactivate timers registered by the NiceGUI dashboard."""
    for timer in list(getattr(state, "active_timers", [])):
        deactivate = getattr(timer, "deactivate", None)
        if callable(deactivate):
            deactivate()
        elif hasattr(timer, "active"):
            timer.active = False


def _terminate_active_processes(state: Any) -> None:
    """Terminate Popen handles launched and registered by this GUI."""
    with LoggedOperation("terminating active subprocesses", count=len(getattr(state, "active_processes", []))):
        processes = list(getattr(state, "active_processes", []))
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            if process.poll() is None:
                LOGGER.info("waiting for subprocess pid=%s timeout_seconds=5", process.pid)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        state.active_processes.clear()


def _reset_runtime_state(state: Any, *, clear_logs: bool) -> None:
    """Reset runtime-only state after shutdown."""
    process_service.mark_process_state(GUI_PROCESS_STATE_PATH, status="stopped")
    state.runtime.is_running = False
    state.run.status_text = "not running"
    state.final_test.status_text = "not running"
    state.microrts.status = "Java GUI not running"
    if clear_logs:
        state.run.log_text = ""
        state.final_test.log_text = ""
        state.microrts.log_text = ""


def build_analysis(run_dir: Path | None) -> tuple[str, str]:
    """Build the existing live-analysis report for one run."""
    with LoggedOperation("parsing logs", kind="live_analysis", run_dir=run_dir):
        if run_dir is None:
            return "No run selected", ""
        report = analysis_service.build_live_analysis_report(run_dir)
        return str(report.summary), str(report.body)


def run_analysis_subprocess(
    run_dir: Path | None,
    output_dir: Path | None,
    analysis_type: str,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    """Run analysis plotting in a subprocess and return a stable result object."""
    run_path = Path(run_dir).resolve() if run_dir is not None else None
    output_path = Path(output_dir).resolve() if output_dir is not None else None
    normalized_type = str(analysis_type or "").strip().lower()
    if run_path is None:
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "output_files": {},
            "error": "No run selected.",
        }

    command = [
        sys.executable,
        "-m",
        "eagle.analysis.run_analysis_cli",
        "--run-dir",
        str(run_path),
        "--type",
        normalized_type,
    ]
    if output_path is not None:
        command.extend(["--output-dir", str(output_path)])
    if extra_args:
        command.extend(str(arg) for arg in extra_args)

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=ANALYSIS_SUBPROCESS_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "output_files": {},
            "error": f"Analysis subprocess timed out after {ANALYSIS_SUBPROCESS_TIMEOUT_SEC} seconds.",
        }
    except OSError as exc:
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "output_files": {},
            "error": str(exc),
        }

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    parsed: dict[str, Any] | None = None
    stdout_text = stdout.strip()
    if stdout_text:
        try:
            payload = json.loads(stdout_text)
        except json.JSONDecodeError as exc:
            parsed = None
            parse_error = str(exc)
        else:
            parsed = payload if isinstance(payload, dict) else None
            parse_error = ""
    else:
        parse_error = ""

    if completed.returncode != 0 or parsed is None:
        error_text = ""
        if parsed is not None:
            error_text = str(parsed.get("error") or "")
        if not error_text:
            error_text = stderr.strip() or parse_error or stdout_text or f"Analysis subprocess exited with code {completed.returncode}."
        output_files = parsed.get("output_files") if isinstance(parsed, dict) and isinstance(parsed.get("output_files"), dict) else {}
        return {
            "ok": False,
            "stdout": stdout,
            "stderr": stderr,
            "output_files": output_files,
            "error": error_text,
        }

    output_files = parsed.get("output_files")
    if not isinstance(output_files, dict):
        output_files = {}
    return {
        "ok": bool(parsed.get("ok", True)),
        "stdout": stdout,
        "stderr": stderr,
        "output_files": output_files,
        "error": str(parsed.get("error") or ""),
    }


def build_timing(run_dir: Path | None) -> tuple[str, list[dict[str, Any]], str]:
    """Build the existing timing report for one run."""
    with LoggedOperation("parsing logs", kind="timing_analysis", run_dir=run_dir):
        if run_dir is None:
            return "No run selected", [], ""
        report = analysis_service.build_timing_analysis_report(run_dir)
        return str(report.summary), list(getattr(report, "rows", []) or []), str(report.body)


def latest_final_test_results_dir(run_dir: Path | None) -> Path | None:
    """Return the newest timestamped final-test results directory for one run."""
    if run_dir is None:
        return None
    path = Path(run_dir).resolve() / "final_test"
    if not path.exists():
        return None
    candidates = [
        candidate
        for candidate in path.iterdir()
        if candidate.is_dir() and (candidate / "results.json").exists()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate.stat().st_mtime, candidate.name))


def latest_final_test_results_path(run_dir: Path | None) -> Path | None:
    """Return the newest final-test results.json path for one run."""
    results_dir = latest_final_test_results_dir(run_dir)
    if results_dir is None:
        return None
    return results_dir / "results.json"


def build_final_test_results_text(run_dir: Path | None) -> str:
    """Render the latest batch final-test results as a compact text summary."""
    if run_dir is None:
        return "No final test results found."
    results_path = latest_final_test_results_path(run_dir)
    if results_path is None:
        return "No final test results found."
    try:
        payload = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return str(exc)
    analysis = parse_final_test_analysis(json.dumps(payload, ensure_ascii=False))
    if not analysis.get("has_final_test"):
        return "No final test results found."
    lines: list[str] = []
    lines.append(f"Source run: {analysis.get('source_run_dir', run_dir)}")
    lines.append(f"Mode: {analysis.get('mode', 'unknown')}")
    selection = dict(analysis.get("selection") or {})
    if selection:
        lines.append(
            "Selection: "
            f"{selection.get('type', 'unknown')} "
            f"({len(list(selection.get('individual_ids') or []))} individuals)"
        )
    config = dict(analysis.get("config") or {})
    if config.get("maps"):
        lines.append("Maps: " + ", ".join(str(item) for item in config["maps"]))
    if config.get("opponents"):
        lines.append("Opponents: " + ", ".join(str(item) for item in config["opponents"]))
    if "games" in analysis:
        lines.append(f"Games: {analysis['games']}")
    if analysis.get("win_rate") is not None:
        lines.append(f"Win rate: {float(analysis['win_rate']) * 100:.1f}%")
    for key, label in (
        ("mean_score", "Mean score"),
        ("worst_score", "Worst score"),
        ("best_score", "Best score"),
        ("mean_resource_difference", "Mean resource difference"),
        ("mean_weighted_resource_score", "Mean weighted resource score"),
    ):
        if analysis.get(key) is not None:
            lines.append(f"{label}: {float(analysis[key]):.4g}")
    if analysis.get("selection_type"):
        lines.append(f"Selection type: {analysis['selection_type']}")
    if analysis.get("results_path"):
        lines.append(f"Results file: {analysis['results_path']}")
    return "\n".join(lines)


def final_test_individual_choices(run_dir: Path | None) -> list[str]:
    """Return individual ids present in the newest final-test results."""
    results_path = latest_final_test_results_path(run_dir)
    if results_path is None:
        return []
    try:
        payload = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    records = payload.get("results") if isinstance(payload, dict) else []
    if not isinstance(records, list):
        return []
    return sorted(
        {
            str(record.get("individual_id"))
            for record in records
            if isinstance(record, dict) and record.get("individual_id")
        }
    )


def load_prompt_records(run_dir: Path | None) -> dict[str, dict[str, Any]]:
    """Load prompt records through the existing desktop service."""
    with LoggedOperation("parsing logs", kind="prompt_records", run_dir=run_dir):
        return analysis_service.load_prompts(run_dir)


def generate_mo_analysis_artifacts(run_dir: Path | None) -> dict[str, Any]:
    """Generate the existing MO Pareto plots and return their artifact paths."""
    if run_dir is None:
        return {"animation_path": "", "generation_choices": [], "static_plot_paths": {}}
    analysis_result = run_analysis_subprocess(Path(run_dir), Path(run_dir) / "analysis" / "evolution", "evolution")
    output_files = analysis_result.get("output_files") if isinstance(analysis_result, dict) else {}
    if not analysis_result.get("ok") or not isinstance(output_files, dict):
        return {"animation_path": "", "generation_choices": [], "static_plot_paths": {}}
    generation_choices: set[str] = set()
    static_plot_paths: dict[str, str] = {}
    for path_text in output_files.get("generation_scatter_figures", []) or []:
        path = Path(str(path_text))
        generation = _extract_mo_generation(path)
        if generation is None:
            continue
        generation_text = str(generation)
        generation_choices.add(generation_text)
        static_plot_paths[generation_text] = str(path)
    return {
        "animation_path": str(output_files.get("generation_animation_gif") or ""),
        "generation_choices": _sort_trace_values(generation_choices),
        "static_plot_paths": static_plot_paths,
    }


def load_llm_trace_records(run_dir: Path | None) -> list[dict[str, Any]]:
    """Load normalized runtime LLM debug records from a run directory."""
    if run_dir is None:
        return []
    run_dir = Path(run_dir)
    generation_path_root = run_dir / "llm_calls"
    if generation_path_root.exists():
        generation_jsonl_paths = list(generation_path_root.glob("generation_*.jsonl"))
        if generation_jsonl_paths:
            return _load_generation_trace_jsonl_records(generation_path_root)
        generation_json_paths = list(generation_path_root.glob("generation_*.json"))
        if generation_json_paths:
            return _load_generation_trace_json_records(generation_path_root)
    llm_debug_path = run_dir / "llm_debug.jsonl"
    if llm_debug_path.exists():
        return _load_llm_debug_trace_records(llm_debug_path)
    return _load_legacy_prompt_trace_records(run_dir)


def generation_choices(trace_records: list[dict[str, Any]]) -> list[str]:
    """Return sorted generation choices for LLM trace records."""
    return _sort_trace_values({str(record.get("generation", "")) for record in trace_records if record.get("generation", "") != ""})


def individual_choices(trace_records: list[dict[str, Any]], generation: str) -> list[str]:
    """Return sorted individual choices for one generation."""
    return _sort_trace_values(
        {
            str(record.get("individual_id", ""))
            for record in trace_records
            if str(record.get("generation", "")) == str(generation)
        }
    )


def llm_call_choices(trace_records: list[dict[str, Any]], generation: str, individual_id: str) -> dict[str, str]:
    """Return LLM call selector options for one generation and individual."""
    options: dict[str, str] = {}
    for record in trace_records:
        if str(record.get("generation", "")) != str(generation):
            continue
        if str(record.get("individual_id", "")) != str(individual_id):
            continue
        record_id = str(record.get("record_id", ""))
        if record_id:
            options[record_id] = llm_trace_label(record)
    return options


def get_llm_trace_record(records: list[dict[str, Any]], record_id: str) -> dict[str, Any] | None:
    """Return one normalized LLM trace record by record id."""
    for record in records:
        if str(record.get("record_id", "")) == str(record_id):
            return record
    return None


def llm_trace_label(record: dict[str, Any]) -> str:
    """Return a compact label for one LLM debug record."""
    return f"call {record.get('call_index', '')} | turn {record.get('turn', '')} | {record.get('mode', '')}"


def prompt_record_label(record_id: str, record: dict[str, Any]) -> str:
    """Return a compact prompt selector label."""
    return (
        f"gen {record.get('generation', '')} | {record.get('individual_id', '')} | "
        f"{record.get('evaluation_mode', '')} | {record_id}"
    )


def prompt_record_metadata(record: dict[str, Any]) -> str:
    """Return selected prompt metadata."""
    parts = [
        f"Generation: {record.get('generation', '')}",
        f"Individual: {record.get('individual_id', '')}",
        f"Mode: {record.get('evaluation_mode', '')}",
    ]
    if record.get("opponent"):
        parts.append(f"Opponent: {record.get('opponent')}")
    if record.get("fitness") not in (None, ""):
        parts.append(f"Fitness: {record.get('fitness')}")
    return " | ".join(parts)


def _trace_text(value: Any) -> str:
    """Return trace values as display-safe text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _trace_int(value: Any, default: int) -> int:
    """Return an integer trace value with a stable fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _load_generation_trace_jsonl_records(path_root: Path) -> list[dict[str, Any]]:
    """Load runtime trace records from per-generation JSONL files."""
    records: list[dict[str, Any]] = []
    for generation_path in sorted(path_root.glob("generation_*.jsonl"), key=lambda path: _numeric_sort_value(_extract_generation_name(path))):
        try:
            lines = generation_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            records.append(
                _normalize_generation_trace_record(
                    payload,
                    generation=_trace_text(payload.get("generation")),
                    default_call_index=line_number,
                    record_seed=f"{generation_path.name}:{line_number}",
                )
            )
    return sorted(records, key=_trace_sort_key)


def _load_generation_trace_json_records(path_root: Path) -> list[dict[str, Any]]:
    """Load runtime trace records from legacy per-generation JSON files."""
    records: list[dict[str, Any]] = []
    for generation_path in sorted(path_root.glob("generation_*.json"), key=lambda path: _numeric_sort_value(_extract_generation_name(path))):
        try:
            payload = json.loads(generation_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        generation = _trace_text(payload.get("generation"))
        generation_records = payload.get("records")
        if not isinstance(generation_records, list):
            continue
        for index, raw_record in enumerate(generation_records, start=1):
            if not isinstance(raw_record, dict):
                continue
            records.append(
                _normalize_generation_trace_record(
                    raw_record,
                    generation=generation,
                    default_call_index=index,
                    record_seed=f"{generation_path.name}:{index}",
                )
            )
    return sorted(records, key=_trace_sort_key)


def _load_llm_debug_trace_records(path: Path) -> list[dict[str, Any]]:
    """Load runtime trace records from the JSONL debug file."""
    records: list[dict[str, Any]] = []
    group_counts: dict[tuple[str, str], int] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        normalized = _normalize_llm_debug_record(payload, line_number=line_number, group_counts=group_counts)
        if normalized is not None:
            records.append(normalized)
    return sorted(records, key=_trace_sort_key)


def _load_legacy_prompt_trace_records(run_dir: Path) -> list[dict[str, Any]]:
    """Load legacy prompt records when trace files are unavailable."""
    try:
        prompt_records = analysis_service.load_prompts(run_dir)
    except (OSError, ValueError):
        return []
    trace_records: list[dict[str, Any]] = []
    for index, (record_id, record) in enumerate(prompt_records.items(), start=1):
        generation = _trace_text(record.get("generation"))
        individual_id = _trace_text(record.get("individual_id"))
        trace_records.append(
            {
                "record_id": str(record_id),
                "generation": generation,
                "individual_id": individual_id,
                "mode": _trace_text(record.get("evaluation_mode")),
                "opponent": _trace_text(record.get("opponent")),
                "turn": "",
                "call_index": index,
                "timestamp": "",
                "input": _trace_text(record.get("prompt")),
                "raw_response_body": "",
                "parsed_response": "",
                "final_response": _trace_text(record.get("llm_output")),
                "fallback_response": _trace_text(record.get("llm_output")),
                "llm_output": _trace_text(record.get("llm_output")),
                "error": "",
            }
        )
    return sorted(trace_records, key=_trace_sort_key)


def _normalize_generation_trace_record(
    raw_record: dict[str, Any], *, generation: str, default_call_index: int, record_seed: str
) -> dict[str, Any]:
    """Normalize one per-generation trace record."""
    input_text = _trace_text(
        raw_record.get("input")
        or raw_record.get("prompt")
        or raw_record.get("llm_input")
        or raw_record.get("request_prompt")
    )
    raw_response_body = _trace_text(
        raw_record.get("raw_response_body")
        or raw_record.get("raw_response")
        or raw_record.get("response_body")
    )
    parsed_response = _trace_text(raw_record.get("parsed_response") or raw_record.get("parsed_text") or raw_record.get("model_text") or raw_record.get("response"))
    if not parsed_response:
        extracted_response = _extract_ollama_response(raw_response_body)
        if extracted_response:
            parsed_response = extracted_response
    final_response = _trace_text(raw_record.get("final_response") or raw_record.get("llm_output"))
    fallback_response = _trace_text(raw_record.get("fallback_response") or raw_record.get("llm_output"))
    llm_output = _trace_text(raw_record.get("llm_output") or raw_record.get("final_response"))
    record_id = _trace_text(raw_record.get("record_id"))
    if not record_id:
        record_id = record_seed
    return {
        "record_id": record_id,
        "generation": _trace_text(raw_record.get("generation") if raw_record.get("generation") not in (None, "") else generation),
        "individual_id": _trace_text(raw_record.get("individual_id")),
        "call_index": _trace_int(raw_record.get("call_index"), default_call_index),
        "mode": _trace_text(raw_record.get("mode") if raw_record.get("mode") not in (None, "") else raw_record.get("evaluation_mode")),
        "opponent": _trace_text(raw_record.get("opponent")),
        "turn": _trace_text(raw_record.get("turn")),
        "timestamp": _trace_text(raw_record.get("timestamp")),
        "input": input_text,
        "raw_response_body": raw_response_body,
        "parsed_response": parsed_response,
        "final_response": final_response,
        "fallback_response": fallback_response,
        "llm_output": llm_output or final_response or fallback_response,
        "error": _trace_text(raw_record.get("error")),
    }


def _normalize_llm_debug_record(
    payload: dict[str, Any], *, line_number: int, group_counts: dict[tuple[str, str], int]
) -> dict[str, Any] | None:
    """Normalize one JSONL debug record into the viewer schema."""
    generation = _trace_text(payload.get("generation"))
    individual_id = _trace_text(payload.get("individual_id"))
    group_key = (generation, individual_id)
    group_counts[group_key] = group_counts.get(group_key, 0) + 1
    call_index = _trace_int(payload.get("call_index"), group_counts[group_key])
    input_text = _trace_text(payload.get("prompt") or payload.get("input") or "")
    parsed_response = _trace_text(
        payload.get("parsed_response")
        or payload.get("parsed_text")
        or payload.get("model_text")
        or payload.get("response")
    )
    if not parsed_response:
        extracted_response = _extract_ollama_response(_trace_text(payload.get("raw_response_body")))
        if extracted_response:
            parsed_response = extracted_response
    final_response = _trace_text(payload.get("final_response") or payload.get("llm_output"))
    fallback_response = _trace_text(payload.get("fallback_response") or payload.get("llm_output") or "")
    raw_response_body = _trace_text(payload.get("raw_response_body") or payload.get("raw_response") or payload.get("response_body") or "")
    record_id = _trace_text(payload.get("record_id")) or f"{generation}|{individual_id}|{call_index}|{line_number}"
    return {
        "record_id": record_id,
        "generation": generation,
        "individual_id": individual_id,
        "mode": _trace_text(payload.get("mode") if payload.get("mode") not in (None, "") else payload.get("evaluation_mode")),
        "opponent": _trace_text(payload.get("opponent")),
        "turn": _trace_text(payload.get("turn")) or _extract_prompt_turn(input_text),
        "call_index": call_index,
        "timestamp": _trace_text(payload.get("timestamp")),
        "input": input_text,
        "raw_response_body": raw_response_body,
        "parsed_response": parsed_response,
        "final_response": final_response,
        "fallback_response": fallback_response,
        "llm_output": _trace_text(payload.get("llm_output")) or final_response or fallback_response,
        "error": _trace_text(payload.get("error")),
    }


def _extract_ollama_response(raw_response_body: str) -> str:
    """Extract an Ollama `response` field from a raw JSON response body."""
    if not raw_response_body.strip():
        return ""
    try:
        payload = json.loads(raw_response_body)
    except json.JSONDecodeError:
        return ""
    if isinstance(payload, dict):
        return _trace_text(payload.get("response"))
    return ""


def _extract_mo_generation(path: Path) -> int | None:
    """Extract the generation number from one Pareto scatter plot path."""
    match = re.search(r"generation_(\d+)_fitness_scatter\.png$", path.name)
    if match is None:
        return None
    return int(match.group(1))


def _extract_generation_name(path: Path) -> str:
    """Return the generation name embedded in a generation JSON file path."""
    import re

    match = re.search(r"generation_(.+)\.jsonl?$", path.name)
    return match.group(1) if match else path.stem


def _extract_prompt_turn(prompt: str) -> str:
    """Extract the first MicroRTS Turn value from a prompt when present."""
    import re

    match = re.search(r"^\s*Turn:\s*([^\n]+)\s*$", str(prompt or ""), re.MULTILINE)
    return match.group(1).strip() if match else ""


def _trace_sort_key(record: dict[str, Any]) -> tuple[Any, ...]:
    """Sort trace records by generation, individual, call index, and timestamp."""
    return (
        _numeric_sort_value(record.get("generation")),
        str(record.get("individual_id", "")),
        int(record.get("call_index", 0)),
        str(record.get("timestamp", "")),
    )


def _sort_trace_values(values: set[str]) -> list[str]:
    """Sort trace selector values numerically when possible."""
    return sorted((value for value in values if value != ""), key=_numeric_sort_value)


def _numeric_sort_value(value: Any) -> tuple[int, Any]:
    """Return a key that sorts numeric text before lexical text."""
    text = str(value or "")
    try:
        return (0, int(text))
    except ValueError:
        return (1, text)


def save_current_prompt_to_microrts(prompt: str) -> Path:
    """Save the active prompt to the vendored MicroRTS prompt file."""
    if not prompt.strip():
        raise ValueError("Render or select a prompt first.")
    return save_microrts_prompt(ROOT, prompt)


def launch_microrts_gui(state: Any) -> str:
    """Launch the visible Java MicroRTS GUI."""
    global _microrts_process, _microrts_log_path
    with LoggedOperation("launching MicroRTS"):
        if getattr(state, "is_stopping", False):
            raise RuntimeError("Shutdown is already in progress.")
        if _microrts_process and _microrts_process.poll() is None:
            raise RuntimeError("MicroRTS is already running.")
        prompt_path = save_current_prompt_to_microrts(state.microrts.prompt_text)
        microrts_root = require_microrts_class("rts/MicroRTS.class")
        update_interval = parse_int(state.microrts.update_interval, "update_interval")
        llm_interval = parse_int(state.microrts.llm_interval, "llm_interval")
        opponent = state.microrts.opponent.strip()
        map_location = selected_microrts_map(state)
        if not opponent:
            raise ValueError("Opponent is required.")
        set_config_property(ROOT, "launch_mode", "STANDALONE")
        set_config_property(ROOT, "headless", "false")
        set_config_property(ROOT, "map_location", map_location)
        set_config_property(ROOT, "AI1", "ai.eagle.EAGLE")
        set_config_property(ROOT, "AI2", opponent)
        set_config_property(ROOT, "update_interval", str(update_interval))
        set_config_property(ROOT, "llm_interval", str(llm_interval))
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _microrts_log_path = LOG_DIR / f"microrts_eagle_ui_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        classpath = f"{microrts_root / 'lib' / '*'}{os.pathsep}{microrts_root / 'bin'}"
        command = [
            "java",
            "-Deagle.debug=true",
            f"-Dmicrorts.prompt={prompt_path}",
            f"-Dmicrorts.llm_interval={llm_interval}",
            f"-Dmicrorts.llm_call_limit={state.config.llm_call_limit}",
            "-cp",
            classpath,
            "rts.MicroRTS",
        ]
        if state.microrts.save_trace:
            trace_path = microrts_trace_dir() / f"gui_trace_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            command.insert(5, f"-Dmicrorts.trace.path={trace_path}")
            state.microrts.selected_trace = str(trace_path)
        log_handle = _microrts_log_path.open("w", encoding="utf-8", errors="replace")
        log_handle.write("Command: " + " ".join(command) + "\n")
        log_handle.write(f"Prompt: {prompt_path}\nOpponent: {opponent}\nMap: {map_location}\n\n")
        log_handle.flush()
        _microrts_process = _launch_tracked_process(command, cwd=microrts_root, stdout=log_handle, state=state)
        return f"MicroRTS PID {_microrts_process.pid}"


def stop_microrts_gui(wait: bool = False) -> str:
    """Stop the visible Java MicroRTS process."""
    global _microrts_process
    with LoggedOperation("stopping MicroRTS", wait=wait):
        if not _microrts_process or _microrts_process.poll() is not None:
            return "Java GUI not running"
        _microrts_process.terminate()
        if wait:
            LOGGER.info("waiting for subprocess pid=%s timeout_seconds=5", _microrts_process.pid)
            try:
                _microrts_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _microrts_process.kill()
        return f"Stopping MicroRTS PID {_microrts_process.pid}"


def microrts_status_text() -> str:
    """Return current Java GUI status."""
    if not _microrts_process:
        return "Java GUI not running"
    if _microrts_process.poll() is None:
        return f"MicroRTS PID {_microrts_process.pid}"
    return f"MicroRTS exited with code {_microrts_process.returncode}"


def read_microrts_log() -> str:
    """Read the current Java GUI log."""
    with LoggedOperation("read MicroRTS log"):
        if _microrts_log_path is None:
            return ""
        if not _microrts_log_path.exists():
            return f"Log file does not exist: {_microrts_log_path}"
        LOGGER.info("reading large file path=%s", _microrts_log_path)
        return _microrts_log_path.read_text(encoding="utf-8", errors="replace")


def open_trace(trace_text: str, state: Any | None = None) -> str:
    """Open a saved trace in the Java trace viewer."""
    with LoggedOperation("launching MicroRTS trace viewer"):
        trace_path = Path(trace_text)
        if not trace_path.exists():
            raise FileNotFoundError(f"Trace file does not exist: {trace_path}")
        microrts_root = require_microrts_class("gui/TraceViewerMain.class")
        classpath = f"{microrts_root / 'lib' / '*'}{os.pathsep}{microrts_root / 'bin'}"
        _launch_tracked_process(
            ["java", "-cp", classpath, "gui.TraceViewerMain", str(trace_path)],
            cwd=microrts_root,
            stdout=subprocess.DEVNULL,
            state=state,
        )
        return f"Opened trace {trace_path.name}"


def microrts_root_path() -> Path:
    """Return the vendored MicroRTS root."""
    return ROOT / "third_party" / "microrts"


def require_microrts_class(class_file: str) -> Path:
    """Return MicroRTS root if the required class is compiled."""
    microrts_root = microrts_root_path()
    required = microrts_root / "bin" / class_file
    if not required.exists():
        raise FileNotFoundError(
            "Missing MicroRTS class file. Compile from WSL first under third_party/microrts."
        )
    return microrts_root


def microrts_map_dir_choices() -> tuple[str, ...]:
    """Return first-level MicroRTS map folders."""
    maps_dir = microrts_root_path() / "maps"
    if not maps_dir.exists():
        return ("8x8",)
    choices = sorted(path.name for path in maps_dir.iterdir() if path.is_dir())
    return tuple(choices) if choices else ("8x8",)


def microrts_map_file_choices(map_dir: str) -> tuple[str, ...]:
    """Return XML maps inside one map folder."""
    maps_dir = microrts_root_path() / "maps" / str(map_dir or "").strip()
    if not maps_dir.exists():
        return ("basesWorkers8x8.xml",)
    choices = sorted(path.name for path in maps_dir.glob("*.xml") if path.is_file())
    return tuple(choices) if choices else ("basesWorkers8x8.xml",)


def selected_microrts_map(state: Any) -> str:
    """Return the selected MicroRTS map path."""
    return f"maps/{state.microrts.map_dir.strip()}/{state.microrts.map_file.strip()}"


def microrts_trace_dir() -> Path:
    """Return the GUI-visible trace directory."""
    return MICRORTS_LOG_DIR / "traces"


def microrts_trace_choices() -> list[str]:
    """Return saved trace files newest first."""
    roots = [microrts_trace_dir(), MICRORTS_LOG_DIR, LOG_DIR]
    paths: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for pattern in ("*.xml", "*.zip"):
            for path in root.rglob(pattern):
                if path.is_file() and path not in seen:
                    seen.add(path)
                    paths.append(path)
    return [str(path) for path in sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)]


def safe_config_filename(raw_name: str) -> str:
    """Return a safe JSON config filename."""
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in raw_name.strip())
    if not safe:
        safe = timestamped_stem("eagle_ui_evolution")
    return safe if safe.endswith(".json") else f"{safe}.json"


def training_example_selection_value(state: Any) -> str | int:
    """Return current training-example sample-count value."""
    cfg = state.config
    if cfg.training_example_fixed_count:
        return parse_nonnegative_int(cfg.training_example_fixed_sample_count, "training_example_fixed_sample_count")
    lower = parse_nonnegative_int(cfg.training_example_sample_min, "training_example_sample_min")
    upper = parse_nonnegative_int(cfg.training_example_sample_max, "training_example_sample_max")
    if lower > upper:
        lower, upper = upper, lower
    return f"random_{lower}_{upper}"


def parse_example_max(state: Any) -> int:
    """Parse and validate the few-shot example sample range upper bound."""
    cfg = state.config
    lower = parse_nonnegative_int(cfg.min_examples, "min_examples")
    upper = parse_nonnegative_int(cfg.max_examples, "max_examples")
    if upper < lower:
        raise ValueError("max_examples must be >= min_examples.")
    return upper


def parse_target_list(value: Any) -> list[str]:
    """Parse comma/list opponent values."""
    if isinstance(value, list):
        items = value
    else:
        items = str(value or "").split(",")
    return [str(item).strip() for item in items if str(item).strip()]


def normalized_float_map(values: dict[str, str], field_name: str) -> dict[str, float]:
    """Parse and normalize a probability map."""
    parsed = {key: parse_float(value, key) for key, value in values.items()}
    total = sum(parsed.values())
    if total <= 0:
        raise ValueError(f"{field_name} must have a positive total weight.")
    return {key: value / total for key, value in parsed.items()}


def parse_int(value: Any, field_name: str) -> int:
    """Parse a positive integer field."""
    try:
        parsed = int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc
    if parsed < 1:
        raise ValueError(f"{field_name} must be >= 1.")
    return parsed


def parse_nonnegative_int(value: Any, field_name: str) -> int:
    """Parse a non-negative integer field."""
    try:
        parsed = int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc
    if parsed < 0:
        raise ValueError(f"{field_name} must be >= 0.")
    return parsed


def parse_optional_nonnegative_int(value: Any, field_name: str) -> int | None:
    """Parse an optional non-negative integer field."""
    text = str(value or "").strip()
    if not text or text.lower() == "none":
        return None
    return parse_nonnegative_int(text, field_name)


def parse_float(value: Any, field_name: str) -> float:
    """Parse a non-negative float field."""
    try:
        parsed = float(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a number.") from exc
    if parsed < 0:
        raise ValueError(f"{field_name} must be >= 0.")
    return parsed


def parse_range(text: str, *, default: tuple[int, int]) -> tuple[int, int]:
    """Parse simple A-B range text."""
    import re

    match = re.search(r"(\d+)\s*-\s*(\d+)", text)
    if not match:
        return default
    lower, upper = int(match.group(1)), int(match.group(2))
    return (lower, upper) if lower <= upper else (upper, lower)


def resolve_repo_path(path_text: str) -> Path:
    """Resolve a path against the repository root."""
    path = Path(path_text)
    return path if path.is_absolute() else ROOT / path


def relative_or_absolute(path: Path) -> str:
    """Return a repository-relative path when possible."""
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())
