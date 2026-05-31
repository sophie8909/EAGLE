"""Registry and fitness construction helpers for objective plugins."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

from eagle.objectives.base import Objective


_PACKAGE_ROOT = Path(__file__).resolve().parent


def _normalize_name(name: str) -> str:
    """Normalize public objective, application, and eval-mode names."""
    return str(name).strip().lower().replace("-", "_").replace(" ", "_")


def normalize_objective_key(key: str) -> str:
    """Normalize one current objective key without applying legacy aliases.

    Args:
        key: Objective key from config, GUI state, or result analysis input.

    Returns:
        The separator/case-normalized objective key. Unsupported names are rejected by
        `validate_objective_config` or `get_objective` instead of being silently mapped.
    """
    return _normalize_name(key)


def _iter_plugin_modules() -> tuple[str, ...]:
    """Return importable objective plugin module names."""
    modules: list[str] = []
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        if path.name in {"__init__.py", "base.py", "registry.py"}:
            continue
        relative = path.relative_to(_PACKAGE_ROOT).with_suffix("")
        module_suffix = ".".join(relative.parts)
        modules.append(f"eagle.objectives.{module_suffix}")
    return tuple(modules)


def _discover_objectives() -> dict[str, type[Objective]]:
    """Import objective modules and collect concrete objective classes."""
    discovered: dict[str, type[Objective]] = {}
    for module_name in _iter_plugin_modules():
        module = import_module(module_name)
        for value in vars(module).values():
            if not isinstance(value, type):
                continue
            if value is Objective:
                continue
            if value.__module__ != module.__name__:
                continue
            if not issubclass(value, Objective):
                continue
            key = _normalize_name(getattr(value, "key", ""))
            if not key:
                continue
            discovered[key] = value
    return discovered


OBJECTIVE_REGISTRY: dict[str, dict[str, type[Objective]]] = {}


def register_objective(application: str, objective: Objective | type[Objective]) -> None:
    """Register one objective instance or class for an application."""
    normalized_application = _normalize_name(application)
    objective_cls = objective if isinstance(objective, type) else objective.__class__
    key = _normalize_name(getattr(objective_cls, "key", ""))
    if not key:
        raise ValueError("Objective key must be non-empty.")
    OBJECTIVE_REGISTRY.setdefault(normalized_application, {})[key] = objective_cls


def _ensure_discovered() -> None:
    """Populate the registry from plugin modules once."""
    if OBJECTIVE_REGISTRY:
        return
    for objective_cls in _discover_objectives().values():
        application = getattr(objective_cls, "application", "")
        register_objective(application, objective_cls)


def get_objective(application: str, key: str) -> Objective:
    """Instantiate one registered objective by application and key."""
    _ensure_discovered()
    normalized_application = _normalize_name(application)
    normalized_key = normalize_objective_key(key)
    application_registry = OBJECTIVE_REGISTRY.get(normalized_application, {})
    if normalized_key not in application_registry:
        known_keys = ", ".join(sorted(application_registry))
        raise ValueError(f"Unknown {application} objective {key!r}. Known objectives: {known_keys}.")
    return application_registry[normalized_key]()


def get_objectives(application: str, eval_mode: str) -> tuple[Objective, ...]:
    """Return objectives available for one application/eval-mode pair."""
    _ensure_discovered()
    normalized_application = _normalize_name(application)
    normalized_eval_mode = _normalize_name(eval_mode)
    objectives: list[Objective] = []
    for objective_cls in OBJECTIVE_REGISTRY.get(normalized_application, {}).values():
        eval_modes = {_normalize_name(mode) for mode in getattr(objective_cls, "eval_modes", set())}
        if normalized_eval_mode in eval_modes:
            objectives.append(objective_cls())
    return tuple(sorted(objectives, key=lambda objective: objective.key))


def list_objective_names(application: str | None = None, eval_mode: str | None = None) -> tuple[str, ...]:
    """Return objective keys, optionally filtered by application and eval mode."""
    _ensure_discovered()
    if application is None and eval_mode is None:
        names: list[str] = []
        for application_registry in OBJECTIVE_REGISTRY.values():
            names.extend(application_registry)
        return tuple(sorted(names))
    if application is None or eval_mode is None:
        raise ValueError("application and eval_mode must be provided together.")
    return tuple(objective.key for objective in get_objectives(application, eval_mode))


def objective_eval_mode(config: Any, eval_result: dict | None = None) -> str:
    """Resolve the objective-facing eval mode from config and evaluator output."""
    if eval_result and eval_result.get("eval_mode"):
        return _normalize_name(eval_result.get("eval_mode"))

    explicit_eval_mode = getattr(config, "eval_mode", None)
    if explicit_eval_mode:
        return _normalize_name(explicit_eval_mode)

    evaluator = _normalize_name(getattr(config, "evaluator", "gameplay"))
    if evaluator != "gameplay":
        return evaluator

    if eval_result:
        result_eval_mode = _normalize_name(eval_result.get("evaluation_mode", ""))
        if result_eval_mode == "gameplay":
            return "full_game"
        if result_eval_mode in {"policy_agent", "java_agent", "java_surrogate"}:
            return "java_surrogate"

    algorithm = _normalize_name(getattr(config, "algorithm", "nsga2"))
    if algorithm not in {"ga_surrogate", "nsga2_surrogate"}:
        return "full_game"

    surrogate = _normalize_name(getattr(config, "surrogate", "round"))
    if surrogate in {"policy_agent", "java_agent", "java_surrogate"}:
        return "java_surrogate"
    return "full_game"


def default_objective_config(config: Any) -> dict[str, Any]:
    """Create a conservative objective config for the current algorithm/eval mode."""
    eval_mode = objective_eval_mode(config)
    objectives = list_objective_names("microrts", eval_mode)
    if not objectives:
        return {"mode": "multi", "objectives": []}
    algorithm = _normalize_name(getattr(config, "algorithm", "nsga2"))
    single_objective = algorithm in {"ga", "ga_surrogate"}
    if single_objective:
        return {"mode": "single", "objective": objectives[0]}
    return {"mode": "multi", "objectives": objectives[:2] if len(objectives) > 1 else objectives}


def validate_required_metrics(objective: Objective, eval_result: dict) -> None:
    """Raise when an objective's required raw metrics are missing."""
    missing = sorted(metric for metric in objective.required_metrics if metric not in eval_result)
    if missing:
        raise ValueError(
            f"Objective {objective.key!r} requires missing eval_result metrics: {', '.join(missing)}."
        )


def validate_objective_config(config: Any, eval_result: dict | None = None) -> dict[str, Any]:
    """Validate and normalize objective_config for the active eval mode."""
    application = _normalize_name(getattr(config, "application", "microrts") or "microrts")
    eval_mode = objective_eval_mode(config, eval_result)
    available = {objective.key for objective in get_objectives(application, eval_mode)}
    objective_config = dict(getattr(config, "objective_config", None) or default_objective_config(config))
    mode = _normalize_name(objective_config.get("mode", ""))
    if mode not in {"single", "weighted_mix", "multi"}:
        raise ValueError("objective_config.mode must be 'single', 'weighted_mix', or 'multi'.")

    if mode == "single":
        objective = normalize_objective_key(objective_config.get("objective", ""))
        if not objective:
            raise ValueError("single objective_config requires exactly one objective.")
        _validate_supported_objectives([objective], available, eval_mode)
        return {"mode": "single", "objective": objective}

    if mode == "weighted_mix":
        raw_weights = dict(objective_config.get("weights") or {})
        if not raw_weights:
            raise ValueError("weighted_mix objective_config requires at least one weighted objective.")
        weights = {
            normalize_objective_key(key): float(value)
            for key, value in raw_weights.items()
            if float(value) > 0
        }
        if not weights:
            raise ValueError("weighted_mix objective_config requires at least one positive weight.")
        _validate_supported_objectives(weights.keys(), available, eval_mode)
        total = sum(weights.values())
        normalized_weights = {key: value / total for key, value in weights.items()}
        return {"mode": "weighted_mix", "weights": normalized_weights}

    objectives = [normalize_objective_key(key) for key in objective_config.get("objectives", [])]
    if len(objectives) < 1:
        raise ValueError("multi objective_config requires at least one objective.")
    if len(objectives) < 2 and eval_mode != "early_end":
        raise ValueError("multi objective_config requires at least two objectives.")
    _validate_supported_objectives(objectives, available, eval_mode)
    return {"mode": "multi", "objectives": objectives}


def selected_objective_names(config: Any, eval_result: dict | None = None) -> tuple[str, ...]:
    """Return objective names selected by config for algorithms and reports."""
    objective_config = validate_objective_config(config, eval_result)
    mode = objective_config["mode"]
    if mode == "single":
        return (objective_config["objective"],)
    if mode == "weighted_mix":
        return tuple(objective_config["weights"].keys())
    return tuple(objective_config["objectives"])


def _validate_supported_objectives(objectives: Any, available: set[str], eval_mode: str) -> None:
    """Raise if any selected objective is unavailable for the active eval mode."""
    selected = list(objectives)
    unsupported = [key for key in selected if key not in available]
    if unsupported:
        raise ValueError(
            "Selected objectives do not support current eval_mode "
            f"{eval_mode!r}: {', '.join(unsupported)}."
        )
