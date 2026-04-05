from .config import EAConfig
from .evaluate import Evaluator
from .log_parse import parse_log

def test_parse_fitness():
    evaluator = Evaluator(None)  # We won't use the component pool for this test

    import glob
    import os
    log_files = glob.glob(str(evaluator.repo_root / "logs" / "run_*.log"))
    if not log_files:
        return 0.0
    latest_log_file = sorted(log_files)[-1]
    print(f"Testing parse_fitness with log file: {latest_log_file}")
    with open(latest_log_file, "r", encoding="utf-8") as f:
        log_content = f.read()
    # parse the log content to get the fitness score
    fitness = evaluator.calculate_fitness_score(log_content)
    print(f"Parsed fitness: {fitness}")

if __name__ == "__main__":
    test_parse_fitness()


def test_parse_resource_history():
    log_content = """
    initLogsIfNeeded
    [EAGLE.getAction] start
    gs.gameover() = false
    Running getAction for Player: 0
     current time 0 p0 player 0(5) p1 player 1(5)
    T: 0, P0: 0 (5), P1: 1 (5)
    initLogsIfNeeded
    [EAGLE.getAction] start
    gs.gameover() = false
    Running getAction for Player: 0
     current time 1 p0 player 0(5) p1 player 1(4)
    T: 1, P0: 0 (5), P1: 1 (4)
    initLogsIfNeeded
    [EAGLE.getAction] start
    gs.gameover() = false
    Running getAction for Player: 0
     current time 1 p0 player 0(5) p1 player 1(4)
    T: 1, P0: 0 (5), P1: 1 (4)
    initLogsIfNeeded
    [EAGLE.getAction] start
    gs.gameover() = false
    Running getAction for Player: 0
     current time 2 p0 player 0(4) p1 player 1(4)
    T: 2, P0: 0 (4), P1: 1 (4)
    """

    parsed = parse_log(log_content)

    assert parsed["resource_history"] == [
        {"time": 0, "p0_resources": 5, "p1_resources": 5},
        {"time": 1, "p0_resources": 5, "p1_resources": 4},
        {"time": 2, "p0_resources": 4, "p1_resources": 4},
    ]
    assert parsed["summary"]["resource_history"] == parsed["resource_history"]


def test_parse_feature_history():
    log_content = """
    initLogsIfNeeded
    [EAGLE.getAction] start
    === Dynamic Prompt ===
    Map size: 8x8
    Turn: 150/5000
    Max actions: 5

    Feature locations:
    (0, 0) Neutral Resource Node {resources=17}
    (7, 7) Neutral Resource Node {resources=19}
    (2, 1) Ally Base Unit {resources=4, current_action="producing unit at (0,0)", HP=10}
    (5, 6) Enemy Base Unit {resources=3, current_action="producing unit at (0,0)", HP=10}
    (0, 2) Ally Worker Unit {current_action="moving to (0,0)", HP=1}
    (6, 4) Enemy Worker Unit {current_action="moving to (0,0)", HP=1}
    (1, 1) Ally Worker Unit {current_action="idling", HP=1}
    (0, 7) Enemy Worker Unit {current_action="moving to (0,0)", HP=1}
    (1, 2) Ally Light Unit {current_action="idling", HP=4}
    (6, 2) Enemy Heavy Unit {current_action="idling", HP=4}
    ========================
    """

    parsed = parse_log(log_content)

    assert parsed["feature_history"] == [
        {
            "time": 150,
            "ally": {
                "base": 1,
                "worker": 2,
                "light": 1,
                "heavy": 0,
                "ranged": 0,
                "resource": 4,
            },
            "enemy": {
                "base": 1,
                "worker": 2,
                "light": 0,
                "heavy": 1,
                "ranged": 0,
                "resource": 3,
            },
            "neutral_resource": 36,
        }
    ]
    assert parsed["summary"]["feature_history"] == parsed["feature_history"]


def test_resource_advantage_evaluation():
    evaluator = Evaluator(None)
    parsed_log = {
        "feature_history": [
            {
                "time": 0,
                "ally": {"base": 1, "worker": 1, "light": 0, "heavy": 0, "ranged": 0, "resource": 5},
                "enemy": {"base": 1, "worker": 1, "light": 0, "heavy": 0, "ranged": 0, "resource": 5},
                "neutral_resource": 40,
            },
            {
                "time": 1,
                "ally": {"base": 1, "worker": 2, "light": 0, "heavy": 0, "ranged": 0, "resource": 6},
                "enemy": {"base": 1, "worker": 1, "light": 0, "heavy": 0, "ranged": 0, "resource": 4},
                "neutral_resource": 38,
            },
            {
                "time": 2,
                "ally": {"base": 1, "worker": 3, "light": 1, "heavy": 0, "ranged": 0, "resource": 8},
                "enemy": {"base": 1, "worker": 1, "light": 0, "heavy": 0, "ranged": 0, "resource": 3},
                "neutral_resource": 35,
            },
        ]
    }

    score = evaluator.resource_advantage_evaluation(parsed_log)

    assert -1.0 <= score <= 1.0
    assert score > 0.0


def test_resource_advantage_uses_config_weights():
    config = EAConfig(
        resource_advantage_alpha=1.0,
        resource_advantage_weights={
            "base": 0.0,
            "worker": 0.0,
            "light": 0.0,
            "heavy": 0.0,
            "ranged": 0.0,
            "resource": 1.0,
        },
    )
    evaluator = Evaluator(None, config=config)
    parsed_log = {
        "feature_history": [
            {
                "time": 0,
                "ally": {"base": 1, "worker": 5, "light": 0, "heavy": 0, "ranged": 0, "resource": 2},
                "enemy": {"base": 1, "worker": 1, "light": 0, "heavy": 0, "ranged": 0, "resource": 6},
                "neutral_resource": 30,
            }
        ]
    }

    score = evaluator.resource_advantage_evaluation(parsed_log)

    assert score < 0.0
