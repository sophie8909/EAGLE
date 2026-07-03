"""Default operator registry entries and plugin-style operator lookup."""

from .base import OperatorContext
from .defaults import register_default_operators
from .registry import OPERATOR_REGISTRY, get_operator, list_operator_names

register_default_operators()

__all__ = [
    "OPERATOR_REGISTRY",
    "OperatorContext",
    "get_operator",
    "list_operator_names",
    "register_default_operators",
]
