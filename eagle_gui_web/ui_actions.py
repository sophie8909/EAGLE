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
            try:
                result = action(*args, **kwargs)
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.exception("%s failed", label)
                ui.notify(f"{label} failed: {exc}", type="negative")

        asyncio.create_task(run())

    return handle
