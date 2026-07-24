"""Bounded process log records shared by runtime services and the GUI."""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock

@dataclass(frozen=True)
class ProcessLogRecord:
    timestamp: str
    source: str
    stream: str
    message: str
    process: str
    severity: str = "info"

    @classmethod
    def create(cls, *, source: str, stream: str, message: str, process: str, severity: str | None = None):
        return cls(datetime.now(timezone.utc).isoformat(timespec="milliseconds"), source, stream, message, process, severity or ("error" if stream == "stderr" else "info"))

    def display(self) -> str:
        return f"{self.timestamp[11:23]} [{self.stream.upper():6}] {self.message}"

class ProcessLogBuffer:
    def __init__(self, max_lines: int = 2000) -> None:
        self._records = deque(maxlen=max(1, max_lines))
        self._lock = Lock()

    def append(self, record: ProcessLogRecord) -> None:
        with self._lock:
            self._records.append(record)

    def snapshot(self) -> tuple[ProcessLogRecord, ...]:
        with self._lock:
            return tuple(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
