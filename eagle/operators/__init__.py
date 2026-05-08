"""Default operator registry entries and plugin-style operator lookup."""

from .defaults import register_default_operators
from .registry import OPERATOR_REGISTRY, get_operator

register_default_operators()

__all__ = ["OPERATOR_REGISTRY", "get_operator", "register_default_operators"]
