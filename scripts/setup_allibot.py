"""Fetch and locally build the pinned upstream AlliBot GUI dependency."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from allibot_llama_cpp_adapter import ADAPTER_VERSION, prepare as prepare_llama_cpp_sources


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_REPOSITORY = "https://github.com/drchangliu/MicroRTS.git"
PINNED_COMMIT = "ef99dcfe38ecc255928e336869ab95bf4992a931"
ENTRY_CLASS = "ai.abstraction.submissions.allibot.alli"
OPPONENT_ROOT = REPOSITORY_ROOT / "third_party" / "gui_opponents"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch pinned upstream MicroRTS, build AlliBot and its upstream classes for GUI use."
    )
    parser.add_argument("--root", type=Path, default=OPPONENT_ROOT)
    args = parser.parse_args(argv)
    try:
        resolved = setup_allibot(args.root.resolve())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"resolved_manifest={resolved}")
    return 0


def setup_allibot(root: Path) -> Path:
    for command in ("git", "javac", "javap"):
        if shutil.which(command) is None:
            raise RuntimeError(f"Required command is unavailable: {command}")
    source_dir = root / "src" / "allibot"
    adapted_source_dir = root / "build" / "allibot" / "source"
    classes_dir = root / "build" / "allibot" / "classes"
    jar_path = root / "jars" / "allibot.jar"
    _checkout_pinned_source(source_dir, UPSTREAM_REPOSITORY, PINNED_COMMIT)
    if not (source_dir / "src" / "ai" / "abstraction" / "submissions" / "allibot" / "alli.java").is_file():
        raise RuntimeError("Pinned upstream checkout does not contain the expected AlliBot source tree.")
    prepare_llama_cpp_sources(source_dir / "src", adapted_source_dir)
    source_files = tuple(sorted(adapted_source_dir.rglob("*.java")))
    if classes_dir.exists():
        shutil.rmtree(classes_dir)
    classes_dir.mkdir(parents=True)
    build = _compile_java_sources(
        source_files,
        cwd=adapted_source_dir,
        classpath=str(source_dir / "lib" / "*"),
        output_dir=classes_dir,
        flags=("-Xlint:all",),
    )
    if build.returncode != 0:
        raise RuntimeError("AlliBot upstream source build failed:\n" + (build.stderr or build.stdout).strip())
    _write_jar(classes_dir, jar_path)
    _verify_entrypoint(jar_path, source_dir)
    resolved = root / "resolved_allibot.json"
    _write_json_atomic(
        resolved,
        {
            "schema_version": "eagle-allibot-v2",
            "opponent_id": "allibot",
            "class_name": ENTRY_CLASS,
            "upstream_repository": UPSTREAM_REPOSITORY,
            "pinned_commit": PINNED_COMMIT,
            "jar_path": str(jar_path.relative_to(REPOSITORY_ROOT)),
            "jar_sha256": _sha256(jar_path),
            "source_sha256": _hash_sources(source_files, adapted_source_dir),
            "llm_backend": "llama.cpp OpenAI-compatible /v1/chat/completions",
            "llm_adapter_version": ADAPTER_VERSION,
            "license": "GPL-3.0-only; downloaded and built locally for GUI use, never committed or redistributed by EAGLE.",
        },
    )
    return resolved


def _checkout_pinned_source(source_dir: Path, repository: str, commit: str) -> None:
    newly_cloned = False
    if not source_dir.exists():
        source_dir.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--no-checkout", "--depth", "1", repository, str(source_dir)])
        newly_cloned = True
    if not (source_dir / ".git").is_dir():
        raise RuntimeError(f"Opponent source path is not a Git checkout: {source_dir}")
    if _run(["git", "-C", str(source_dir), "remote", "get-url", "origin"]).rstrip("/").removesuffix(".git") != repository.removesuffix(".git"):
        raise RuntimeError(f"Opponent checkout origin does not match {repository}: {source_dir}")
    dirty = _run(["git", "-C", str(source_dir), "status", "--porcelain"])
    unmaterialized = bool(dirty) and not any(path.name != ".git" for path in source_dir.iterdir())
    if dirty and not unmaterialized:
        raise RuntimeError(f"Opponent source checkout has local changes: {source_dir}")
    if newly_cloned or _run(["git", "-C", str(source_dir), "rev-parse", "HEAD"]) != commit:
        _run(["git", "-C", str(source_dir), "fetch", "--depth", "1", "origin", commit])
    checkout = ["git", "-C", str(source_dir), "checkout", "--detach"]
    if newly_cloned or unmaterialized:
        checkout.append("--force")
    checkout.append(commit)
    _run(checkout)
    if _run(["git", "-C", str(source_dir), "rev-parse", "HEAD"]) != commit:
        raise RuntimeError(f"Opponent checkout is not at {commit}: {source_dir}")


def _compile_java_sources(
    sources: tuple[Path, ...], *, cwd: Path, classpath: str, output_dir: Path,
    flags: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    # A source list can exceed the Windows command-line limit.
    with tempfile.TemporaryDirectory() as temporary:
        argfile = Path(temporary) / "sources.args"
        paths = [Path(os.path.relpath(source, cwd)).as_posix() for source in sources]
        argfile.write_text("".join(f'"{path}"\n' for path in paths), encoding="utf-8")
        return subprocess.run(
            ["javac", "-J-Dfile.encoding=UTF-8", "-encoding", "UTF-8", *flags,
             "-cp", classpath, "-d", str(output_dir), f"@{argfile}"],
            cwd=cwd, capture_output=True, text=True, check=False,
        )


def _verify_entrypoint(jar_path: Path, source_dir: Path) -> None:
    # MicroRTS has no stable --help contract. Loading the declared class through its
    # own runtime is a less ambiguous proof than attempting a display-dependent game.
    probe = subprocess.run(
        ["javap", "-classpath", os.pathsep.join((str(jar_path), str(source_dir / "lib" / "*"))), ENTRY_CLASS],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0 or ENTRY_CLASS not in probe.stdout:
        raise RuntimeError("AlliBot entry class is not loadable from the rebuilt JAR.")


def _write_jar(classes_dir: Path, jar_path: Path, *, created_by: str = "EAGLE AlliBot setup") -> None:
    jar_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = jar_path.with_suffix(".jar.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        manifest = zipfile.ZipInfo("META-INF/MANIFEST.MF", date_time=(1980, 1, 1, 0, 0, 0))
        manifest.external_attr = 0o644 << 16
        archive.writestr(manifest, f"Manifest-Version: 1.0\r\nCreated-By: {created_by}\r\n\r\n")
        for path in sorted(classes_dir.rglob("*.class")):
            info = zipfile.ZipInfo(path.relative_to(classes_dir).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    temporary.replace(jar_path)


def _run(command: list[str]) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError("Command failed: " + " ".join(command) + "\n" + (completed.stderr or completed.stdout).strip())
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_sources(paths: tuple[Path, ...], source_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(source_dir).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
