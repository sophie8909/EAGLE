"""Collect lightweight timing and JSONL profiling records for EAGLE runs."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


@contextmanager
def timer(name: str, stats: dict[str, float]) -> Iterator[None]:
    """Accumulate elapsed time for one named phase into the provided stats dict."""
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    stats[name] = stats.get(name, 0.0) + elapsed


def summarize_total_eval_time(stats: dict[str, float]) -> float:
    """Recompute the aggregate `total_eval_time` from all `*_time` entries."""
    nested_time_keys = {"microrts_compile_time"}
    total = 0.0
    for key, value in stats.items():
        if key.endswith("_time") and key != "total_eval_time" and key not in nested_time_keys:
            total += value
    stats["total_eval_time"] = total
    return total


def write_jsonl(record: dict[str, Any], path: str | Path) -> None:
    """Append one JSON object as a JSONL row, creating parent folders if needed."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_base_record(
    *,
    generation: int | None = None,
    individual_id: str | None = None,
    record_type: str,
) -> dict[str, Any]:
    """Create the common metadata envelope shared by profiler records."""
    return {
        "timestamp": datetime.now().isoformat(),
        "record_type": record_type,
        "generation": generation,
        "individual_id": individual_id,
    }


class RunTimingRecorder:
    """Record run-level phase timings and emit compact analysis artifacts."""

    def __init__(self, log_dir: str | Path) -> None:
        """Bind the recorder to one run directory."""
        self.log_dir = Path(log_dir)
        self.events_path = self.log_dir / "timing_events.jsonl"
        self.summary_path = self.log_dir / "timing_summary.json"
        self.report_path = self.log_dir / "timing_report.md"
        self.started_at = datetime.now().isoformat(timespec="seconds")

    @contextmanager
    def phase(
        self,
        name: str,
        *,
        generation: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[None]:
        """Time one named run phase and append a JSONL event."""
        start = time.perf_counter()
        ok = False
        try:
            yield
            ok = True
        finally:
            elapsed = time.perf_counter() - start
            record = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "record_type": "timing_event",
                "phase": name,
                "generation": generation,
                "elapsed_sec": elapsed,
                "ok": ok,
            }
            if metadata:
                record["metadata"] = dict(metadata)
            write_jsonl(record, self.events_path)

    def write_summary(self, *, status: str = "running") -> dict[str, Any]:
        """Aggregate timing events and write JSON plus Markdown summaries."""
        events = self._load_events()
        by_phase: dict[str, dict[str, float]] = {}
        by_generation: dict[str, float] = {}
        total = 0.0
        for event in events:
            phase = str(event.get("phase") or "unknown")
            elapsed = self._safe_float(event.get("elapsed_sec"))
            if elapsed is None:
                continue
            total += elapsed
            stats = by_phase.setdefault(
                phase,
                {"count": 0.0, "total_sec": 0.0, "max_sec": 0.0},
            )
            stats["count"] += 1.0
            stats["total_sec"] += elapsed
            stats["max_sec"] = max(stats["max_sec"], elapsed)
            generation = event.get("generation")
            if generation is not None:
                by_generation[str(generation)] = by_generation.get(str(generation), 0.0) + elapsed

        for stats in by_phase.values():
            count = max(1.0, stats["count"])
            stats["avg_sec"] = stats["total_sec"] / count

        summary = {
            "record_type": "timing_summary",
            "started_at": self.started_at,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "status": status,
            "event_count": len(events),
            "total_recorded_sec": total,
            "by_phase": by_phase,
            "by_generation": by_generation,
            "top_phases": self._top_phase_rows(by_phase),
            "recommendations": self._recommendations(by_phase),
        }
        self.summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        self.report_path.write_text(self._format_markdown(summary), encoding="utf-8")
        return summary

    def _load_events(self) -> list[dict[str, Any]]:
        """Load all timing JSONL rows for this run."""
        if not self.events_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.events_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        """Return value as float when possible."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _top_phase_rows(by_phase: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
        """Return phase rows ordered by total time descending."""
        rows = []
        for phase, stats in by_phase.items():
            rows.append(
                {
                    "phase": phase,
                    "count": int(stats.get("count", 0.0)),
                    "total_sec": float(stats.get("total_sec", 0.0)),
                    "avg_sec": float(stats.get("avg_sec", 0.0)),
                    "max_sec": float(stats.get("max_sec", 0.0)),
                }
            )
        return sorted(rows, key=lambda row: row["total_sec"], reverse=True)

    @staticmethod
    def _recommendations(by_phase: dict[str, dict[str, float]]) -> list[str]:
        """Generate conservative speed-up hints from observed phase costs."""
        rows = RunTimingRecorder._top_phase_rows(by_phase)
        if not rows:
            return ["No timing data has been recorded yet."]

        hints: list[str] = []
        top = rows[0]
        if top["phase"] in {"evaluate_initial_population", "evaluate_offspring", "gameplay_match"}:
            hints.append("Evaluation dominates runtime; reduce opponents, game seconds, or gameplay_rate first.")
        if by_phase.get("microrts_compile", {}).get("total_sec", 0.0) > 1.0:
            hints.append("MicroRTS compilation is visible; incremental compile skipping should help repeated gameplay runs.")
        if by_phase.get("round_llm_request", {}).get("total_sec", 0.0) > 1.0:
            hints.append("Round LLM requests dominate local surrogate time; lower one_eval_rounds or use prompt history reuse for faster iteration.")
        hints.append("Python bytecode precompile only helps startup/import overhead; it will not speed Java matches or LLM calls.")
        return hints

    @staticmethod
    def _format_markdown(summary: dict[str, Any]) -> str:
        """Render the timing summary as a small Markdown report."""
        lines = [
            "# Timing Analysis",
            "",
            f"Status: {summary.get('status')}",
            f"Updated: {summary.get('updated_at')}",
            f"Events: {summary.get('event_count')}",
            f"Total recorded seconds: {float(summary.get('total_recorded_sec', 0.0)):.3f}",
            "",
            "## Top phases",
            "",
            "| Phase | Count | Total sec | Avg sec | Max sec |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for row in summary.get("top_phases", []):
            lines.append(
                f"| {row['phase']} | {row['count']} | "
                f"{row['total_sec']:.3f} | {row['avg_sec']:.3f} | {row['max_sec']:.3f} |"
            )
        lines.extend(["", "## Recommendations", ""])
        for hint in summary.get("recommendations", []):
            lines.append(f"- {hint}")
        return "\n".join(lines) + "\n"
