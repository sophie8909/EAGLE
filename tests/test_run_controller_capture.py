import subprocess
import sys
import threading
import unittest
from pathlib import Path

from eagle_ui.controllers.run_controller import RunController
from eagle_ui.state import RunState


class RunControllerCaptureTests(unittest.TestCase):
    def test_drains_stdout_and_stderr_and_keeps_nonzero_exit(self):
        state = RunState()
        controller = RunController(Path.cwd(), state)
        process = subprocess.Popen(
            [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        controller._process = process
        readers = [
            threading.Thread(target=controller._read_stream, args=(process.stdout, "stdout")),
            threading.Thread(target=controller._read_stream, args=(process.stderr, "stderr")),
        ]
        for reader in readers:
            reader.start()
        for reader in readers:
            reader.join()
        controller._wait_for_exit()
        records = state.logs.snapshot()
        self.assertEqual(set(record.stream for record in records), {"stdout", "stderr", "system"})
        self.assertEqual(records[-1].stream, "system")
        self.assertIn("code 3", records[-1].message)
        process.stdout.close(); process.stderr.close()


if __name__ == "__main__":
    unittest.main()
