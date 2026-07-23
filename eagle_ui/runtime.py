"""Runtime settings for the EAGLE NiceGUI app."""

from __future__ import annotations

import os


DEFAULT_GUI_PORT = 8082
GUI_PORT_ENV = "EAGLE_GUI_PORT"


def resolve_gui_port() -> int:
    value = os.environ.get(GUI_PORT_ENV, str(DEFAULT_GUI_PORT)).strip()
    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError(f"{GUI_PORT_ENV} must be an integer port.") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"{GUI_PORT_ENV} must be between 1 and 65535.")
    return port
