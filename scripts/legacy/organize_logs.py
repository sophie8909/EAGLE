from __future__ import annotations

import re
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGS_ROOT = PROJECT_ROOT / "logs"
MICRORTS_LOGS_ROOT = LOGS_ROOT / "microrts"
EAGLE_LOGS_ROOT = LOGS_ROOT / "eagle"
LEGACY_EAGLE_LOGS_ROOT = PROJECT_ROOT / "eagle" / "logs"

# Example: run_2026-03-27_00-00-32.log
MICRORTS_LOG_PATTERN = re.compile(
    r"^(?:run|run_test|surrogate|surrogate_test)_(\d{4})-(\d{2})-(\d{2})_\d{2}-\d{2}-\d{2}\.log$"
)
RESPONSE_PATTERN = re.compile(r"^Response(\d{4})-(\d{2})-(\d{2})[_-].*")


def safe_move(source: Path, destination: Path) -> bool:
    """Move one file or directory unless the destination already exists."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        print(f"[SKIP] Target already exists: {destination.as_posix().encode('ascii', errors='backslashreplace').decode('ascii')}")
        return False

    shutil.move(str(source), str(destination))
    source_text = source.as_posix().encode("ascii", errors="backslashreplace").decode("ascii")
    destination_text = destination.as_posix().encode("ascii", errors="backslashreplace").decode("ascii")
    print(f"[MOVE] {source_text} -> {destination_text}")
    return True


def merge_directory_contents(source_dir: Path, destination_dir: Path) -> tuple[int, int]:
    """Move the children of one directory into another directory."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    moved_count = 0
    skipped_count = 0

    for item in source_dir.iterdir():
        destination = destination_dir / item.name
        if safe_move(item, destination):
            moved_count += 1
        else:
            skipped_count += 1

    try:
        source_dir.rmdir()
    except OSError:
        pass

    return moved_count, skipped_count


def remove_duplicate_source_dir_if_fully_copied(source_dir: Path, destination_dir: Path) -> bool:
    """Delete one source directory when every child already exists in the destination."""
    if not source_dir.exists() or not destination_dir.exists():
        return False
    source_children = sorted(child.name for child in source_dir.iterdir())
    destination_children = sorted(child.name for child in destination_dir.iterdir())
    if source_children != destination_children:
        return False
    shutil.rmtree(source_dir)
    source_text = source_dir.as_posix().encode("ascii", errors="backslashreplace").decode("ascii")
    print(f"[REMOVE DUPLICATE SOURCE] {source_text}")
    return True


def organize_root_microrts_logs(logs_root: Path = LOGS_ROOT) -> None:
    """Move loose MicroRTS runtime logs under logs/microrts/<MMDD>/."""
    logs_root.mkdir(parents=True, exist_ok=True)
    MICRORTS_LOGS_ROOT.mkdir(parents=True, exist_ok=True)
    moved_count = 0
    skipped_count = 0

    for item in logs_root.iterdir():
        if not item.is_file():
            continue
        match = MICRORTS_LOG_PATTERN.match(item.name)
        if not match:
            skipped_count += 1
            continue
        _, month, day = match.groups()
        destination = MICRORTS_LOGS_ROOT / f"{month}{day}" / item.name
        if safe_move(item, destination):
            moved_count += 1
        else:
            skipped_count += 1

    print(f"[ROOT MICRORTS LOGS] moved={moved_count}, skipped={skipped_count}")


def migrate_legacy_microrts_log_dirs(logs_root: Path = LOGS_ROOT) -> None:
    """Move legacy date folders from logs/ into logs/microrts/."""
    MICRORTS_LOGS_ROOT.mkdir(parents=True, exist_ok=True)
    moved_count = 0
    skipped_count = 0

    for item in logs_root.iterdir():
        if not item.is_dir():
            continue
        if item.name in {"eagle", "microrts"}:
            continue
        destination = MICRORTS_LOGS_ROOT / item.name
        if destination.exists() and destination.is_dir():
            moved, skipped = merge_directory_contents(item, destination)
            moved_count += moved
            skipped_count += skipped
            remove_duplicate_source_dir_if_fully_copied(item, destination)
            continue
        if safe_move(item, destination):
            moved_count += 1
        else:
            skipped_count += 1

    print(f"[LEGACY MICRORTS DIRS] moved={moved_count}, skipped={skipped_count}")


def migrate_legacy_eagle_logs(
    legacy_root: Path = LEGACY_EAGLE_LOGS_ROOT,
    eagle_root: Path = EAGLE_LOGS_ROOT,
) -> None:
    """Move legacy EAGLE log directories into top-level logs/eagle/."""
    if not legacy_root.exists():
        print(f"[WARN] Legacy EAGLE logs directory does not exist: {legacy_root}")
        return

    eagle_root.mkdir(parents=True, exist_ok=True)
    moved_count = 0
    skipped_count = 0

    for item in legacy_root.iterdir():
        destination = eagle_root / item.name
        if destination.exists() and destination.is_dir() and item.is_dir():
            moved, skipped = merge_directory_contents(item, destination)
            moved_count += moved
            skipped_count += skipped
            continue
        if safe_move(item, destination):
            moved_count += 1
        else:
            skipped_count += 1

    print(f"[LEGACY EAGLE LOGS] moved={moved_count}, skipped={skipped_count}")


def organize_responses(responses_dir: Path = PROJECT_ROOT / "responses") -> None:
    """Move response files into responses/<MMDD>/."""
    if not responses_dir.exists():
        print(f"[WARN] Responses directory does not exist: {responses_dir}")
        return

    moved_count = 0
    skipped_count = 0

    for item in responses_dir.iterdir():
        if not item.is_file():
            continue
        match = RESPONSE_PATTERN.match(item.name)
        if not match:
            skipped_count += 1
            continue
        _, month, day = match.groups()
        destination = responses_dir / f"{month}{day}" / item.name
        if safe_move(item, destination):
            moved_count += 1
        else:
            skipped_count += 1

    print(f"[RESPONSES] moved={moved_count}, skipped={skipped_count}")


def organize_root_responses(project_root: Path = PROJECT_ROOT) -> None:
    """Move loose root-level Response*. files into responses/<MMDD>/."""
    responses_root = project_root / "responses"
    responses_root.mkdir(parents=True, exist_ok=True)
    moved_count = 0
    skipped_count = 0

    for item in project_root.iterdir():
        if not item.is_file():
            continue
        match = RESPONSE_PATTERN.match(item.name)
        if not match:
            continue
        _, month, day = match.groups()
        destination = responses_root / f"{month}{day}" / item.name
        if safe_move(item, destination):
            moved_count += 1
        else:
            skipped_count += 1

    print(f"[ROOT RESPONSES] moved={moved_count}, skipped={skipped_count}")


def main() -> None:
    """Migrate legacy logs into the current top-level logs layout."""
    organize_root_microrts_logs()
    migrate_legacy_microrts_log_dirs()
    migrate_legacy_eagle_logs()
    organize_responses()
    organize_root_responses()
    print("[DONE] Log organization finished.")


if __name__ == "__main__":
    main()
