from __future__ import annotations

import signal
import subprocess
import sys
import unittest

from eagle.interrupts import install_interrupt_handlers


class InterruptTests(unittest.TestCase):
    def test_sigterm_raises_keyboard_interrupt_and_handler_is_restored(self):
        previous = signal.getsignal(signal.SIGTERM)
        restore = install_interrupt_handlers()
        try:
            with self.assertRaises(KeyboardInterrupt):
                signal.raise_signal(signal.SIGTERM)
        finally:
            restore()
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    @unittest.skipUnless(sys.platform == "win32", "requires a Windows console")
    def test_ctrl_break_wakes_blocking_wait_and_runs_cleanup(self):
        import ctypes

        if not ctypes.windll.kernel32.GetConsoleWindow():
            self.skipTest("run in a console to deliver Ctrl+Break")
        code = """
import time
from eagle.interrupts import install_interrupt_handlers
restore = install_interrupt_handlers()
try:
    print('ready', flush=True)
    time.sleep(60)
except KeyboardInterrupt:
    print('cleaned', flush=True)
finally:
    restore()
"""
        child = subprocess.Popen(
            [sys.executable, "-u", "-c", code], stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            child.send_signal(signal.CTRL_BREAK_EVENT)
            output, _ = child.communicate(timeout=5)
            self.assertEqual(child.returncode, 0, output)
            self.assertIn("cleaned", output)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdout.close()


if __name__ == "__main__":
    unittest.main()
