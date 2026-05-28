"""Plugin-style registry for evolutionary operators."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from eagle.operators.base import (
    BaseCrossover,
    BaseMutation,
    BaseOperator,
    BaseParentSelection,
    BaseReflection,
    BaseReplacement,
)


_PACKAGE_ROOT = Path(__file__).resolve().parent
_DISCOVERY_PACKAGES = {
    "mutation": ("mutation", BaseMutation),
    "crossover": ("crossover", BaseCrossover),
    "reflection": ("reflection", BaseReflection),
    "parent_selection": ("parent_selection", BaseParentSelection),
    "env_selection": ("env_selection", BaseReplacement),
}


def _normalize_name(name: str) -> str:
    """Normalize config names without changing their public spelling rules."""
    return str(name).strip().lower().replace("-", "_")


def _operator_name(operator_cls: type[BaseOperator]) -> str:
    """Return the registry key for one operator class."""
    configured_name = getattr(operator_cls, "name", "") or operator_cls.__name__
    return _normalize_name(configured_name)


def _iter_plugin_modules(package_name: str):
    """Yield importable module names for all Python files in one operator package."""
    package_dir = _PACKAGE_ROOT / package_name
    if not package_dir.exists():
        return
    for path in sorted(package_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        yield f"eagle.operators.{package_name}.{path.stem}"


def _discover_operator_group(package_name: str, expected_base: type[BaseOperator]) -> dict[str, type]:
    """Import one operator package and collect concrete operator classes."""
    discovered: dict[str, type] = {}
    for module_name in _iter_plugin_modules(package_name) or ():
        module = import_module(module_name)
        for value in vars(module).values():
            if not isinstance(value, type):
                continue
            if value is expected_base or value is BaseOperator:
                continue
            if value.__module__ != module.__name__:
                continue
            if not issubclass(value, expected_base):
                continue
            if not getattr(value, "name", ""):
                continue
            discovered[_operator_name(value)] = value
    return discovered


def _build_registry() -> dict[str, dict[str, type]]:
    """Discover all operator plugins from the operator package folders."""
    registry: dict[str, dict[str, type]] = {}
    for operator_type, (package_name, expected_base) in _DISCOVERY_PACKAGES.items():
        registry[operator_type] = _discover_operator_group(package_name, expected_base)

    return registry


OPERATOR_REGISTRY: dict[str, dict[str, type]] = _build_registry()

_EXPECTED_BASES = {
    "mutation": BaseMutation,
    "crossover": BaseCrossover,
    "reflection": BaseReflection,
    "parent_selection": BaseParentSelection,
    "env_selection": BaseReplacement,
}

def list_operator_names(operator_type: str) -> tuple[str, ...]:
    """Return sorted registered operator names for one operator type."""
    normalized_type = _normalize_name(operator_type)
    if normalized_type not in OPERATOR_REGISTRY:
        known_types = ", ".join(sorted(OPERATOR_REGISTRY))
        raise ValueError(
            f"Unknown operator type {operator_type!r}. Known types: {known_types}."
        )
    return tuple(sorted(OPERATOR_REGISTRY[normalized_type]))


def get_operator(
    operator_type: str,
    operator_name: str,
    config: dict | None = None,
):
    """Instantiate one registered operator by type and name."""
    normalized_type = _normalize_name(operator_type)
    if normalized_type not in OPERATOR_REGISTRY:
        known_types = ", ".join(sorted(OPERATOR_REGISTRY))
        raise ValueError(
            f"Unknown operator type {operator_type!r}. Known types: {known_types}."
        )

    normalized_name = _normalize_name(operator_name)
    operators = OPERATOR_REGISTRY[normalized_type]
    if normalized_name not in operators:
        known_names = ", ".join(sorted(operators))
        raise ValueError(
            f"Unknown {normalized_type} operator {operator_name!r}. "
            f"Known names: {known_names}."
        )

    operator_cls = operators[normalized_name]
    expected_base = _EXPECTED_BASES[normalized_type]
    if not issubclass(operator_cls, expected_base):
        raise ValueError(
            f"Registered {normalized_type} operator {normalized_name!r} "
            f"must inherit {expected_base.__name__}."
        )

    return operator_cls(config)
