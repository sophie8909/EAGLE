"""CLI for the local, read-only EAGLE experiment monitor."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from eagle.monitoring import (
    DEFAULT_STALE_AFTER_SECONDS,
    ExperimentStatusCollector,
    RunsRootStatusCollector,
    serve_status,
    write_status_snapshot,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve read-only EAGLE experiment status.")
    locations = parser.add_mutually_exclusive_group()
    locations.add_argument("--run-dir", type=Path, help="one canonical eagle-run-v2 directory")
    locations.add_argument(
        "--runs-root",
        type=Path,
        default=Path("runs"),
        help="root whose direct canonical run children are discovered automatically (default: runs)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address; token protection is optional")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--token", help="optional Bearer token for /status")
    parser.add_argument("--pid", type=int, help="optional experiment PID to report")
    parser.add_argument(
        "--snapshot-file",
        type=Path,
        help="derived JSON snapshot to update periodically (default: <runs-root>/monitor_status.json)",
    )
    parser.add_argument(
        "--snapshot-interval",
        default=30.0,
        type=float,
        metavar="SECONDS",
        help="snapshot update interval (default: 30)",
    )
    parser.add_argument(
        "--stale-after",
        default=DEFAULT_STALE_AFTER_SECONDS,
        type=float,
        metavar="SECONDS",
        help="mark an initialized/running run stale after this many seconds",
    )
    parser.add_argument("--once", action="store_true", help="print one JSON status snapshot and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.run_dir is not None:
        collector = ExperimentStatusCollector(
            args.run_dir,
            stale_after_seconds=args.stale_after,
            pid=args.pid,
        )
    else:
        if args.pid is not None:
            raise SystemExit("--pid can only be used with --run-dir")
        collector = RunsRootStatusCollector(
            args.runs_root,
            stale_after_seconds=args.stale_after,
        )
    snapshot_path = args.snapshot_file
    if snapshot_path is None:
        snapshot_root = args.runs_root if args.run_dir is None else args.run_dir.parent
        snapshot_path = snapshot_root / "monitor_status.json"
    if args.once:
        payload = collector.collect_summary()
        write_status_snapshot(snapshot_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"EAGLE monitor listening on http://{args.host}:{args.port}", flush=True)
    print("GET /health for liveness; GET /status for all discovered runs", flush=True)
    print(f"JSON snapshot: {snapshot_path}", flush=True)
    serve_status(
        collector,
        host=args.host,
        port=args.port,
        token=args.token,
        snapshot_path=snapshot_path,
        snapshot_interval=args.snapshot_interval,
    )
    return 0
