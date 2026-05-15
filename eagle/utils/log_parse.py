"""Parse MicroRTS runtime logs into structured summaries and state snapshots."""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


# =========================================================
# Regex patterns
# =========================================================

INIT_LOGS_RE = re.compile(r"^\s*initLogsIfNeeded.*$", re.MULTILINE)
GETACTION_START_RE = re.compile(r"^\s*\[(?P<agent>[^\]]+)\.getAction\]\s+start\s*$", re.MULTILINE)

RAW_RESPONSE_HEADER_RE = re.compile(r"^\s*=== Raw LLM Response ===\s*$", re.MULTILINE)
RAW_RESPONSE_FOOTER_RE = re.compile(r"^\s*=+\s*$", re.MULTILINE)
DYNAMIC_PROMPT_HEADER_RE = re.compile(r"^\s*=== Dynamic Prompt ===\s*$", re.MULTILINE)
DYNAMIC_PROMPT_FOOTER_RE = re.compile(r"^\s*=+\s*$", re.MULTILINE)
MAP_SIZE_RE = re.compile(r"^\s*Map size:\s*(?P<width>\d+)x(?P<height>\d+)\s*$", re.MULTILINE)

RUNNING_GETACTION_RE = re.compile(r"^\s*Running getAction for Player:\s*(?P<player>\d+)\s*$", re.MULTILINE)
CURRENT_TIME_RE = re.compile(
    r"^\s*current time\s+(?P<time>\d+)\s+p0 player\s+(?P<p0_player>\d+)\((?P<p0_value>\d+)\)\s+p1 player\s+(?P<p1_player>\d+)\((?P<p1_value>\d+)\)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
SCOREBOARD_RE = re.compile(
    r"^\s*T:\s*(?P<T>\d+),\s*P0:\s*(?P<P0_player>\d+)\s*\((?P<P0_value>\d+)\),\s*P1:\s*(?P<P1_player>\d+)\s*\((?P<P1_value>\d+)\)\s*$",
    re.MULTILINE,
)
FINAL_SCOREBOARD_RE = re.compile(
    r"^\s*(?:.*?\s+info\s*:\s*)?T:\s*(?P<T>\d+),\s*"
    r"P0:\s*(?P<P0_units>\d+)\s*\((?P<P0_eval>-?\d+(?:\.\d+)?)\),\s*"
    r"P1:\s*(?P<P1_units>\d+)\s*\((?P<P1_eval>-?\d+(?:\.\d+)?)\)\s*$",
    re.MULTILINE,
)
GAMEOVER_RE = re.compile(r"^\s*gs\.gameover\(\)\s*=\s*(?P<value>true|false)\s*$", re.MULTILINE)
GAME_SETTING_AI_RE = re.compile(r"^\s*AI(?P<slot>[12]):\s*(?P<name>.+?)\s*$", re.MULTILINE)
WINNER_RE = re.compile(r"^\s*WINNER\s*:?\s*(?P<winner>-?\d+)\s*$", re.MULTILINE | re.IGNORECASE)
FINAL_TICK_RE = re.compile(r"^\s*FINAL_TICK\s*:?\s*(?P<tick>\d+)\s*$", re.MULTILINE | re.IGNORECASE)
MAX_CYCLES_RE = re.compile(r"^\s*Max Cycles:\s*(?P<cycles>\d+)\s*$", re.MULTILINE | re.IGNORECASE)
LLM_CALL_RE = re.compile(r"^\s*\[EAGLE\]\s+call LLM:", re.MULTILINE)
LLM_CALL_LIMIT_RE = re.compile(r"llm_call_limit\s+reached", re.IGNORECASE)
WALL_CLOCK_TIMEOUT_RE = re.compile(r"wall-clock safety stop", re.IGNORECASE)
STACKTRACE_CLASS_RE = re.compile(r"\bat\s+(?P<class>[a-zA-Z_][\w.$]*)\.[\w$<>]+\(")

APPLY_MOVE_RE = re.compile(
    r"^\s*Applying LLM move:\s*(?P<raw_move>.+?)\s*\|\s*action_type=(?P<action_type>\w+)\s*\|\s*unit=\((?P<ux>-?\d+),(?P<uy>-?\d+)\)\s*type=(?P<unit_type>.+?)\s*$"
)

ACTION_FAILED_RE = re.compile(
    r"^\s*'?(?P<prefix>\w+)'?\s+failed:\s*(?P<reason>.+?)\s*$",
    re.IGNORECASE,
)

NON_OWNED_RE = re.compile(
    r"Can't command non-owned unit at\s*\((?P<x>-?\d+),\s*(?P<y>-?\d+)\)",
    re.IGNORECASE,
)

FALLBACK_NO_MOVES_RE = re.compile(
    r"^\s*\[LLM\]\s+No moves\[\]\s+in response\..*$",
    re.MULTILINE,
)

SKIP_RE = re.compile(
    r"^\s*(?:⚠️\s*)?Skipping\s+.+$",
    re.IGNORECASE,
)

TURN_PROMPT_RE = re.compile(r"^\s*Turn:\s*(?P<time>\d+)\s*/\s*\d+\s*$", re.MULTILINE)
FEATURE_LINE_RE = re.compile(
    r"^\s*\((?P<x>-?\d+),\s*(?P<y>-?\d+)\)\s+"
    r"(?P<team>Neutral|Ally|Enemy)\s+"
    r"(?P<unit>Resource Node|Base Unit|Barracks Unit|Worker Unit|Light Unit|Heavy Unit|Ranged Unit)"
    r"(?:\s+(?P<stats>\{.*\}))?\s*$"
)
RESOURCE_VALUE_RE = re.compile(r"resources\s*=\s*(?P<value>\d+)", re.IGNORECASE)
CURRENT_ACTION_RE = re.compile(r'current_action\s*=\s*"(?P<value>[^"]*)"', re.IGNORECASE)


# =========================================================
# Data classes
# =========================================================

@dataclass
class MoveResult:
    segment_index: int
    move_index: int
    agent: str | None
    current_time: int | None
    player: int | None

    llm_move_raw: dict[str, Any] | None
    raw_move: str | None
    unit_type: str | None
    action_type: str | None
    unit_position: list[int] | None

    status: str
    failure_reason: str | None

    has_apply_log: bool
    apply_log: str | None
    result_log: str | None


# =========================================================
# Utility functions
# =========================================================

def split_segments_by_initlogs(log_text: str) -> list[str]:
    """
    Split the log into segments by initLogsIfNeeded.
    """
    matches = list(INIT_LOGS_RE.finditer(log_text))
    if not matches:
        return [log_text.strip()] if log_text.strip() else []

    segments: list[str] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(log_text)
        segment = log_text[start:end].strip()
        if segment:
            segments.append(segment)
    return segments


def detect_agent_name(segment: str) -> str | None:
    """
    Detect the agent name from [Agent.getAction] start.
    """
    match = GETACTION_START_RE.search(segment)
    if not match:
        return None
    return match.group("agent")


def is_target_agent_block(segment: str, target_agent: str = "EAGLE") -> bool:
    """
    Check whether the segment belongs to the target agent.
    """
    agent = detect_agent_name(segment)
    if agent is None:
        return False
    return agent.lower() == target_agent.lower()


def extract_raw_llm_response(segment: str) -> tuple[str | None, dict[str, Any] | None]:
    """
    Extract the raw LLM response JSON.
    """
    header = RAW_RESPONSE_HEADER_RE.search(segment)
    if not header:
        return None, None

    after_header = segment[header.end():]
    footer = RAW_RESPONSE_FOOTER_RE.search(after_header)
    raw_text = after_header[:footer.start()].strip() if footer else after_header.strip()

    if not raw_text:
        return None, None

    try:
        raw_json = json.loads(raw_text)
    except json.JSONDecodeError:
        raw_json = None

    return raw_text, raw_json


def split_pre_post(segment: str) -> tuple[str, str]:
    """
    Split the segment into pre-getAction and post-getAction parts.
    """
    match = RUNNING_GETACTION_RE.search(segment)
    if not match:
        return segment.strip(), ""
    return segment[:match.start()].strip(), segment[match.start():].strip()


def parse_post_fields(post_text: str) -> dict[str, Any]:
    """
    Parse player id, current time, and scoreboard.
    """
    result: dict[str, Any] = {
        "player": None,
        "current_time": None,
        "scoreboard": None,
    }

    player_match = RUNNING_GETACTION_RE.search(post_text)
    if player_match:
        result["player"] = int(player_match.group("player"))

    time_match = CURRENT_TIME_RE.search(post_text)
    if time_match:
        result["current_time"] = int(time_match.group("time"))

    scoreboard_match = SCOREBOARD_RE.search(post_text)
    if scoreboard_match:
        result["scoreboard"] = {
            "T": int(scoreboard_match.group("T")),
            "P0": {
                "player": int(scoreboard_match.group("P0_player")),
                "value": int(scoreboard_match.group("P0_value")),
            },
            "P1": {
                "player": int(scoreboard_match.group("P1_player")),
                "value": int(scoreboard_match.group("P1_value")),
            },
        }

    return result


def extract_resource_history(log_text: str) -> list[dict[str, int]]:
    """
    Extract per-turn player resources from the full log.

    The Java logger prints lines like:
        current time 42 p0 player 0(5) p1 player 1(3)

    We collapse repeated observations for the same turn and keep one record
    per game time in log order.
    """
    by_time: dict[int, dict[str, int]] = {}
    ordered_times: list[int] = []

    for match in CURRENT_TIME_RE.finditer(log_text):
        current_time = int(match.group("time"))
        record = {
            "time": current_time,
            "p0_resources": int(match.group("p0_value")),
            "p1_resources": int(match.group("p1_value")),
        }

        if current_time not in by_time:
            ordered_times.append(current_time)
        by_time[current_time] = record

    return [by_time[current_time] for current_time in ordered_times]


def _empty_force_snapshot() -> dict[str, int]:
    """Create an empty ally/enemy force summary bucket."""
    return {
        "base": 0,
        "worker": 0,
        "light": 0,
        "heavy": 0,
        "ranged": 0,
        "resource": 0,
    }


def _normalize_feature_unit(unit_label: str) -> str | None:
    """Map Dynamic Prompt unit labels onto the normalized summary keys."""
    mapping = {
        "Base Unit": "base",
        "Worker Unit": "worker",
        "Light Unit": "light",
        "Heavy Unit": "heavy",
        "Ranged Unit": "ranged",
    }
    return mapping.get(unit_label)


def extract_feature_history(log_text: str) -> list[dict[str, Any]]:
    """
    Extract per-turn unit totals from the Dynamic Prompt feature list.

    The returned rows summarize:
    - ally/enemy counts of base/worker/light/heavy/ranged
    - ally/enemy stored resources inferred from Base Unit {resources=...}
    - neutral_resource total remaining on map from Resource Node {resources=...}
    """
    history: list[dict[str, Any]] = []
    header_matches = list(DYNAMIC_PROMPT_HEADER_RE.finditer(log_text))

    for header in header_matches:
        after_header = log_text[header.end():]
        footer = DYNAMIC_PROMPT_FOOTER_RE.search(after_header)
        block = after_header[:footer.start()].strip() if footer else after_header.strip()
        if not block:
            continue

        turn_match = TURN_PROMPT_RE.search(block)
        if not turn_match:
            continue
        current_time = int(turn_match.group("time"))

        feature_idx = block.find("Feature locations:")
        if feature_idx == -1:
            continue

        feature_lines = block[feature_idx:].splitlines()[1:]
        ally = _empty_force_snapshot()
        enemy = _empty_force_snapshot()
        neutral_resource = 0

        for raw_line in feature_lines:
            line = raw_line.strip()
            if not line:
                continue

            feature_match = FEATURE_LINE_RE.match(line)
            if not feature_match:
                continue

            team = feature_match.group("team")
            unit_label = feature_match.group("unit")
            stats = feature_match.group("stats") or ""

            if team == "Neutral" and unit_label == "Resource Node":
                resource_match = RESOURCE_VALUE_RE.search(stats)
                if resource_match:
                    neutral_resource += int(resource_match.group("value"))
                continue

            normalized_unit = _normalize_feature_unit(unit_label)
            if normalized_unit is None:
                continue

            target = ally if team == "Ally" else enemy
            target[normalized_unit] += 1

            if unit_label == "Base Unit":
                resource_match = RESOURCE_VALUE_RE.search(stats)
                if resource_match:
                    target["resource"] += int(resource_match.group("value"))

        history.append(
            {
                "time": current_time,
                "ally": ally,
                "enemy": enemy,
                "neutral_resource": neutral_resource,
            }
        )

    by_time: dict[int, dict[str, Any]] = {}
    ordered_times: list[int] = []
    for row in history:
        current_time = row["time"]
        if current_time not in by_time:
            ordered_times.append(current_time)
        by_time[current_time] = row

    return [by_time[current_time] for current_time in ordered_times]


def extract_dynamic_prompt_blocks(log_text: str) -> list[dict[str, Any]]:
    """
    Extract full Dynamic Prompt blocks from a log.

    Each returned item preserves the original prompt text and, when available,
    the parsed turn number so downstream surrogate evaluators can reuse a gameplay
    game snapshot without replaying the game.
    """
    blocks: list[dict[str, Any]] = []
    header_matches = list(DYNAMIC_PROMPT_HEADER_RE.finditer(log_text))

    for header in header_matches:
        after_header = log_text[header.end():]
        footer = DYNAMIC_PROMPT_FOOTER_RE.search(after_header)
        block = after_header[:footer.start()].strip() if footer else after_header.strip()
        if not block:
            continue

        turn_match = TURN_PROMPT_RE.search(block)
        blocks.append(
            {
                "time": int(turn_match.group("time")) if turn_match else None,
                "text": block,
            }
        )

    return blocks


def collect_recent_dynamic_prompts(
    logs_dir: str | Path,
    recent_count: int = 10,
) -> list[dict[str, Any]]:
    """
    Collect every Dynamic Prompt block found in the most recent log window.
    """
    log_dir_path = Path(logs_dir)
    if not log_dir_path.exists():
        return []

    # We only look at a sliding window of the most recent logs so surrogate
    # sampling stays close to the states currently being generated in runs.
    candidate_logs = sorted(
        log_dir_path.glob("run_*.log"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )[: max(0, recent_count)]

    collected: list[dict[str, Any]] = []
    for log_path in candidate_logs:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        # Only reuse gameplay EAGLE runtime logs for surrogate round sampling.
        # Surrogate-agent logs can contain different action traces and would
        # leak the surrogate policy back into the history window.
        if "[EAGLE.getAction]" not in log_text or "[eaglePolicy.getAction]" in log_text:
            continue
        for block in extract_dynamic_prompt_blocks(log_text):
            item = dict(block)
            item["log_path"] = str(log_path)
            collected.append(item)
    return collected


def sample_recent_dynamic_prompt(
    logs_dir: str | Path,
    recent_count: int = 10,
    rng: random.Random | None = None,
) -> dict[str, Any] | None:
    """
    Randomly sample one Dynamic Prompt block from the most recent log files.

    Selection policy:
    1. sort available `run_*.log` files by modified time descending
    2. keep the most recent `recent_count` files
    3. randomly choose one file from that window
    4. randomly choose one Dynamic Prompt block from that file

    Returns None when the directory is missing, no candidate logs exist, or the
    selected window contains no Dynamic Prompt blocks.
    """
    rng = rng or random
    dynamic_prompts = collect_recent_dynamic_prompts(logs_dir, recent_count=recent_count)
    if not dynamic_prompts:
        return None
    return dict(rng.choice(dynamic_prompts))


def sample_recent_dynamic_prompts(
    logs_dir: str | Path,
    recent_count: int = 10,
    sample_count: int = 10,
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    """
    Sample up to `sample_count` Dynamic Prompt blocks from the recent log window.
    """
    rng = rng or random
    dynamic_prompts = collect_recent_dynamic_prompts(logs_dir, recent_count=recent_count)
    if not dynamic_prompts:
        return []
    # Returning the whole window when it is already small avoids introducing
    # duplicate samples and keeps each sampled round unique.
    if len(dynamic_prompts) <= sample_count:
        return [dict(item) for item in dynamic_prompts]
    return [dict(item) for item in rng.sample(dynamic_prompts, sample_count)]


def parse_dynamic_prompt_state(dynamic_prompt_text: str) -> dict[str, Any]:
    """
    Parse one sampled Dynamic Prompt block into a lightweight game state.
    """
    map_match = MAP_SIZE_RE.search(dynamic_prompt_text)
    width = int(map_match.group("width")) if map_match else None
    height = int(map_match.group("height")) if map_match else None

    state = {
        "map_width": width,
        "map_height": height,
        "ally_units": {},
        "enemy_units": {},
        "neutral_resources": {},
        "ally_bases": {},
        "enemy_bases": {},
    }

    for raw_line in dynamic_prompt_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        feature_match = FEATURE_LINE_RE.match(line)
        if not feature_match:
            continue

        x = int(feature_match.group("x"))
        y = int(feature_match.group("y"))
        team = feature_match.group("team")
        unit_label = feature_match.group("unit")
        stats = feature_match.group("stats") or ""
        position = (x, y)

        if team == "Neutral" and unit_label == "Resource Node":
            resource_match = RESOURCE_VALUE_RE.search(stats)
            state["neutral_resources"][position] = {
                "type": "resource",
                "resources": int(resource_match.group("value")) if resource_match else 0,
            }
            continue

        normalized_unit = _normalize_feature_unit(unit_label)
        if normalized_unit is None and unit_label == "Barracks Unit":
            normalized_unit = "barracks"
        if normalized_unit is None:
            continue

        unit_info = {
            "type": normalized_unit,
            "team": team.lower(),
            "stats": stats,
        }
        current_action_match = CURRENT_ACTION_RE.search(stats)
        current_action = current_action_match.group("value") if current_action_match else "idling"
        unit_info["current_action"] = current_action
        unit_info["available_for_new_command"] = current_action.strip().lower() == "idling"
        if normalized_unit == "base":
            resource_match = RESOURCE_VALUE_RE.search(stats)
            unit_info["resources"] = int(resource_match.group("value")) if resource_match else 0

        if team == "Ally":
            # The surrogate validator only needs ownership, type, and base/resource
            # anchors, so we keep this state intentionally lightweight.
            state["ally_units"][position] = unit_info
            if normalized_unit == "base":
                state["ally_bases"][position] = unit_info
        elif team == "Enemy":
            state["enemy_units"][position] = unit_info
            if normalized_unit == "base":
                state["enemy_bases"][position] = unit_info

    return state


def parse_gameover(pre_text: str) -> bool | None:
    """
    Parse gs.gameover() if present.
    """
    match = GAMEOVER_RE.search(pre_text)
    if not match:
        return None
    return match.group("value").lower() == "true"


def parse_game_settings(log_text: str) -> dict[str, str]:
    """
    Parse AI1/AI2 definitions from the log header.
    """
    settings: dict[str, str] = {}
    for match in GAME_SETTING_AI_RE.finditer(log_text):
        settings[f"AI{match.group('slot')}"] = match.group("name").strip()
    return settings


def extract_declared_winner(log_text: str) -> str | None:
    """Extract the declared winner from an explicit WINNER line when present."""
    match = WINNER_RE.search(log_text)
    if not match:
        return None
    return match.group("winner")


def extract_final_tick(log_text: str) -> int | None:
    """Extract the final game tick printed by MicroRTS when available."""
    match = FINAL_TICK_RE.search(log_text)
    if not match:
        return None
    return int(match.group("tick"))


def extract_max_cycles(log_text: str) -> int | None:
    """Extract the configured MicroRTS max cycle count from the log header."""
    match = MAX_CYCLES_RE.search(log_text)
    if not match:
        return None
    return int(match.group("cycles"))


def extract_final_scoreboard(log_text: str) -> dict[str, Any] | None:
    """Extract the last MicroRTS scoreboard line from a completed game log."""
    matches = list(FINAL_SCOREBOARD_RE.finditer(log_text))
    if not matches:
        return None
    match = matches[-1]
    return {
        "time": int(match.group("T")),
        "p0_units": int(match.group("P0_units")),
        "p1_units": int(match.group("P1_units")),
        "p0_eval": float(match.group("P0_eval")),
        "p1_eval": float(match.group("P1_eval")),
    }


def count_llm_calls(log_text: str) -> int:
    """Count actual Java EAGLE LLM call log entries."""
    return len(LLM_CALL_RE.findall(log_text))


def detect_llm_call_limit(log_text: str) -> bool:
    """Return whether the EAGLE agent reported that the LLM call limit was reached."""
    return bool(LLM_CALL_LIMIT_RE.search(log_text))


def detect_wall_clock_timeout(log_text: str) -> bool:
    """Return whether the runtime log reports a wall-clock safety stop."""
    return bool(WALL_CLOCK_TIMEOUT_RE.search(log_text))


def detect_tick_timeout(final_tick: Any, max_cycles: Any) -> bool:
    """Return whether the final tick reached the configured MicroRTS tick budget."""
    try:
        return int(final_tick) >= int(max_cycles)
    except (TypeError, ValueError):
        return False


def _class_name_variants(name: str) -> set[str]:
    """Generate plausible Java class-name variants for one configured agent name."""
    variants = {name.strip()}
    short_name = name.strip().split(".")[-1]
    variants.add(short_name)
    return {variant for variant in variants if variant}


def detect_crashed_ai_side(log_text: str, game_settings: dict[str, str]) -> str | None:
    """
    Infer which configured AI crashed from a Java stack trace.
    Returns "0" for AI1/P0, "1" for AI2/P1, or None.
    """
    classes = {
        match.group("class").split(".")[-1]
        for match in STACKTRACE_CLASS_RE.finditer(log_text)
    }
    if not classes:
        return None

    ai1_variants = _class_name_variants(game_settings.get("AI1", ""))
    ai2_variants = _class_name_variants(game_settings.get("AI2", ""))

    if classes & ai1_variants:
        return "0"
    if classes & ai2_variants:
        return "1"
    return None


def infer_winner(log_text: str, target_agent: str = "EAGLE") -> dict[str, Any]:
    """
    Determine the winner from an explicit WINNER line or from a crash trace.
    """
    game_settings = parse_game_settings(log_text)
    declared_winner = extract_declared_winner(log_text)
    crashed_side = detect_crashed_ai_side(log_text, game_settings)

    inferred_winner = declared_winner
    termination_reason = "winner_line" if declared_winner is not None else None

    if inferred_winner is None and crashed_side is not None:
        inferred_winner = "1" if crashed_side == "0" else "0"
        termination_reason = "opponent_crash" if crashed_side == "1" else "self_crash"

    target_side = None
    target_variants = _class_name_variants(target_agent)
    if game_settings:
        if target_variants & _class_name_variants(game_settings.get("AI1", "")):
            target_side = "0"
        elif target_variants & _class_name_variants(game_settings.get("AI2", "")):
            target_side = "1"

    return {
        "game_settings": game_settings,
        "declared_winner": declared_winner,
        "crashed_side": crashed_side,
        "winner": inferred_winner,
        "target_side": target_side,
        "termination_reason": termination_reason,
    }


def normalize_llm_moves(raw_llm_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    """
    Safely return the moves array from the raw LLM response.
    """
    if not isinstance(raw_llm_json, dict):
        return []

    moves = raw_llm_json.get("moves")
    if not isinstance(moves, list):
        return []

    normalized: list[dict[str, Any]] = []
    for move in moves:
        if isinstance(move, dict):
            normalized.append(move)
        else:
            normalized.append({"raw_value": move})
    return normalized


def extract_failure_reason(line: str) -> str:
    """
    Convert a failure log line into a compact reason label.
    """
    lower = line.lower()

    if "non-owned unit" in lower:
        return "non_owned_unit"
    if "non-worker" in lower:
        return "non_worker"
    if "not base/barracks" in lower:
        return "not_base_or_barracks"
    if "structure at" in lower:
        return "structure_blocked"
    if "out of bounds" in lower:
        return "out_of_bounds"
    if "resource" in lower:
        return "resource_issue"

    failed_match = ACTION_FAILED_RE.match(line.strip())
    if failed_match:
        return f"{failed_match.group('prefix').lower()}_failed"

    return "unknown_failure"


# =========================================================
# Core move-result builder
# =========================================================

def build_move_results(
    segment_index: int,
    agent: str | None,
    current_time: int | None,
    player: int | None,
    raw_llm_json: dict[str, Any] | None,
    pre_text: str,
) -> list[MoveResult]:
    """
    Build move-level results based on log events only.

    Categories:
    - direct_failed: failed before apply
    - applied_failed: apply happened, then failure
    - applied_success: apply happened, no failure
    - not_executed: no matching execution log found
    """
    llm_moves = normalize_llm_moves(raw_llm_json)
    lines = [line.rstrip() for line in pre_text.splitlines() if line.strip()]

    results: list[MoveResult] = []
    move_idx = 0
    line_idx = 0

    while move_idx < len(llm_moves):
        move = llm_moves[move_idx]

        raw_move = move.get("raw_move") if isinstance(move.get("raw_move"), str) else None
        unit_type = move.get("unit_type") if isinstance(move.get("unit_type"), str) else None
        action_type = move.get("action_type") if isinstance(move.get("action_type"), str) else None
        unit_position = move.get("unit_position") if isinstance(move.get("unit_position"), list) else None

        status = "not_executed"
        failure_reason: str | None = None
        has_apply_log = False
        apply_log: str | None = None
        result_log: str | None = None

        matched = False

        while line_idx < len(lines):
            line = lines[line_idx].strip()

            if NON_OWNED_RE.search(line):
                status = "direct_failed"
                failure_reason = extract_failure_reason(line)
                result_log = line
                matched = True
                line_idx += 1
                break

            if SKIP_RE.search(line):
                status = "duplicate_skipped"
                failure_reason = extract_failure_reason(line)
                result_log = line
                matched = True
                line_idx += 1
                break

            apply_match = APPLY_MOVE_RE.match(line)
            if apply_match:
                status = "applied_success"
                has_apply_log = True
                apply_log = line
                matched = True
                line_idx += 1

                if line_idx < len(lines):
                    next_line = lines[line_idx].strip()
                    failed_match = ACTION_FAILED_RE.match(next_line)
                    if failed_match:
                        status = "applied_failed"
                        failure_reason = extract_failure_reason(next_line)
                        result_log = next_line
                        line_idx += 1

                break

            line_idx += 1

        if not matched:
            if FALLBACK_NO_MOVES_RE.search(pre_text):
                failure_reason = "fallback_no_moves"
            else:
                failure_reason = "no_matching_execution_log"

        results.append(
            MoveResult(
                segment_index=segment_index,
                move_index=move_idx,
                agent=agent,
                current_time=current_time,
                player=player,
                llm_move_raw=move,
                raw_move=raw_move,
                unit_type=unit_type,
                action_type=action_type,
                unit_position=unit_position,
                status=status,
                failure_reason=failure_reason,
                has_apply_log=has_apply_log,
                apply_log=apply_log,
                result_log=result_log,
            )
        )

        move_idx += 1

    return results


# =========================================================
# Segment parser
# =========================================================

def parse_segment(segment: str, segment_index: int) -> dict[str, Any]:
    """
    Parse one target-agent segment.
    """
    agent = detect_agent_name(segment)
    pre_text, post_text = split_pre_post(segment)
    raw_llm_text, raw_llm_json = extract_raw_llm_response(pre_text)
    post_fields = parse_post_fields(post_text)

    move_results = build_move_results(
        segment_index=segment_index,
        agent=agent,
        current_time=post_fields["current_time"],
        player=post_fields["player"],
        raw_llm_json=raw_llm_json,
        pre_text=pre_text,
    )

    llm_move_count = len(normalize_llm_moves(raw_llm_json))
    direct_failure_count = sum(1 for m in move_results if m.status == "direct_failed")
    duplicate_skipped_count = sum(1 for m in move_results if m.status == "duplicate_skipped")
    applied_failure_count = sum(1 for m in move_results if m.status == "applied_failed")
    applied_success_count = sum(1 for m in move_results if m.status == "applied_success")

    return {
        "segment_index": segment_index,
        "agent": agent,
        "current_time": post_fields["current_time"],
        "player": post_fields["player"],
        "scoreboard": post_fields["scoreboard"],
        "gameover": parse_gameover(pre_text),
        "raw_llm_response_text": raw_llm_text,
        "raw_llm_response_json": raw_llm_json,
        "llm_move_count": llm_move_count,
        "direct_failure_count": direct_failure_count,
        "duplicate_skipped_count": duplicate_skipped_count,
        "applied_failure_count": applied_failure_count,
        "applied_success_count": applied_success_count,
        "move_results": [asdict(m) for m in move_results],
    }


# =========================================================
# Main parser
# =========================================================

def parse_log(log_text: str, target_agent: str = "EAGLE") -> dict[str, Any]:
    """
    Parse the full log and return segment-level and global summaries.
    """
    segments = split_segments_by_initlogs(log_text)

    parsed_segments: list[dict[str, Any]] = []
    for i, segment in enumerate(segments):
        if is_target_agent_block(segment, target_agent=target_agent):
            parsed_segments.append(parse_segment(segment, i))

    all_moves: list[dict[str, Any]] = []
    for segment in parsed_segments:
        all_moves.extend(segment["move_results"])
    resource_history = extract_resource_history(log_text)
    feature_history = extract_feature_history(log_text)
    final_tick = extract_final_tick(log_text)
    max_cycles = extract_max_cycles(log_text)

    summary = {
        "target_agent": target_agent,
        "segment_count": len(parsed_segments),
        "llm_call_count": count_llm_calls(log_text),
        "llm_move_count": sum(s["llm_move_count"] for s in parsed_segments),
        "direct_failure_count": sum(s["direct_failure_count"] for s in parsed_segments),
        "duplicate_skipped_count": sum(s["duplicate_skipped_count"] for s in parsed_segments),
        "applied_failure_count": sum(s["applied_failure_count"] for s in parsed_segments),
        "applied_success_count": sum(s["applied_success_count"] for s in parsed_segments),
        "resource_history": resource_history,
        "feature_history": feature_history,
        "final_tick": final_tick,
        "final_scoreboard": extract_final_scoreboard(log_text),
        "max_cycles": max_cycles,
        "tick_timeout": detect_tick_timeout(final_tick, max_cycles),
        "wall_clock_timeout": detect_wall_clock_timeout(log_text),
        "llm_call_limit_reached": detect_llm_call_limit(log_text),
    }
    outcome = infer_winner(log_text, target_agent=target_agent)
    summary.update(
        {
            "winner": outcome["winner"],
            "declared_winner": outcome["declared_winner"],
            "crashed_side": outcome["crashed_side"],
            "target_side": outcome["target_side"],
            "termination_reason": outcome["termination_reason"],
        }
    )

    return {
        "summary": summary,
        "game_settings": outcome["game_settings"],
        "resource_history": resource_history,
        "feature_history": feature_history,
        "segments": parsed_segments,
        "all_move_results": all_moves,
    }


def parse_log_file(file_path: str | Path, target_agent: str = "EAGLE") -> dict[str, Any]:
    """
    Parse a log file from disk.
    """
    text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    return parse_log(text, target_agent=target_agent)


# =========================================================
# Output helpers
# =========================================================

def save_json(data: Any, output_path: str | Path) -> None:
    """
    Save parsed results as JSON.
    """
    Path(output_path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_jsonl_move_results(parsed: dict[str, Any], output_path: str | Path) -> None:
    """
    Save move-level results as JSONL.
    """
    with Path(output_path).open("w", encoding="utf-8") as f:
        for row in parsed["all_move_results"]:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# if __name__ == "__main__":
#     input_path = "game.log"
#     output_json = "parsed_eagle_log.json"
#     output_jsonl = "parsed_eagle_moves.jsonl"

#     parsed = parse_log_file(input_path, target_agent="EAGLE")

#     print(json.dumps(parsed["summary"], ensure_ascii=False, indent=2))

#     save_json(parsed, output_json)
#     save_jsonl_move_results(parsed, output_jsonl)
