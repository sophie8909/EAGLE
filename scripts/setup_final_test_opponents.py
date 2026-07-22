"""Prepare pinned TMA, Mayari, and COAC final-test dependencies."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from eagle.final_test.opponents import OpponentSetupError, prepare_opponents


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch pinned champion sources, rebuild JARs, and verify MicroRTS class loading."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPOSITORY_ROOT / "third_party" / "final_test_opponents" / "manifest.toml",
    )
    parser.add_argument(
        "--microrts-dir",
        type=Path,
        default=REPOSITORY_ROOT / "third_party" / "microrts",
    )
    args = parser.parse_args()
    try:
        resolved = prepare_opponents(
            manifest_path=args.manifest.resolve(),
            opponent_root=args.manifest.resolve().parent,
            microrts_dir=args.microrts_dir.resolve(),
        )
    except (OpponentSetupError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"resolved_manifest={resolved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
