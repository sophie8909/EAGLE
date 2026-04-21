from __future__ import annotations

import argparse
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGS_ROOT = PROJECT_ROOT / "logs"
MICRORTS_LOGS_ROOT = LOGS_ROOT / "microrts"
EAGLE_LOGS_ROOT = LOGS_ROOT / "eagle"
TEXT_FILE_SUFFIXES = {".csv", ".json", ".jsonl", ".md", ".txt"}
MICRORTS_LOG_NAME_PATTERN = re.compile(
    r"^(?:SurrogateLog_|run_)?"
    r"(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})"
    r"(?:_(?P<kind>test_surrogate|test|surrogate))?"
    r"\.(?:log|txt)$"
)
MICRORTS_LOG_REFERENCE_PATTERN = re.compile(
    r"((?:SurrogateLog_|run_)?"
    r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}"
    r"(?:_(?:test_surrogate|test|surrogate))?"
    r"\.(?:log|txt))"
)


@dataclass(frozen=True)
class PlannedMove:
    source: Path
    destination: Path
    experiment_dir: Path | None


def windows_to_wsl(path: Path) -> str:
    """Convert one Windows absolute path into a WSL-compatible absolute path."""
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    tail = resolved.as_posix().split(":", 1)[-1].lstrip("/")
    return f"/mnt/{drive}/{tail}"


def iter_loose_microrts_logs(microrts_root: Path) -> list[Path]:
    """Return loose runtime logs that still live directly under logs/microrts/."""
    if not microrts_root.exists():
        return []
    return sorted(path for path in microrts_root.iterdir() if path.is_file())


def parse_log_date(file_name: str) -> str | None:
    """Extract the ISO date prefix from one runtime log filename."""
    match = MICRORTS_LOG_NAME_PATTERN.match(file_name)
    if not match:
        return None
    return str(match.group("date"))


def collect_experiment_log_references(eagle_root: Path) -> dict[str, set[Path]]:
    """Map one runtime log filename to the experiment directories that reference it."""
    references: dict[str, set[Path]] = defaultdict(set)
    if not eagle_root.exists():
        return references

    for experiment_dir in sorted(path for path in eagle_root.iterdir() if path.is_dir()):
        for file_path in experiment_dir.rglob("*"):
            if not file_path.is_file() or file_path.suffix.lower() not in TEXT_FILE_SUFFIXES:
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for match in MICRORTS_LOG_REFERENCE_PATTERN.finditer(content):
                references[match.group(1)].add(experiment_dir)

    return references


def build_move_plan(
    microrts_root: Path,
    eagle_root: Path,
) -> tuple[list[PlannedMove], list[Path]]:
    """Plan where each loose MicroRTS log should be moved."""
    experiment_references = collect_experiment_log_references(eagle_root)
    moves: list[PlannedMove] = []
    unmatched: list[Path] = []

    for source in iter_loose_microrts_logs(microrts_root):
        file_name = source.name
        experiment_dirs = experiment_references.get(file_name, set())
        if len(experiment_dirs) == 1:
            experiment_dir = next(iter(experiment_dirs))
            destination = experiment_dir / "microrts" / file_name
            moves.append(PlannedMove(source=source, destination=destination, experiment_dir=experiment_dir))
            continue

        log_date = parse_log_date(file_name)
        if log_date is not None:
            destination = microrts_root / log_date / file_name
            moves.append(PlannedMove(source=source, destination=destination, experiment_dir=None))
            continue

        unmatched.append(source)

    return moves, unmatched


def safe_move(source: Path, destination: Path, *, dry_run: bool) -> bool:
    """Move one file unless the destination already exists."""
    if destination.exists():
        print(f"[SKIP] destination exists: {destination}")
        return False

    print(f"[MOVE] {source} -> {destination}")
    if dry_run:
        return True

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return True


def replace_text_in_file(file_path: Path, replacements: dict[str, str], *, dry_run: bool) -> bool:
    """Rewrite one text file when at least one old path reference is present."""
    try:
        original = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False

    updated = original
    for old_text, new_text in replacements.items():
        updated = updated.replace(old_text, new_text)

    if updated == original:
        return False

    print(f"[REWRITE] {file_path}")
    if not dry_run:
        file_path.write_text(updated, encoding="utf-8")
    return True


def rewrite_experiment_references(
    experiment_dir: Path,
    source: Path,
    destination: Path,
    *,
    dry_run: bool,
) -> int:
    """Update text artifacts in one experiment directory after moving a runtime log."""
    source_windows = source.resolve().as_posix()
    source_wsl = windows_to_wsl(source)
    destination_windows = destination.resolve().as_posix()
    destination_wsl = windows_to_wsl(destination)
    replacements = {
        source_windows: destination_windows,
        source_wsl: destination_wsl,
        f"logs/microrts/{source.name}": str(destination.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    }

    rewritten_count = 0
    for file_path in experiment_dir.rglob("*"):
        if not file_path.is_file() or file_path.suffix.lower() not in TEXT_FILE_SUFFIXES:
            continue
        if replace_text_in_file(file_path, replacements, dry_run=dry_run):
            rewritten_count += 1
    return rewritten_count


def print_summary(moves: list[PlannedMove], unmatched: list[Path]) -> None:
    """Emit one compact dry-run/apply summary."""
    experiment_move_count = sum(1 for move in moves if move.experiment_dir is not None)
    date_bucket_count = sum(1 for move in moves if move.experiment_dir is None)
    print(
        "[SUMMARY] "
        f"planned_moves={len(moves)}, "
        f"experiment_moves={experiment_move_count}, "
        f"date_bucket_moves={date_bucket_count}, "
        f"unmatched={len(unmatched)}"
    )
    for path in unmatched:
        print(f"[UNMATCHED] {path}")


def main() -> None:
    """Organize loose MicroRTS runtime logs into experiment folders or date buckets."""
    parser = argparse.ArgumentParser(
        description=(
            "Move loose logs/microrts/run_*.log files into logs/eagle/<experiment>/microrts/ "
            "when they are referenced by one experiment, otherwise into logs/microrts/YYYY-MM-DD/."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually move files and rewrite references. Without this flag the script performs a dry run.",
    )
    args = parser.parse_args()

    dry_run = not args.apply
    moves, unmatched = build_move_plan(MICRORTS_LOGS_ROOT, EAGLE_LOGS_ROOT)
    print_summary(moves, unmatched)

    moved_count = 0
    rewritten_count = 0
    for move in moves:
        if not safe_move(move.source, move.destination, dry_run=dry_run):
            continue
        moved_count += 1
        if move.experiment_dir is not None:
            rewritten_count += rewrite_experiment_references(
                move.experiment_dir,
                move.source,
                move.destination,
                dry_run=dry_run,
            )

    mode = "DRY RUN" if dry_run else "APPLY"
    print(f"[DONE] {mode}: moved={moved_count}, rewritten_files={rewritten_count}, unmatched={len(unmatched)}")


if __name__ == "__main__":
    main()
