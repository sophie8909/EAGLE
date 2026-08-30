from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.codex_budget import (
    LOCAL_SNAPSHOT_STALE_SECONDS,
    build_report,
    combine_snapshots,
    normalize_snapshot,
    read_usage,
)


NOW = datetime(2026, 8, 26, 12, tzinfo=timezone.utc)


def meter(used: float, duration: int, reset: datetime) -> dict[str, object]:
    return {"used_percent": used, "window_duration_mins": duration, "resets_at": reset.isoformat()}


def snapshot(weekly_used: float = 45, five_used: float = 20, *, weekly_reset: datetime | None = None, five_reset: datetime | None = None) -> dict[str, object]:
    return {
        "limit_id": "fixture",
        "limit_name": "fixture limit",
        "plan_type": "pro",
        "primary": meter(weekly_used, 10080, weekly_reset or NOW + timedelta(days=4)),
        "secondary": meter(five_used, 300, five_reset or NOW + timedelta(hours=3)),
    }


def write_event(root: Path, name: str, timestamp: datetime, rate_limits: object) -> Path:
    path = root / "sessions" / "2026" / "08" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {"timestamp": timestamp.isoformat(), "type": "event_msg", "payload": {"type": "token_count", "rate_limits": rate_limits}}
    path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    os.utime(path, (timestamp.timestamp(), timestamp.timestamp()))
    return path


class CodexBudgetTests(unittest.TestCase):
    def report_for(self, limits: object, *, timestamp: datetime = NOW) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as directory:
            write_event(Path(directory), "rollout.jsonl", timestamp, limits)
            return read_usage(directory, no_live=True, now=NOW)

    def test_normal_weekly_snapshot(self):
        report = self.report_for(snapshot())
        self.assertEqual(report["weekly"]["used_percent"], 45)
        self.assertEqual(report["weekly"]["remaining_percent"], 55)
        self.assertEqual(report["budget"]["recommended_mode"], "NORMAL")
        self.assertEqual(report["metadata"]["plan_type"], "pro")

    def test_actual_snake_case_window_minutes_shape_is_parsed(self):
        limits = {
            "limit_id": "codex",
            "plan_type": "prolite",
            "primary": {
                "used_percent": 11,
                "window_minutes": 10080,
                "resets_at": (NOW + timedelta(days=5)).isoformat(),
            },
            "secondary": None,
        }
        report = self.report_for(limits)
        self.assertEqual(report["weekly"]["used_percent"], 11)
        self.assertEqual(report["weekly"]["remaining_percent"], 89)

    def test_weekly_remaining_near_reserve_is_critical(self):
        report = self.report_for(snapshot(weekly_used=86, weekly_reset=NOW + timedelta(days=1)))
        self.assertEqual(report["budget"]["recommended_mode"], "CRITICAL")
        self.assertEqual(report["budget"]["usable_percent"], 2)

    def test_weekly_at_or_below_reserve_stops(self):
        report = self.report_for(snapshot(weekly_used=88))
        self.assertEqual(report["budget"]["recommended_mode"], "STOP")
        self.assertEqual(report["budget"]["usable_percent"], 0)

    def test_high_quota_is_normal_early_and_aggressive_near_reset(self):
        early = self.report_for(snapshot(weekly_used=20, weekly_reset=NOW + timedelta(days=6, hours=20)))
        late = self.report_for(snapshot(weekly_used=20, weekly_reset=NOW + timedelta(hours=12)))
        self.assertEqual(early["budget"]["recommended_mode"], "NORMAL")
        self.assertEqual(late["budget"]["recommended_mode"], "AGGRESSIVE")

    def test_constrained_five_hour_downgrades_healthy_weekly_budget(self):
        report = self.report_for(snapshot(weekly_used=45, five_used=92))
        self.assertEqual(report["budget"]["recommended_mode"], "CRITICAL")

    def test_live_buckets_choose_the_most_constrained_valid_meter(self):
        general = normalize_snapshot(snapshot(weekly_used=11, five_used=0))
        model = normalize_snapshot(snapshot(weekly_used=60, five_used=95))
        assert general is not None and model is not None
        report = build_report(combine_snapshots([general, model], timestamp=NOW), "fixture", None, now=NOW)
        self.assertEqual(report["weekly"]["remaining_percent"], 40)
        self.assertEqual(report["five_hour"]["remaining_percent"], 5)
        self.assertEqual(report["budget"]["recommended_mode"], "CRITICAL")
        self.assertEqual(len(report["meters"]), 4)
        self.assertEqual(report["snapshot_age_seconds"], 0)

    def test_stale_snapshot_is_unknown(self):
        report = self.report_for(snapshot(), timestamp=NOW - timedelta(seconds=LOCAL_SNAPSHOT_STALE_SECONDS + 1))
        self.assertTrue(report["stale"])
        self.assertEqual(report["budget"]["recommended_mode"], "UNKNOWN")

    def test_missing_telemetry_is_unknown_not_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            report = read_usage(directory, no_live=True, now=NOW)
        self.assertEqual(report["budget"]["recommended_mode"], "UNKNOWN")
        self.assertIsNone(report["source"])

    def test_malformed_telemetry_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "sessions" / "bad.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text("not json\n" + json.dumps({"payload": {"type": "token_count", "rate_limits": {"primary": {"wat": 1}}}}), encoding="utf-8")
            report = read_usage(directory, no_live=True, now=NOW)
        self.assertEqual(report["budget"]["recommended_mode"], "UNKNOWN")

    def test_newest_valid_snapshot_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_event(root, "old.jsonl", NOW - timedelta(minutes=2), snapshot(weekly_used=80))
            latest_path = root / "archived_sessions" / "latest.jsonl"
            latest_path.parent.mkdir(parents=True)
            event = {"timestamp": NOW.isoformat(), "type": "event_msg", "payload": {"type": "token_count", "rate_limits": snapshot(weekly_used=40)}}
            latest_path.write_text("broken line\n" + json.dumps(event) + "\n", encoding="utf-8")
            os.utime(latest_path, (NOW.timestamp(), NOW.timestamp()))
            report = read_usage(directory, no_live=True, now=NOW)
        self.assertEqual(report["weekly"]["used_percent"], 40)
        self.assertIn("archived_sessions", report["source"])

    def test_malformed_tail_does_not_hide_earlier_valid_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_event(root, "tail.jsonl", NOW, snapshot(weekly_used=40))
            with path.open("a", encoding="utf-8") as handle:
                handle.write("{malformed tail}\n")
            report = read_usage(directory, no_live=True, now=NOW)
        self.assertEqual(report["weekly"]["used_percent"], 40)

    def test_unknown_fields_do_not_crash_or_change_known_meters(self):
        limits = snapshot()
        limits["server_experiment"] = {"surprise": [1, 2, 3]}
        limits["primary"]["new_field"] = True
        report = self.report_for(limits)
        self.assertEqual(report["five_hour"]["remaining_percent"], 80)
        self.assertEqual(report["budget"]["recommended_mode"], "NORMAL")

    def test_past_reset_is_unknown(self):
        report = self.report_for(snapshot(weekly_reset=NOW - timedelta(seconds=1)))
        self.assertEqual(report["weekly"]["resets_at"], None)
        self.assertEqual(report["budget"]["recommended_mode"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
