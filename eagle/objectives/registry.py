"""Plugin-style registry for objective implementations."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from eagle.objectives.base import BaseObjective


_PACKAGE_ROOT = Path(__file__).resolve().parent


def _normalize_name(name: str) -> str:
    """Normalize objective names without changing their public spelling rules."""
    return str(name).strip().lower().replace("-", "_")


def _iter_plugin_modules():
    """Yield importable objective plugin modules."""
    for path in sorted(_PACKAGE_ROOT.glob("*.py")):
        if path.name in {"__init__.py", "base.py", "registry.py"}:
            continue
        yield f"eagle.objectives.{path.stem}"


def _discover_objectives() -> dict[str, type[BaseObjective]]:
    """Import objective modules and collect concrete objective classes."""
    discovered: dict[str, type[BaseObjective]] = {}
    for module_name in _iter_plugin_modules():
        module = import_module(module_name)
        for value in vars(module).values():
            if not isinstance(value, type):
                continue
            if value is BaseObjective:
                continue
            if value.__module__ != module.__name__:
                continue
            if not issubclass(value, BaseObjective):
                continue
            if not getattr(value, "name", ""):
                continue
            discovered[_normalize_name(value.name)] = value
    return discovered


OBJECTIVE_REGISTRY: dict[str, type[BaseObjective]] = _discover_objectives()


def list_objective_names(evaluator: str | None = None) -> tuple[str, ...]:
    """Return sorted objective plugin names."""
    if evaluator is None:
        return tuple(sorted(OBJECTIVE_REGISTRY))
    normalized_evaluator = _normalize_name(evaluator)
    return tuple(
        sorted(
            name
            for name, objective_cls in OBJECTIVE_REGISTRY.items()
            if _normalize_name(getattr(objective_cls, "evaluator", "")) == normalized_evaluator
        )
    )


def get_objective(objective_name: str, config: dict | None = None) -> BaseObjective:
    """Instantiate one registered objective by name."""
    normalized_name = _normalize_name(objective_name)
    if normalized_name not in OBJECTIVE_REGISTRY:
        known_names = ", ".join(sorted(OBJECTIVE_REGISTRY))
        raise ValueError(
            f"Unknown objective {objective_name!r}. Known objectives: {known_names}."
        )
    return OBJECTIVE_REGISTRY[normalized_name](config)
