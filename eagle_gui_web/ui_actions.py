"""Safe NiceGUI callback wrappers."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import Any

from nicegui import ui

LOGGER = logging.getLogger(__name__)


def safe_click(action: Callable[..., Any], *, label: str) -> Callable[..., None]:
    """Run one UI action in a task and report boundary failures."""

    def handle(*args: Any, **kwargs: Any) -> None:
        async def run() -> None:
            LOGGER.info("GUI callback start label=%s", label)
            try:
                result = action(*args, **kwargs)
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("GUI callback failed label=%s", label)
                ui.notify("GUI error: check terminal/logs/gui_runtime.log", type="negative")
            else:
                LOGGER.info("GUI callback end label=%s", label)

        asyncio.create_task(run())

    return handle
