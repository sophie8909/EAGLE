"""Build the vendored MicroRTS runtime and the three pinned champion JARs."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from setup_allibot import (
    REPOSITORY_ROOT,
    _checkout_pinned_source,
    _compile_java_sources,
    _write_jar,
)


def main() -> int:
    microrts = REPOSITORY_ROOT / "third_party" / "microrts"
    root = REPOSITORY_ROOT / "third_party" / "final_test_opponents"
    try:
        manifest = tomllib.loads((root / "manifest.toml").read_text(encoding="utf-8"))
        runtime_source = microrts / "src"
        runtime_sources = tuple(sorted(
            path for path in runtime_source.rglob("*.java")
            if path.relative_to(runtime_source).parts[0] != "tests"
        ))
        runtime_libraries = os.pathsep.join(
            str(microrts / entry) for entry in ("lib/*", "lib/bots/*")
        )
        build_root = root / "build"
        build_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=build_root) as temp:
            build = Path(temp)
            runtime_classes = build / "microrts"
            _compile(
                runtime_sources,
                cwd=microrts, classpath=runtime_libraries, output=runtime_classes,
            )
            classpath = os.pathsep.join((str(runtime_classes), runtime_libraries))
            built_jars = []
            for opponent in manifest["opponents"]:
                opponent_id = opponent["id"]
                source_dir = root / "src" / opponent_id
                _checkout_pinned_source(
                    source_dir, opponent["upstream_repository"], opponent["pinned_commit"],
                )
                sources = {
                    path for pattern in opponent["source_globs"] for path in source_dir.glob(pattern)
                    if path.is_file()
                }
                if not sources:
                    raise RuntimeError(f"No pinned Java sources found for {opponent_id}.")
                sources.update(root / path for path in opponent.get("adapter_sources", ()))
                classes = build / opponent_id
                _compile(tuple(sorted(sources)), cwd=source_dir, classpath=classpath, output=classes)
                entrypoint = opponent["expected_class"].replace(".", "/") + ".class"
                if not (classes / entrypoint).is_file():
                    raise RuntimeError(f"{opponent_id} did not build {entrypoint}.")
                destination = REPOSITORY_ROOT / opponent["jar_path"]
                staged_jar = build / destination.name
                _write_jar(classes, staged_jar, created_by="EAGLE pinned opponent setup")
                built_jars.append((staged_jar, destination))

            shutil.copytree(runtime_classes, microrts / "bin", dirs_exist_ok=True)
            for source, destination in built_jars:
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.replace(destination)
                print(f"Built {destination.relative_to(REPOSITORY_ROOT)}")
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def _compile(sources: tuple[Path, ...], *, cwd: Path, classpath: str, output: Path) -> None:
    output.mkdir()
    result = _compile_java_sources(sources, cwd=cwd, classpath=classpath, output_dir=output)
    if result.returncode:
        raise RuntimeError(f"Java build failed in {cwd}:\n{result.stderr or result.stdout}")


if __name__ == "__main__":
    raise SystemExit(main())
