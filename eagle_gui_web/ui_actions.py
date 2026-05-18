"""Safe NiceGUI callback wrappers."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import Any

from nicegui import ui
from nicegui.context import context

LOGGER = logging.getLogger(__name__)


def safe_click(action: Callable[..., Any], *, label: str, notify_result: bool = False) -> Callable[..., Any]:
    """Run one UI action in a task and report boundary failures."""

    def handle(*args: Any, **kwargs: Any) -> Any:
        async def run() -> None:
            LOGGER.info("GUI callback start label=%s", label)
            try:
                result = action(*args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                notify_callback_error(label, exc)
            else:
                if notify_result:
                    notify_callback_result(result)
                LOGGER.info("GUI callback end label=%s", label)

        return run()

    return handle


def notify_callback_result(result: Any) -> None:
    """Notify one callback result when a NiceGUI context is available."""
    if not isinstance(result, tuple) or len(result) != 2:
        return
    success, message = result
    try:
        context.slot
        ui.notify(str(message), type="positive" if success else "warning")
    except RuntimeError:
        LOGGER.info("GUI callback result notification skipped message=%s", message)


def notify_callback_error(label: str, exc: Exception) -> None:
    """Report callback errors without creating a second slot-context failure."""
    try:
        context.slot
        ui.notify(f"{label} failed: {exc}", type="negative")
    except RuntimeError:
        LOGGER.exception("GUI callback failed label=%s", label)
