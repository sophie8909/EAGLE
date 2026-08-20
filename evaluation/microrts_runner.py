"""Standalone MicroRTS candidate-integration probe."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_MAP_PATH = "maps/8x8/basesWorkers8x8.xml"

INTEGRATION_CHECK_NAMES = (
    "class_loading",
    "ai_inheritance",
    "constructors",
    "reset",
    "clone",
    "get_action",
    "player_action",
)

INTEGRATION_PROBE_SOURCE = r"""
import ai.abstraction.AbstractionLayerAI;
import ai.abstraction.pathfinding.AStarPathFinding;
import ai.core.AI;
import rts.GameState;
import rts.PhysicalGameState;
import rts.Player;
import rts.PlayerAction;
import rts.units.UnitTypeTable;
import java.lang.reflect.Constructor;

public final class EAGLEIntegrationProbe {
    private static void check(String name, String status, String reason) {
        System.out.println("CHECK\t" + name + "\t" + status + "\t" + (reason == null ? "" : reason));
    }

    private static void blocked(String name, String reason) {
        check(name, "blocked", reason);
    }

    private static String describe(Throwable error) {
        Throwable current = error;
        while (current.getCause() != null) {
            current = current.getCause();
        }
        String message = current.getMessage();
        return current.getClass().getSimpleName() + (message == null ? "" : ": " + message);
    }

    private static void blockAfter(String failedName, String reason) {
        boolean after = false;
        for (String name : new String[] {
            "class_loading", "ai_inheritance", "constructors", "reset",
            "clone", "get_action", "player_action"
        }) {
            if (name.equals(failedName)) {
                after = true;
                continue;
            }
            if (after) {
                blocked(name, reason);
            }
        }
    }

    public static void main(String[] args) {
        String className = args[0];
        Class<?> candidateClass;
        try {
            candidateClass = Class.forName(className);
            check("class_loading", "passed", "");
        } catch (Throwable error) {
            check("class_loading", "failed", describe(error));
            blockAfter("class_loading", "class loading failed");
            return;
        }

        if (!AI.class.isAssignableFrom(candidateClass)
                || !AbstractionLayerAI.class.isAssignableFrom(candidateClass)) {
            check("ai_inheritance", "failed", "candidate is not an AI extending AbstractionLayerAI");
            blockAfter("ai_inheritance", "inheritance check failed");
            return;
        }
        check("ai_inheritance", "passed", "");

        AI candidate;
        try {
            Constructor<?> one = candidateClass.getConstructor(UnitTypeTable.class);
            Constructor<?> two = candidateClass.getConstructor(UnitTypeTable.class, AStarPathFinding.class);
            UnitTypeTable utt = new UnitTypeTable();
            candidate = (AI) one.newInstance(utt);
            two.newInstance(utt, new AStarPathFinding());
            check("constructors", "passed", "");
        } catch (Throwable error) {
            check("constructors", "failed", describe(error));
            blockAfter("constructors", "constructor check failed");
            return;
        }

        try {
            candidate.reset();
            check("reset", "passed", "");
        } catch (Throwable error) {
            check("reset", "failed", describe(error));
            blockAfter("reset", "reset failed");
            return;
        }

        try {
            AI cloned = candidate.clone();
            if (cloned == null) {
                check("clone", "failed", "clone returned null");
                blockAfter("clone", "clone failed");
                return;
            }
            check("clone", "passed", "");
        } catch (Throwable error) {
            check("clone", "failed", describe(error));
            blockAfter("clone", "clone failed");
            return;
        }

        PlayerAction action;
        try {
            PhysicalGameState physical = new PhysicalGameState(8, 8);
            physical.addPlayer(new Player(0, 10));
            physical.addPlayer(new Player(1, 10));
            GameState state = new GameState(physical, new UnitTypeTable());
            action = candidate.getAction(0, state);
            check("get_action", "passed", "");
        } catch (Throwable error) {
            check("get_action", "failed", describe(error));
            blockAfter("get_action", "getAction failed");
            return;
        }

        if (action == null || action.getResourceUsage() == null) {
            check("player_action", "failed", "getAction returned an invalid PlayerAction");
            return;
        }
        check("player_action", "passed", "");
    }
}
"""


@dataclass(frozen=True)
class IntegrationCheck:
    name: str
    status: str
    reason: str = ""

    def to_json_dict(self) -> dict[str, str]:
        return {"check": self.name, "status": self.status, "reason": self.reason}


@dataclass(frozen=True)
class IntegrationResult:
    status: str
    checks: tuple[IntegrationCheck, ...]
    integration_pass_ratio: float
    commands: tuple[tuple[str, ...], ...] = ()
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    failure_stage: str | None = None
    failure_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "success"

    def to_json_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "ordered_checks": [check.to_json_dict() for check in self.checks],
            "integration_pass_ratio": self.integration_pass_ratio,
            "commands": [list(command) for command in self.commands],
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "timing": {
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "duration_seconds": self.duration_seconds,
            },
            "failure_stage": self.failure_stage,
            "failure_reason": self.failure_reason,
        }


def integrate_microrts_agent(
    *,
    microrts_dir: Path,
    classes_dir: Path,
    agent_class: str,
    integration_artifacts_dir: Path | None = None,
    mock: bool = False,
) -> IntegrationResult:
    started_at = _utc_now()
    started = time.monotonic()
    artifact_dir = None if integration_artifacts_dir is None else integration_artifacts_dir.resolve()
    if artifact_dir is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "request.txt").write_text(
            json.dumps(
                {
                    "agent_class": agent_class,
                    "classes_dir": str(classes_dir.resolve()),
                    "microrts_dir": str(microrts_dir.resolve()),
                    "check_order": list(INTEGRATION_CHECK_NAMES),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    if mock:
        checks = tuple(IntegrationCheck(name, "passed") for name in INTEGRATION_CHECK_NAMES)
        result = _integration_result(
            checks,
            commands=(),
            stdout="mock integration passed",
            stderr="",
            started_at=started_at,
            started=started,
        )
        _persist_integration_artifacts(artifact_dir, result)
        return result

    microrts_dir = microrts_dir.resolve()
    classes_dir = classes_dir.resolve()
    if artifact_dir is None:
        artifact_dir = classes_dir.parent / "integration"
        artifact_dir.mkdir(parents=True, exist_ok=True)
    probe_source = artifact_dir / "EAGLEIntegrationProbe.java"
    probe_source.write_text(INTEGRATION_PROBE_SOURCE, encoding="utf-8")
    classpath = os.pathsep.join(
        [str(classes_dir), str(microrts_dir / "bin"), str(microrts_dir / "lib" / "*")]
    )
    compile_command = ["javac", "-cp", classpath, "-d", str(artifact_dir), str(probe_source)]
    run_command = ["java", "-cp", os.pathsep.join([classpath, str(artifact_dir)]), "EAGLEIntegrationProbe", agent_class]
    commands = (tuple(compile_command), tuple(run_command))

    try:
        compiled = subprocess.run(
            compile_command,
            cwd=microrts_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        result = _integration_result(
            _failed_checks("integration probe compilation timed out"),
            commands=commands,
            stdout=_text_output(exc.stdout),
            stderr=_text_output(exc.stderr),
            returncode=124,
            started_at=started_at,
            started=started,
        )
        _persist_integration_artifacts(artifact_dir, result)
        return result
    if compiled.returncode != 0:
        reason = (compiled.stderr or compiled.stdout or "integration probe compilation failed").strip()
        result = _integration_result(
            _failed_checks(reason),
            commands=commands,
            stdout=compiled.stdout,
            stderr=compiled.stderr,
            returncode=compiled.returncode,
            started_at=started_at,
            started=started,
        )
        _persist_integration_artifacts(artifact_dir, result)
        return result

    try:
        executed = subprocess.run(
            run_command,
            cwd=microrts_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        checks = parse_integration_checks(executed.stdout, executed.stderr)
        result = _integration_result(
            checks,
            commands=commands,
            stdout=executed.stdout,
            stderr=executed.stderr,
            returncode=executed.returncode,
            started_at=started_at,
            started=started,
        )
    except subprocess.TimeoutExpired as exc:
        result = _integration_result(
            _failed_checks("integration probe timed out"),
            commands=commands,
            stdout=_text_output(exc.stdout),
            stderr=_text_output(exc.stderr),
            returncode=124,
            started_at=started_at,
            started=started,
        )
    _persist_integration_artifacts(artifact_dir, result)
    return result


def parse_integration_checks(stdout: str, stderr: str = "") -> tuple[IntegrationCheck, ...]:
    observed: dict[str, IntegrationCheck] = {}
    for line in stdout.splitlines():
        parts = line.split("\t", 3)
        if len(parts) != 4 or parts[0] != "CHECK" or parts[1] not in INTEGRATION_CHECK_NAMES:
            continue
        status = parts[2] if parts[2] in {"passed", "failed", "blocked"} else "failed"
        reason = parts[3] if status == parts[2] else f"invalid integration status: {parts[2]}"
        observed.setdefault(parts[1], IntegrationCheck(parts[1], status, reason))
    checks: list[IntegrationCheck] = []
    terminal = False
    terminal_reason = ""
    for name in INTEGRATION_CHECK_NAMES:
        if name in observed:
            check = observed[name]
            checks.append(check)
            if check.status == "failed" and not terminal:
                terminal = True
                terminal_reason = check.reason or f"{name} failed"
            continue
        if terminal:
            checks.append(IntegrationCheck(name, "blocked", terminal_reason))
        else:
            reason = (stderr or "integration probe did not report this check").strip()
            checks.append(IntegrationCheck(name, "failed", reason))
            terminal = True
            terminal_reason = reason
    return tuple(checks)


def _failed_checks(reason: str) -> tuple[IntegrationCheck, ...]:
    return tuple(
        IntegrationCheck(name, "failed" if index == 0 else "blocked", reason)
        for index, name in enumerate(INTEGRATION_CHECK_NAMES)
    )


def _integration_result(
    checks: tuple[IntegrationCheck, ...],
    *,
    commands: tuple[tuple[str, ...], ...],
    stdout: str,
    stderr: str,
    returncode: int = 0,
    started_at: str,
    started: float,
) -> IntegrationResult:
    passed = sum(check.status == "passed" for check in checks)
    failure = next((check.reason or f"{check.name} failed" for check in checks if check.status == "failed"), None)
    result = IntegrationResult(
        status="success" if passed == len(INTEGRATION_CHECK_NAMES) else "failed",
        checks=checks,
        integration_pass_ratio=passed / len(INTEGRATION_CHECK_NAMES),
        commands=commands,
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        started_at=started_at,
        finished_at=_utc_now(),
        duration_seconds=max(0.0, time.monotonic() - started),
        failure_stage=None if passed == len(INTEGRATION_CHECK_NAMES) else "integration",
        failure_reason=failure,
    )
    return result


def _persist_integration_artifacts(artifact_dir: Path | None, result: IntegrationResult) -> None:
    if artifact_dir is None:
        return
    (artifact_dir / "stdout.txt").write_text(result.stdout, encoding="utf-8")
    (artifact_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")
    (artifact_dir / "integration_result.json").write_text(
        json.dumps(result.to_json_dict(), indent=2),
        encoding="utf-8",
    )


def _text_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
