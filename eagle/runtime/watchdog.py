"""Small GUI liveness watchdog started by the canonical ``run.sh`` entrypoint.

The watchdog owns only liveness reporting for the GUI process. The GUI owns
experiment and LLM server children; the watchdog never starts or restarts
those services and therefore cannot overlap their lifecycle ownership.
"""

from __future__ import annotations

import argparse
import os
import time


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch one EAGLE GUI process.")
    parser.add_argument("--pid", type=int, required=True, dest="gui_pid")
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if args.interval <= 0:
        raise ValueError("watchdog interval must be positive")
    print(f"EAGLE watchdog active for GUI pid {args.gui_pid}", flush=True)
    while _is_alive(args.gui_pid):
        time.sleep(args.interval)
    print(f"EAGLE watchdog observed GUI pid {args.gui_pid} exit", flush=True)
    return 0


def _is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


if __name__ == "__main__":
    raise SystemExit(main())
