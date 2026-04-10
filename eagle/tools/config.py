"""Compatibility shim for config imports.

The canonical config module now lives at `eagle.config`. This file remains so
older imports such as `eagle.tools.config` continue to work during the
transition.
"""

from ..config import EAConfig, load_config_from_json, load_config_payload

__all__ = [
    "EAConfig",
    "load_config_from_json",
    "load_config_payload",
]
