"""Interrupt CLI work while retaining its normal finally-based cleanup."""
from __future__ import annotations

import signal
import sys
from collections.abc import Callable


def install_interrupt_handlers() -> Callable[[], None]:
    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupt)
    kernel = handler = None
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        handler_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

        @handler_type
        def handler(event):
            if event == 1:  # CTRL_BREAK_EVENT
                # SIGBREAK alone does not wake Windows blocking waits; SIGINT does.
                signal.raise_signal(signal.SIGINT)
                return True
            return False

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.SetConsoleCtrlHandler.argtypes = (handler_type, wintypes.BOOL)
        kernel.SetConsoleCtrlHandler.restype = wintypes.BOOL
        if not kernel.SetConsoleCtrlHandler(handler, True):
            signal.signal(signal.SIGTERM, previous)
            raise ctypes.WinError(ctypes.get_last_error())

    def restore():
        if kernel is not None:
            kernel.SetConsoleCtrlHandler(handler, False)
        signal.signal(signal.SIGTERM, previous)

    return restore
