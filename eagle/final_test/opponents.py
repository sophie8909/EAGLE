"""Pinned external-opponent manifests, source builds, and class-load checks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib  # type: ignore[no-redef]


PINNED_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")

OPPONENT_PROBE_SOURCE = r"""
import ai.core.AI;
import rts.units.UnitTypeTable;
import java.lang.reflect.Modifier;

public final class EAGLEOpponentProbe {
    private static String describe(Throwable error) {
        Throwable current = error;
        while (current.getCause() != null) current = current.getCause();
        String message = current.getMessage();
        return current.getClass().getSimpleName() + (message == null ? "" : ": " + message);
    }

    public static void main(String[] args) {
        for (String className : args) {
            try {
                Class<?> candidate = Class.forName(className);
                if (!AI.class.isAssignableFrom(candidate) || Modifier.isAbstract(candidate.getModifiers())) {
                    System.out.println("PROBE\t" + className + "\trejected\tnot a concrete MicroRTS AI");
                    continue;
                }
                candidate.getConstructor(UnitTypeTable.class).newInstance(new UnitTypeTable());
                System.out.println("PROBE\t" + className + "\taccepted\t");
            } catch (Throwable error) {
                System.out.println("PROBE\t" + className + "\trejected\t" + describe(error));
            }
        }
    }
}
"""


@dataclass(frozen=True)
class OpponentSpec:
    opponent_id: str
    display_name: str
    competition_year: int
    upstream_repository: str
    pinned_commit: str
    expected_class: str
    build_method: str
    jar_path: str
    source_globs: tuple[str, ...]
    required_classpath_entries: tuple[str, ...]
    adapter_sources: tuple[str, ...]
    license_status: str
    provided_jar: str | None = None


@dataclass(frozen=True)
class ResolvedOpponent:
    opponent_id: str
    display_name: str
    competition_year: int
    upstream_repository: str
    pinned_commit: str
    class_name: str
    build_method: str
    jar_path: str
    required_classpath_entries: tuple[str, ...]
    jar_sha256: str
    source_sha256: str
    detected_ai_classes: tuple[str, ...]
    class_load_verified: bool
    license_status: str
    detected_license_files: tuple[str, ...]
    provided_jar_path: str | None = None
    adapter_sources: tuple[str, ...] = ()
    adapter_source_sha256: str | None = None
    provided_jar_sha256: str | None = None
    provided_jar_contains_classes: bool | None = None

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_classpath_entries"] = list(self.required_classpath_entries)
        payload["detected_ai_classes"] = list(self.detected_ai_classes)
        payload["detected_license_files"] = list(self.detected_license_files)
        payload["adapter_sources"] = list(self.adapter_sources)
        return payload


class OpponentSetupError(RuntimeError):
    """A pinned champion could not be prepared reproducibly."""


def load_opponent_manifest(path: Path) -> tuple[OpponentSpec, ...]:
    """Load and validate the committed opponent manifest."""

    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    if payload.get("schema_version") != "eagle-final-test-opponents-v1":
        raise ValueError("Unsupported opponent manifest schema_version.")
    raw_opponents = payload.get("opponents")
    if not isinstance(raw_opponents, list) or not raw_opponents:
        raise ValueError("Opponent manifest must contain [[opponents]] entries.")
    specs: list[OpponentSpec] = []
    for item in raw_opponents:
        if not isinstance(item, dict):
            raise ValueError("Each opponent manifest entry must be a mapping.")
        spec = OpponentSpec(
            opponent_id=str(item["id"]),
            display_name=str(item["display_name"]),
            competition_year=int(item["competition_year"]),
            upstream_repository=str(item["upstream_repository"]),
            pinned_commit=str(item["pinned_commit"]).lower(),
            expected_class=str(item["expected_class"]),
            build_method=str(item["build_method"]),
            jar_path=str(item["jar_path"]),
            source_globs=tuple(str(value) for value in item.get("source_globs", ())),
            required_classpath_entries=tuple(
                str(value) for value in item.get("required_classpath_entries", ())
            ),
            adapter_sources=tuple(str(value) for value in item.get("adapter_sources", ())),
            license_status=str(item["license_status"]),
            provided_jar=str(item["provided_jar"]) if item.get("provided_jar") else None,
        )
        _validate_spec(spec)
        specs.append(spec)
    ids = [item.opponent_id for item in specs]
    if len(ids) != len(set(ids)):
        raise ValueError("Opponent IDs must be unique.")
    if set(ids) != {"tma", "mayari", "coac"}:
        raise ValueError("Opponent manifest must contain exactly tma, mayari, and coac.")
    return tuple(specs)


def load_resolved_opponents(
    path: Path,
    *,
    expected_ids: Iterable[str] = ("tma", "mayari", "coac"),
) -> dict[str, ResolvedOpponent]:
    """Read a successful setup result and reject incomplete or unpinned data."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OpponentSetupError(
            f"Cannot read resolved opponent manifest {path}; run "
            "python3 scripts/setup_final_test_opponents.py first."
        ) from exc
    if payload.get("schema_version") != "eagle-final-test-opponents-resolved-v1":
        raise OpponentSetupError(f"Unsupported resolved opponent manifest: {path}")
    resolved: dict[str, ResolvedOpponent] = {}
    for item in payload.get("opponents", []):
        opponent = ResolvedOpponent(
            opponent_id=str(item["opponent_id"]),
            display_name=str(item["display_name"]),
            competition_year=int(item["competition_year"]),
            upstream_repository=str(item["upstream_repository"]),
            pinned_commit=str(item["pinned_commit"]),
            class_name=str(item["class_name"]),
            build_method=str(item["build_method"]),
            jar_path=str(item["jar_path"]),
            required_classpath_entries=tuple(item.get("required_classpath_entries", ())),
            jar_sha256=str(item["jar_sha256"]),
            source_sha256=str(item["source_sha256"]),
            detected_ai_classes=tuple(item.get("detected_ai_classes", ())),
            class_load_verified=bool(item.get("class_load_verified")),
            license_status=str(item["license_status"]),
            detected_license_files=tuple(item.get("detected_license_files", ())),
            provided_jar_path=item.get("provided_jar_path"),
            adapter_sources=tuple(item.get("adapter_sources", ())),
            adapter_source_sha256=item.get("adapter_source_sha256"),
            provided_jar_sha256=item.get("provided_jar_sha256"),
            provided_jar_contains_classes=item.get("provided_jar_contains_classes"),
        )
        if not PINNED_COMMIT_PATTERN.fullmatch(opponent.pinned_commit):
            raise OpponentSetupError(f"Opponent {opponent.opponent_id} is not pinned to a full commit SHA.")
        if not opponent.class_load_verified:
            raise OpponentSetupError(f"Opponent {opponent.opponent_id} has no successful class-load proof.")
        resolved[opponent.opponent_id] = opponent
    expected = set(expected_ids)
    missing = expected - set(resolved)
    extra = set(resolved) - expected
    if missing or extra:
        raise OpponentSetupError(
            f"Resolved opponents do not match configuration; missing={sorted(missing)} extra={sorted(extra)}"
        )
    return resolved


def prepare_opponents(
    *,
    manifest_path: Path,
    opponent_root: Path,
    microrts_dir: Path,
) -> Path:
    """Fetch, source-build, probe, and atomically resolve all champions."""

    specs = load_opponent_manifest(manifest_path)
    _require_tool("git")
    _require_tool("javac")
    _require_tool("java")
    opponent_root = opponent_root.resolve()
    microrts_dir = microrts_dir.resolve()
    if not (microrts_dir / "bin").is_dir():
        raise OpponentSetupError(
            f"Vendored MicroRTS classes are missing at {microrts_dir / 'bin'}; build only that vendored runtime first."
        )
    (opponent_root / "src").mkdir(parents=True, exist_ok=True)
    (opponent_root / "jars").mkdir(parents=True, exist_ok=True)
    (opponent_root / "build").mkdir(parents=True, exist_ok=True)
    probe_classes = _compile_probe(opponent_root / "build" / "class_probe", microrts_dir)
    resolved = [
        _prepare_one(spec, opponent_root=opponent_root, microrts_dir=microrts_dir, probe_classes=probe_classes)
        for spec in specs
    ]
    output_path = opponent_root / "resolved_manifest.json"
    _write_json_atomic(
        output_path,
        {
            "schema_version": "eagle-final-test-opponents-resolved-v1",
            "source_manifest": str(manifest_path.resolve()),
            "microrts_dir": str(microrts_dir),
            "opponents": [item.to_json_dict() for item in resolved],
        },
    )
    return output_path


def verify_resolved_opponent(
    opponent: ResolvedOpponent,
    *,
    repository_root: Path,
    microrts_dir: Path,
    probe_classes: Path,
) -> None:
    """Recheck a resolved JAR hash and entrypoint before formal matches."""

    jar_path = (repository_root / opponent.jar_path).resolve()
    if not jar_path.is_file():
        raise OpponentSetupError(f"Opponent JAR is missing: {jar_path}")
    actual_hash = _sha256_file(jar_path)
    if actual_hash != opponent.jar_sha256:
        raise OpponentSetupError(
            f"Opponent JAR hash mismatch for {opponent.opponent_id}: expected {opponent.jar_sha256}, got {actual_hash}"
        )
    accepted = _probe_classes(
        jar_path=jar_path,
        class_names=(opponent.class_name,),
        microrts_dir=microrts_dir,
        probe_classes=probe_classes,
    )
    if accepted != (opponent.class_name,):
        raise OpponentSetupError(
            f"Opponent class {opponent.class_name} cannot be loaded from {jar_path}."
        )


def compile_opponent_probe(output_dir: Path, microrts_dir: Path) -> Path:
    """Compile the reusable class-load probe for a final-test execution."""

    return _compile_probe(output_dir, microrts_dir)


def _validate_spec(spec: OpponentSpec) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", spec.opponent_id):
        raise ValueError(f"Invalid opponent ID: {spec.opponent_id}")
    if not PINNED_COMMIT_PATTERN.fullmatch(spec.pinned_commit):
        raise ValueError(f"Opponent {spec.opponent_id} must use a full 40-character commit SHA.")
    if spec.build_method != "javac-source":
        raise ValueError(f"Unsupported build method for {spec.opponent_id}: {spec.build_method}")
    if not spec.source_globs:
        raise ValueError(f"Opponent {spec.opponent_id} has no source globs.")
    for value in spec.adapter_sources:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Opponent {spec.opponent_id} has an unsafe adapter source path: {value}")


def _prepare_one(
    spec: OpponentSpec,
    *,
    opponent_root: Path,
    microrts_dir: Path,
    probe_classes: Path,
) -> ResolvedOpponent:
    source_dir = opponent_root / "src" / spec.opponent_id
    _ensure_checkout(spec, source_dir)
    java_sources = _source_files(source_dir, spec.source_globs)
    if not java_sources:
        raise OpponentSetupError(f"No Java sources matched for {spec.opponent_id}.")
    adapter_sources = tuple((opponent_root / value).resolve() for value in spec.adapter_sources)
    for path in adapter_sources:
        if opponent_root not in path.parents:
            raise OpponentSetupError(
                f"Adapter source path escapes the dedicated opponent area: {path}"
            )
        if not path.is_file():
            raise OpponentSetupError(
                f"Configured adapter source is missing for {spec.opponent_id}: {path}"
            )
    compile_sources = (*java_sources, *adapter_sources)
    classes_dir = opponent_root / "build" / spec.opponent_id / "classes"
    _reset_generated_directory(classes_dir, opponent_root / "build")
    command = [
        "javac",
        "-Xlint:all",
        "-cp",
        _runtime_classpath(microrts_dir),
        "-d",
        str(classes_dir),
        *(str(path) for path in compile_sources),
    ]
    completed = subprocess.run(command, cwd=source_dir, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        diagnostic = (completed.stderr or completed.stdout).strip()
        raise OpponentSetupError(
            f"Failed to compile {spec.opponent_id} from pinned source. Command: {' '.join(command)}\n{diagnostic}"
        )
    jar_path = (opponent_root.parents[1] / spec.jar_path).resolve()
    if opponent_root not in jar_path.parents:
        raise OpponentSetupError(f"Opponent JAR path escapes the dedicated opponent area: {jar_path}")
    _build_deterministic_jar(classes_dir, jar_path)
    candidates = _jar_class_names(jar_path)
    detected = _probe_classes(
        jar_path=jar_path,
        class_names=candidates,
        microrts_dir=microrts_dir,
        probe_classes=probe_classes,
    )
    if spec.expected_class not in detected:
        raise OpponentSetupError(
            f"Expected upstream entrypoint {spec.expected_class} was not a loadable concrete MicroRTS AI; "
            f"detected={list(detected)}"
        )
    provided_path = source_dir / spec.provided_jar if spec.provided_jar else None
    provided_hash = _sha256_file(provided_path) if provided_path and provided_path.is_file() else None
    provided_contains_classes = (
        bool(_jar_class_names(provided_path)) if provided_path and provided_path.is_file() else None
    )
    license_files = tuple(
        sorted(
            {
                path.relative_to(source_dir).as_posix()
                for pattern in ("LICENSE*", "COPYING*", "NOTICE*")
                for path in source_dir.rglob(pattern)
                if path.is_file() and ".git" not in path.parts
            }
        )
    )
    return ResolvedOpponent(
        opponent_id=spec.opponent_id,
        display_name=spec.display_name,
        competition_year=spec.competition_year,
        upstream_repository=spec.upstream_repository,
        pinned_commit=spec.pinned_commit,
        class_name=spec.expected_class,
        build_method="source_rebuild_with_javac",
        jar_path=spec.jar_path,
        required_classpath_entries=spec.required_classpath_entries,
        jar_sha256=_sha256_file(jar_path),
        source_sha256=_hash_sources(source_dir, java_sources),
        detected_ai_classes=detected,
        adapter_sources=spec.adapter_sources,
        adapter_source_sha256=_hash_sources(opponent_root, adapter_sources) if adapter_sources else None,
        class_load_verified=True,
        license_status=spec.license_status,
        detected_license_files=license_files,
        provided_jar_path=spec.provided_jar,
        provided_jar_sha256=provided_hash,
        provided_jar_contains_classes=provided_contains_classes,
    )


def _ensure_checkout(spec: OpponentSpec, source_dir: Path) -> None:
    newly_cloned = False
    if not source_dir.exists():
        source_dir.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            ["git", "clone", "--no-checkout", spec.upstream_repository, str(source_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise OpponentSetupError(
                f"Cannot clone {spec.opponent_id} from {spec.upstream_repository}: "
                f"{(completed.stderr or completed.stdout).strip()}"
            )
        newly_cloned = True
    if not (source_dir / ".git").exists():
        raise OpponentSetupError(f"Existing source directory is not a Git checkout: {source_dir}")
    dirty = _git(source_dir, "status", "--porcelain")
    unmaterialized = bool(dirty) and not any(
        path.name != ".git" for path in source_dir.iterdir()
    )
    if dirty and not unmaterialized:
        raise OpponentSetupError(
            f"Opponent checkout has local changes and will not be modified: {source_dir}"
        )
    remote = _git(source_dir, "remote", "get-url", "origin")
    if _normalize_git_url(remote) != _normalize_git_url(spec.upstream_repository):
        raise OpponentSetupError(
            f"Opponent checkout origin mismatch for {spec.opponent_id}: {remote}"
        )
    present = subprocess.run(
        ["git", "-C", str(source_dir), "cat-file", "-e", f"{spec.pinned_commit}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if present.returncode != 0:
        fetched = subprocess.run(
            ["git", "-C", str(source_dir), "fetch", "--depth", "1", "origin", spec.pinned_commit],
            capture_output=True,
            text=True,
            check=False,
        )
        if fetched.returncode != 0:
            raise OpponentSetupError(
                f"Cannot fetch pinned commit {spec.pinned_commit} for {spec.opponent_id}: "
                f"{(fetched.stderr or fetched.stdout).strip()}"
            )
    if newly_cloned or unmaterialized or _git(source_dir, "rev-parse", "HEAD") != spec.pinned_commit:
        checkout_args = ["git", "-C", str(source_dir), "checkout", "--detach"]
        if newly_cloned or unmaterialized:
            checkout_args.append("--force")
        checkout_args.append(spec.pinned_commit)
        checkout = subprocess.run(
            checkout_args,
            capture_output=True,
            text=True,
            check=False,
        )
        if checkout.returncode != 0:
            raise OpponentSetupError(
                f"Cannot checkout pinned commit for {spec.opponent_id}: "
                f"{(checkout.stderr or checkout.stdout).strip()}"
            )
    if _git(source_dir, "rev-parse", "HEAD") != spec.pinned_commit:
        raise OpponentSetupError(f"Pinned revision enforcement failed for {spec.opponent_id}.")


def _source_files(source_dir: Path, patterns: Iterable[str]) -> tuple[Path, ...]:
    return tuple(
        sorted({path.resolve() for pattern in patterns for path in source_dir.glob(pattern) if path.is_file()})
    )


def _compile_probe(output_dir: Path, microrts_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_path = output_dir / "EAGLEOpponentProbe.java"
    source_path.write_text(OPPONENT_PROBE_SOURCE, encoding="utf-8")
    command = [
        "javac",
        "-cp",
        _runtime_classpath(microrts_dir),
        "-d",
        str(output_dir),
        str(source_path),
    ]
    completed = subprocess.run(command, cwd=microrts_dir, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise OpponentSetupError(
            "Cannot compile champion class-load probe against vendored MicroRTS: "
            + (completed.stderr or completed.stdout).strip()
        )
    return output_dir


def _probe_classes(
    *,
    jar_path: Path,
    class_names: Iterable[str],
    microrts_dir: Path,
    probe_classes: Path,
) -> tuple[str, ...]:
    names = tuple(class_names)
    if not names:
        return ()
    command = [
        "java",
        "-cp",
        os.pathsep.join([str(probe_classes), str(jar_path), _runtime_classpath(microrts_dir)]),
        "EAGLEOpponentProbe",
        *names,
    ]
    completed = subprocess.run(
        command,
        cwd=microrts_dir,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise OpponentSetupError(
            f"Champion class-load probe failed for {jar_path}: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    accepted = []
    for line in completed.stdout.splitlines():
        parts = line.split("\t", 3)
        if len(parts) >= 3 and parts[0] == "PROBE" and parts[2] == "accepted":
            accepted.append(parts[1])
    return tuple(sorted(accepted))


def _build_deterministic_jar(classes_dir: Path, jar_path: Path) -> None:
    jar_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = jar_path.with_suffix(".jar.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        manifest = zipfile.ZipInfo("META-INF/MANIFEST.MF", date_time=(1980, 1, 1, 0, 0, 0))
        manifest.external_attr = 0o644 << 16
        archive.writestr(manifest, "Manifest-Version: 1.0\r\nCreated-By: EAGLE opponent setup\r\n\r\n")
        for path in sorted(item for item in classes_dir.rglob("*.class") if item.is_file()):
            info = zipfile.ZipInfo(
                path.relative_to(classes_dir).as_posix(),
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    temporary.replace(jar_path)


def _jar_class_names(path: Path) -> tuple[str, ...]:
    try:
        with zipfile.ZipFile(path) as archive:
            return tuple(
                sorted(
                    name[:-6].replace("/", ".")
                    for name in archive.namelist()
                    if name.endswith(".class")
                    and "$" not in name
                    and not name.startswith("META-INF/")
                    and name != "module-info.class"
                )
            )
    except (OSError, zipfile.BadZipFile):
        return ()


def _runtime_classpath(microrts_dir: Path) -> str:
    return os.pathsep.join([str(microrts_dir / "bin"), str(microrts_dir / "lib" / "*")])


def _hash_sources(source_dir: Path, sources: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sources:
        digest.update(path.relative_to(source_dir).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(source_dir: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(source_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise OpponentSetupError(
            f"Git command failed in {source_dir}: git {' '.join(args)}\n"
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    return completed.stdout.strip()


def _normalize_git_url(value: str) -> str:
    return value.rstrip("/").removesuffix(".git").lower()


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise OpponentSetupError(
            f"Required tool '{name}' is not available. Run opponent setup in the EAGLE WSL/JDK environment."
        )


def _reset_generated_directory(path: Path, allowed_root: Path) -> None:
    path = path.resolve()
    allowed_root = allowed_root.resolve()
    if allowed_root not in path.parents:
        raise OpponentSetupError(f"Refusing to reset generated directory outside {allowed_root}: {path}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def _write_json_atomic(path: Path, payload: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
