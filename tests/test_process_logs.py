import sys
import time
import unittest

from eagle.runtime.process_logs import ProcessLogBuffer, ProcessLogRecord


class ProcessLogTests(unittest.TestCase):
    def test_records_keep_stream_and_bound_retention(self):
        buffer = ProcessLogBuffer(max_lines=2)
        buffer.append(ProcessLogRecord.create(source="experiment", stream="stdout", process="p", message="one"))
        buffer.append(ProcessLogRecord.create(source="experiment", stream="stderr", process="p", message="two"))
        buffer.append(ProcessLogRecord.create(source="experiment", stream="system", process="p", message="exit", severity="error"))
        records = buffer.snapshot()
        self.assertEqual([record.stream for record in records], ["stderr", "system"])
        self.assertIn("[SYSTEM]", records[-1].display())

    def test_subprocess_style_records_retain_final_nonzero_exit(self):
        buffer = ProcessLogBuffer()
        buffer.append(ProcessLogRecord.create(source="experiment", stream="stdout", process="child", message="incremental"))
        buffer.append(ProcessLogRecord.create(source="experiment", stream="stderr", process="child", message="failure"))
        buffer.append(ProcessLogRecord.create(source="experiment", stream="system", process="child", message="process exited with code 3", severity="error"))
        self.assertEqual([record.message for record in buffer.snapshot()], ["incremental", "failure", "process exited with code 3"])
        self.assertEqual(buffer.snapshot()[1].severity, "error")


if __name__ == "__main__":
    unittest.main()
