"""Replay one generated EAGLE candidate in a visible MicroRTS match."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eagle.config import ExperimentConfig
from evaluation.compiler import compile_generated_agent
from generation.backend import generated_class_name


DEFAULT_MAP = "maps/8x8/basesWorkers8x8.xml"
DEFAULT_OPPONENT = "ai.PassiveAI"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay an existing generated EAGLE candidate in the MicroRTS GUI.",
    )
    parser.add_argument("run_dir", help="Run directory, for example runs/20260708_123456_000000")
    parser.add_argument("candidate_id", help="Candidate id from a run artifact or generation population file")
    parser.add_argument("--map", default=None, help=f"MicroRTS map path. Default: {DEFAULT_MAP}")
    parser.add_argument(
        "--opponent",
        default=DEFAULT_OPPONENT,
        help=(
            "Player 1 opponent Java class name. Common choices: "
            "ai.RandomAI, ai.RandomBiasedAI, ai.abstraction.LightRush, ai.abstraction.HeavyRush. "
            f"Default: {DEFAULT_OPPONENT}"
        ),
    )
    parser.add_argument("--max-cycles", type=int, default=None, help="Maximum MicroRTS game cycles")
    parser.add_argument("--utt-version", type=int, default=1, help="UnitTypeTable version passed to MicroRTS")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"error: run directory does not exist: {run_dir}", file=sys.stderr)
        return 2

    config = load_run_config(run_dir)
    source_path = find_generated_agent_source(run_dir, args.candidate_id)
    if source_path is None:
        print(
            "error: generated candidate source not found. Looked under "
            f"{run_dir / 'generated_agents' / args.candidate_id} and "
            f"{run_dir / 'candidates' / args.candidate_id}.",
            file=sys.stderr,
        )
        return 2

    map_path = args.map or DEFAULT_MAP
    opponent = args.opponent
    max_cycles = args.max_cycles or (config.tick_limit if config is not None else 100)
    microrts_dir = config.microrts_dir if config is not None else Path("third_party/microrts")
    class_name = (
        generated_class_name(args.candidate_id)
        if source_path.name == "generated_java_source.java"
        else source_path.stem
    )
    agent_class = f"ai.generated.{class_name}"

    print(f"run_id={run_dir.name}")
    print(f"candidate_id={args.candidate_id}")
    print(f"generated_agent_path={source_path}")
    print(f"map={map_path}")
    print(f"player 0: generated candidate ({agent_class})")
    print(f"player 1: selected opponent ({opponent})")
    print(f"max_cycles={max_cycles}")

    # This script is for manual GUI inspection only. It reuses an existing generated
    # Java candidate as player 0 and launches MicroRTS without running EA/evaluation.
    # The --opponent option only replaces player 1; candidate side swapping is not supported here.
    with tempfile.TemporaryDirectory(prefix=f"eagle_gui_{args.candidate_id}_") as temp_dir:
        source_for_compile = source_path
        if source_path.name == "generated_java_source.java":
            source_for_compile = copy_artifact_source_for_compile(source_path, Path(temp_dir), class_name)

        classes_dir = Path(temp_dir) / "classes"
        compile_result = compile_generated_agent(
            source_for_compile,
            microrts_dir=microrts_dir,
            output_dir=classes_dir,
            mock=False,
        )
        if not compile_result.ok:
            print("error: generated candidate did not compile", file=sys.stderr)
            if compile_result.stderr:
                print(compile_result.stderr, file=sys.stderr)
            return compile_result.returncode or 1

        command = gui_match_command(
            microrts_dir=microrts_dir,
            classes_dir=classes_dir,
            agent_class=agent_class,
            opponent=opponent,
            map_path=map_path,
            max_cycles=max_cycles,
            utt_version=args.utt_version,
        )
        return subprocess.run(command, cwd=microrts_dir).returncode


def load_run_config(run_dir: Path) -> ExperimentConfig | None:
    config_path = run_dir / "config.yaml"
    if not config_path.exists():
        return None
    return ExperimentConfig.from_file(config_path)


def find_generated_agent_source(run_dir: Path, candidate_id: str) -> Path | None:
    generated_dir = run_dir / "generated_agents" / candidate_id
    if generated_dir.exists():
        expected = generated_dir / "src" / "ai" / "generated" / f"{generated_class_name(candidate_id)}.java"
        if expected.exists():
            return expected
        java_files = sorted(generated_dir.rglob("*.java"))
        if java_files:
            return java_files[0]

    artifact_source = run_dir / "candidates" / candidate_id / "generated_java_source.java"
    if artifact_source.exists():
        return artifact_source
    return None


def copy_artifact_source_for_compile(source_path: Path, temp_dir: Path, class_name: str) -> Path:
    source_dir = temp_dir / "src" / "ai" / "generated"
    source_dir.mkdir(parents=True, exist_ok=True)
    compile_source = source_dir / f"{class_name}.java"
    shutil.copy2(source_path, compile_source)
    return compile_source


def gui_match_command(
    *,
    microrts_dir: Path,
    classes_dir: Path,
    agent_class: str,
    opponent: str,
    map_path: str,
    max_cycles: int,
    utt_version: int,
) -> list[str]:
    return [
        "java",
        "-cp",
        os.pathsep.join(
            [
                str(classes_dir.resolve()),
                str(microrts_dir.resolve() / "bin"),
                str(microrts_dir.resolve() / "lib" / "*"),
            ]
        ),
        "rts.MicroRTS",
        "-l",
        "STANDALONE",
        "--headless",
        "false",
        "-m",
        map_path,
        "-c",
        str(max_cycles),
        "-i",
        "20",
        "-u",
        str(utt_version),
        "--ai1",
        agent_class,
        "--ai2",
        opponent,
    ]


if __name__ == "__main__":
    raise SystemExit(main())
