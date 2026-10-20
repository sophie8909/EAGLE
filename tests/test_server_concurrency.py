"""Shared server capacity and concurrent event persistence contracts."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import unittest

from eagle.execution import llm_request_slot
from eagle.timing import append_event


class ServerConcurrencyTests(unittest.TestCase):
    def test_same_server_shares_two_slots_across_api_paths_and_models(self):
        occupied = threading.Barrier(3, timeout=3)
        release = threading.Event()
        third_entered = threading.Event()

        def hold(url):
            with llm_request_slot(url):
                occupied.wait()
                self.assertTrue(release.wait(3))

        def third():
            with llm_request_slot("http://capacity.test:8000/v1/chat/completions"):
                third_entered.set()

        with ThreadPoolExecutor(max_workers=3) as executor:
            first = executor.submit(hold, "http://capacity.test:8000")
            second = executor.submit(hold, "http://CAPACITY.test:8000/v1")
            try:
                occupied.wait()
                last = executor.submit(third)
                self.assertFalse(third_entered.wait(0.1))
            finally:
                release.set()
            for future in (first, second, last):
                future.result(timeout=3)
        self.assertTrue(third_entered.is_set())

    def test_other_server_proceeds_and_exception_returns_capacity(self):
        entered = threading.Event()

        def other_server():
            with llm_request_slot("http://independent.test:9001"):
                entered.set()

        with llm_request_slot("http://independent.test:9000"):
            with llm_request_slot("http://independent.test:9000/v1"):
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(other_server)
                    self.assertTrue(entered.wait(3))
                    future.result(timeout=3)
        with self.assertRaisesRegex(RuntimeError, "request failed"):
            with llm_request_slot("http://independent.test:9000"):
                raise RuntimeError("request failed")
        with llm_request_slot("http://independent.test:9000"):
            with llm_request_slot("http://independent.test:9000"):
                pass

    def test_overlapping_match_and_llm_events_remain_complete_json_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timing.jsonl"
            records = [{"index": index, "evidence": "測試" * 1000} for index in range(80)]
            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(lambda record: append_event(path, record), records))
            actual = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(sorted(actual, key=lambda record: record["index"]), records)


if __name__ == "__main__":
    unittest.main()
