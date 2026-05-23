import json
from types import SimpleNamespace

from eagle.analysis.evolution_result_analysis import parse_final_test_analysis
from eagle.eval.microrts.final_test_batch import _build_failed_result_record, _build_raw_result_record
from eagle.eval.microrts.generation_replay import build_result_record


def test_batch_result_record_uses_clean_raw_schema():
    raw_result = {
        "winner": 0,
        "target_side": 0,
        "players": {
            "p0": {"resource_total": 3, "unit_types": {"Base": 1, "Worker": 2}},
            "p1": {"resource_total": 1, "unit_types": {"Barracks": 1, "Light": 1}},
        },
        "final_scoreboard": {"p0_eval": 7.0, "p1_eval": 2.0},
    }
    record = _build_raw_result_record(
        individual_id="ind-1",
        map_folder="8x8",
        map_path="8x8/basesWorkers8x8.xml",
        opponent="ai.RandomBiasedAI",
        repeat=0,
        match_score={"win_score": -1.0, "raw_resource_advantage_score": 2.0},
        raw_result=raw_result,
        simulation_meta={
            "log_path": "run.log",
            "trace_xml_path": "trace.xml",
            "trace_json_path": None,
            "interval_mode": "interval_10",
            "llm_interval": 10,
            "llm_model": "local",
            "llm_base_url": "http://127.0.0.1:8080/v1",
        },
    )

    assert set(record) == {
        "individual_id",
        "map_folder",
        "map",
        "opponent",
        "repeat",
        "result",
        "raw",
        "paths",
        "runtime",
    }
    assert "match_score" not in record
    assert "fitness" not in record
    assert "win_score" not in record
    assert record["result"] == "Win"
    assert record["raw"]["win_score"] == 1.0
    assert record["raw"]["score"] == 5.0
    assert "total_units" not in record["raw"]["ally"]
    assert record["paths"] == {"log": "run.log", "trace_xml": "trace.xml", "trace_json": None}
    assert record["runtime"] == {
        "interval_mode": "interval_10",
        "llm_interval": 10,
        "model": "local",
        "base_url": "http://127.0.0.1:8080/v1",
    }


def test_generation_replay_record_does_not_duplicate_scores():
    record = build_result_record(
        SimpleNamespace(id="ind-2"),
        "ai.RandomBiasedAI",
        {"win_score": 0.0, "raw_resource_advantage_score": 4.0},
        "run.log",
        trace_xml_path="trace.xml",
        trace_json_path=None,
    )

    assert record["result"] == "Draw"
    assert record["raw"] == {"win_score": 0.0, "score": 4.0}
    assert "match_score" not in record
    assert "fitness" not in record
    assert "resource_advantage_score" not in record


def test_analysis_normalizes_legacy_records_from_raw_only():
    payload = {
        "source_run_dir": "run",
        "results": [
            {
                "individual_id": "old",
                "map": "8x8/basesWorkers8x8.xml",
                "opponent": "ai.RandomBiasedAI",
                "match_score": {"win_score": -1.0, "raw_resource_advantage_score": 5.0},
                "fitness": {"win_score": -1.0, "raw_resource_advantage_score": 5.0},
                "ally": {"resources": 1, "base_count": 1},
                "enemy": {"resources": 2, "base_count": 1},
            },
            {
                "individual_id": "new",
                "map": "8x8/basesWorkers8x8.xml",
                "opponent": "ai.RandomBiasedAI",
                "result": "Draw",
                "raw": {
                    "win_score": 0.0,
                    "score": 0.0,
                    "ally": {"resources": 1},
                    "enemy": {"resources": 1},
                },
            },
        ],
    }

    analysis = parse_final_test_analysis(json.dumps(payload))

    assert analysis["games"] == 2
    assert analysis["wins"] == 0
    assert analysis["losses"] == 1
    assert analysis["draws"] == 1


def test_backend_error_repeat_is_failed_not_game_outcome():
    record = _build_failed_result_record(
        individual_id="ind-3",
        map_folder="8x8",
        map_path="8x8/basesWorkers8x8.xml",
        opponent="ai.RandomBiasedAI",
        repeat=0,
        error="LLM backend error during MicroRTS match",
        log_path="run.log",
        interval_mode="interval_10",
        llm_interval=10,
        model="local",
        base_url="http://127.0.0.1:8080/v1",
    )
    payload = {"source_run_dir": "run", "results": [record]}

    analysis = parse_final_test_analysis(json.dumps(payload))

    assert record["result"] == "Failed"
    assert record["status"] == "failed"
    assert analysis["wins"] == 0
    assert analysis["losses"] == 0
    assert analysis["draws"] == 0
    assert analysis["failed_games"] == 1
