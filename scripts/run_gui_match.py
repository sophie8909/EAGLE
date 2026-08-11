"""Launch one visual MicroRTS match from a persisted EAGLE candidate.

This is an inspection utility, not an EA evaluation command: it does not write
fitness or mutate the selected run.  Candidate Java is compiled and integration
checked in a temporary directory, then MicroRTS starts in STANDALONE non-headless
mode.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from evaluation.compiler import compile_generated_agent
from evaluation.microrts_runner import integrate_microrts_agent
from eagle.opponents import (
    EVALUATION_ROSTER,
    EXTERNAL_OPPONENTS,
    GUI_ONLY_OPPONENTS,
    gui_opponent_by_id,
    rooted_jar_path,
)


JAVA_CLASS_NAME = "ai.generated.CandidateAgent"
_JAVA_CLASS_PATTERN = re.compile(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+")
ALLIBOT_RESOLVED_MANIFEST = REPOSITORY_ROOT / "third_party" / "gui_opponents" / "resolved_allibot.json"


class ResolvedOpponent:
    def __init__(
        self,
        class_name: str,
        *,
        classpath_before_runtime: tuple[Path, ...] = (),
        classpath_after_runtime: tuple[Path, ...] = (),
        environment: dict[str, str] | None = None,
    ) -> None:
        self.class_name = class_name
        self.classpath_before_runtime = classpath_before_runtime
        self.classpath_after_runtime = classpath_after_runtime
        self.environment = {} if environment is None else environment


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_dir = args.run_dir.expanduser().resolve()
        source = load_candidate_source(run_dir, args.candidate_id)
        microrts_dir = args.microrts_dir.expanduser().resolve()
        if not microrts_dir.is_dir():
            raise ValueError(f"MicroRTS directory does not exist: {microrts_dir}")
        opponent = resolve_opponent(
            args.opponent,
            enable_allibot_runtime_llm=args.allibot_runtime_llm,
            allibot_llama_cpp_url=args.allibot_llama_cpp_url,
            allibot_llama_cpp_model=args.allibot_llama_cpp_model,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="eagle-gui-match-") as temporary:
        workspace = Path(temporary)
        classes_dir = workspace / "classes"
        compile_source = workspace / "CandidateAgent.java"
        compile_source.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        compile_result = compile_generated_agent(
            compile_source,
            microrts_dir=microrts_dir,
            output_dir=classes_dir,
        )
        if not compile_result.ok:
            print("ERROR: selected candidate does not compile.", file=sys.stderr)
            print(compile_result.stderr or compile_result.stdout, file=sys.stderr)
            return 1

        integration = integrate_microrts_agent(
            microrts_dir=microrts_dir,
            classes_dir=classes_dir,
            agent_class=JAVA_CLASS_NAME,
            integration_artifacts_dir=workspace / "integration",
        )
        if not integration.ok:
            print("ERROR: selected candidate failed the MicroRTS integration check.", file=sys.stderr)
            for check in integration.checks:
                detail = f": {check.reason}" if check.reason else ""
                print(f"- {check.name}: {check.status}{detail}", file=sys.stderr)
            return 1

        command = build_command(
            classes_dir=classes_dir,
            microrts_dir=microrts_dir,
            opponent_class=opponent.class_name,
            classpath_before_runtime=opponent.classpath_before_runtime,
            classpath_after_runtime=opponent.classpath_after_runtime,
            map_path=args.map_path,
            cycles=args.cycles,
            interval_ms=args.interval_ms,
            candidate_player=args.candidate_player,
            workspace=workspace,
        )
        print(f"Candidate: {args.candidate_id}")
        print(f"Opponent: {args.opponent} ({opponent.class_name})")
        print(f"Side: player {args.candidate_player}")
        print("Starting MicroRTS GUI; close its window to return to the shell.")
        environment = dict(os.environ)
        environment.update(opponent.environment)
        return subprocess.run(command, cwd=microrts_dir, env=environment, check=False).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one visual MicroRTS game using a persisted EAGLE candidate. "
            "This command does not update the EAGLE run or its fitness."
        )
    )
    parser.add_argument("--run-dir", type=Path, required=True, help="runs/<run_id>")
    parser.add_argument("--candidate-id", required=True, help="candidate directory/ID within the run")
    parser.add_argument(
        "--opponent",
        default="light_rush",
        help=(
            "EAGLE opponent ID (default: light_rush) or a fully qualified Java class. "
            "Known IDs: "
            f"{', '.join(item.opponent_id for item in EVALUATION_ROSTER + EXTERNAL_OPPONENTS + GUI_ONLY_OPPONENTS)}"
        ),
    )
    parser.add_argument("--map-path", default="maps/8x8/basesWorkers8x8.xml")
    parser.add_argument("--cycles", type=positive_int, default=100)
    parser.add_argument(
        "--interval-ms",
        type=non_negative_int,
        default=20,
        help="GUI update interval in milliseconds (default: 20)",
    )
    parser.add_argument(
        "--candidate-player",
        type=int,
        choices=(0, 1),
        default=0,
        help="put CandidateAgent on player 0 or player 1 (default: 0)",
    )
    parser.add_argument(
        "--allibot-runtime-llm",
        action="store_true",
        help=(
            "Allow AlliBot to call the local llama.cpp runtime LLM. By default GUI "
            "matches disable those calls and use AlliBot's non-LLM fallback behavior."
        ),
    )
    parser.add_argument(
        "--allibot-llama-cpp-url",
        default=os.environ.get("LLAMA_CPP_BASE_URL", "http://127.0.0.1:8080"),
        help="llama.cpp OpenAI-compatible base URL for AlliBot (default: %(default)s)",
    )
    parser.add_argument(
        "--allibot-llama-cpp-model",
        default=os.environ.get("LLAMA_CPP_MODEL", "qwen3.5-9b"),
        help="model alias served by llama.cpp for AlliBot (default: %(default)s)",
    )
    parser.add_argument(
        "--microrts-dir",
        type=Path,
        default=REPOSITORY_ROOT / "third_party" / "microrts",
    )
    return parser


def load_candidate_source(run_dir: Path, candidate_id: str) -> Path:
    candidate_dir = run_dir / "candidates" / candidate_id
    individual_path = candidate_dir / "individual.json"
    source_path = candidate_dir / "generation" / "normalized_candidate.java"
    if not run_dir.is_dir():
        raise ValueError(f"Run directory does not exist: {run_dir}")
    if not individual_path.is_file() or not source_path.is_file():
        raise ValueError(
            "Candidate requires individual.json and generation/normalized_candidate.java: "
            f"{candidate_dir}"
        )
    record = json.loads(individual_path.read_text(encoding="utf-8"))
    recorded_id = str(record.get("candidate_id") or record.get("id") or "")
    if recorded_id != candidate_id:
        raise ValueError(
            f"Candidate artifact ID mismatch: requested {candidate_id!r}, found {recorded_id!r}."
        )
    source = source_path.read_text(encoding="utf-8")
    embedded_source = str(record.get("generated_java") or "")
    if embedded_source and embedded_source != source:
        raise ValueError("Candidate Java does not match individual.json; refusing ambiguous artifact.")
    return source_path


def resolve_opponent(
    value: str,
    *,
    enable_allibot_runtime_llm: bool = False,
    allibot_llama_cpp_url: str = "http://127.0.0.1:8080",
    allibot_llama_cpp_model: str = "qwen3.5-9b",
) -> ResolvedOpponent:
    try:
        spec = gui_opponent_by_id(value)
    except KeyError:
        if not _JAVA_CLASS_PATTERN.fullmatch(value):
            raise ValueError(
                "--opponent must be a known EAGLE opponent ID or a fully qualified Java class name."
            )
        return ResolvedOpponent(value)

    classpath: tuple[Path, ...] = ()
    if spec in EXTERNAL_OPPONENTS:
        jar_path = rooted_jar_path(REPOSITORY_ROOT, spec)
        if jar_path is None or not jar_path.is_file():
            raise ValueError(
                f"External opponent {spec.opponent_id!r} is unavailable: {jar_path}. "
                "Run scripts/setup_final_test_opponents.py first."
            )
        classpath = (jar_path,)
    if spec in GUI_ONLY_OPPONENTS:
        return resolve_allibot(
            spec,
            enable_runtime_llm=enable_allibot_runtime_llm,
            llama_cpp_url=allibot_llama_cpp_url,
            llama_cpp_model=allibot_llama_cpp_model,
        )
    return ResolvedOpponent(spec.class_name, classpath_after_runtime=classpath)


def resolve_allibot(
    spec,
    *,
    enable_runtime_llm: bool,
    llama_cpp_url: str,
    llama_cpp_model: str,
) -> ResolvedOpponent:
    jar_path = rooted_jar_path(REPOSITORY_ROOT, spec)
    if jar_path is None or not jar_path.is_file() or not ALLIBOT_RESOLVED_MANIFEST.is_file():
        raise ValueError(
            "AlliBot is unavailable. Run python scripts/setup_allibot.py first."
        )
    try:
        resolved = json.loads(ALLIBOT_RESOLVED_MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Cannot parse AlliBot setup manifest: {ALLIBOT_RESOLVED_MANIFEST}") from exc
    if (
        resolved.get("schema_version") != "eagle-allibot-v2"
        or resolved.get("class_name") != spec.class_name
        or resolved.get("jar_sha256") != hashlib.sha256(jar_path.read_bytes()).hexdigest()
    ):
        raise ValueError("AlliBot setup evidence is incomplete or does not match its JAR; rerun setup_allibot.py.")
    source_lib = REPOSITORY_ROOT / "third_party" / "gui_opponents" / "src" / "allibot" / "lib"
    libraries = tuple(sorted(path.resolve() for path in source_lib.glob("*.jar") if path.is_file()))
    if not libraries:
        raise ValueError("AlliBot upstream libraries are missing; rerun setup_allibot.py.")
    environment = {
        "ALLI_USE_SEARCH_LLM": "false",
        "ALLI_SMALLMAP_LLM_ADVISOR": "false",
    }
    if enable_runtime_llm:
        if not llama_cpp_url.strip() or not llama_cpp_model.strip():
            raise ValueError("AlliBot llama.cpp URL and model must both be non-empty.")
        environment = {
            "LLAMA_CPP_BASE_URL": llama_cpp_url.rstrip("/"),
            "LLAMA_CPP_MODEL": llama_cpp_model,
        }
    return ResolvedOpponent(
        spec.class_name,
        classpath_before_runtime=(jar_path, *libraries),
        environment=environment,
    )


def build_command(
    *,
    classes_dir: Path,
    microrts_dir: Path,
    opponent_class: str,
    classpath_before_runtime: tuple[Path, ...],
    classpath_after_runtime: tuple[Path, ...],
    map_path: str,
    cycles: int,
    interval_ms: int,
    candidate_player: int,
    workspace: Path,
) -> list[str]:
    classpath = os.pathsep.join(
        [
            *(str(path) for path in classpath_before_runtime),
            str(classes_dir),
            str(microrts_dir / "bin"),
            str(microrts_dir / "lib" / "*"),
            *(str(path) for path in classpath_after_runtime),
        ]
    )
    ai1, ai2 = (
        (JAVA_CLASS_NAME, opponent_class)
        if candidate_player == 0
        else (opponent_class, JAVA_CLASS_NAME)
    )
    return [
        "java",
        f"-Dmicrorts.trace.path={workspace / 'replay.xml'}",
        "-cp",
        classpath,
        "rts.MicroRTS",
        "-l",
        "STANDALONE",
        "--headless",
        "false",
        "-m",
        map_path,
        "-c",
        str(cycles),
        "-i",
        str(interval_ms),
        "--ai1",
        ai1,
        "--ai2",
        ai2,
        "--result-json",
        str(workspace / "result.json"),
    ]


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
