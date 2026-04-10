import tempfile
from pathlib import Path
import shutil

from .config import EAConfig
from .evaluate import Evaluator
from .fitness_recorder import FitnessRecorder
from .nsga2 import NSGA2
from .steady_state_nsga2 import SteadyStateNSGA2
from .individual import Individual
from . import evaluate as evaluate_module
from . import llm as llm_module
from .log_parse import (
    parse_log,
    extract_dynamic_prompt_blocks,
    sample_recent_dynamic_prompt,
    parse_dynamic_prompt_state,
)
from .simulation_runner import set_llm_interval

def test_parse_fitness():
    """Smoke-test parsing on the newest locally available game log."""
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
    """Verify that repeated turn logs collapse into one resource record per turn."""
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
    """Verify that Dynamic Prompt feature blocks become normalized force summaries."""
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


def test_extract_dynamic_prompt_blocks():
    """Verify extraction of raw Dynamic Prompt blocks and their turn numbers."""
    log_content = """
    initLogsIfNeeded
    [EAGLE.getAction] start
    === Dynamic Prompt ===
    Map size: 8x8
    Turn: 12/5000
    Max actions: 2

    Feature locations:
    (0, 0) Neutral Resource Node {resources=20}
    ========================
    """

    blocks = extract_dynamic_prompt_blocks(log_content)

    assert len(blocks) == 1
    assert blocks[0]["time"] == 12
    assert "Feature locations:" in blocks[0]["text"]


def test_parse_dynamic_prompt_state():
    """Verify lightweight state parsing for sampled Dynamic Prompt blocks."""
    dynamic_prompt = """
    Map size: 8x8
    Turn: 12/5000
    Max actions: 2

    Feature locations:
    (0, 0) Neutral Resource Node {resources=20}
    (2, 1) Ally Base Unit {resources=4, HP=10}
    (1, 1) Ally Worker Unit {HP=1}
    (5, 6) Enemy Base Unit {resources=3, HP=10}
    (6, 6) Enemy Worker Unit {HP=1}
    """

    state = parse_dynamic_prompt_state(dynamic_prompt)

    assert state["map_width"] == 8
    assert state["map_height"] == 8
    assert (1, 1) in state["ally_units"]
    assert state["ally_units"][(1, 1)]["type"] == "worker"
    assert (5, 6) in state["enemy_bases"]
    assert (0, 0) in state["neutral_resources"]


def test_sample_recent_dynamic_prompt():
    """Verify random sampling over the recent-log window for Dynamic Prompt blocks."""
    tmp_path = Path(__file__).resolve().parent / "_tmp_recent_logs_test"
    shutil.rmtree(tmp_path, ignore_errors=True)
    tmp_path.mkdir(parents=True, exist_ok=True)
    try:
        old_log = tmp_path / "run_2026-04-01_00-00-00.log"
        new_log = tmp_path / "run_2026-04-02_00-00-00.log"

        old_log.write_text(
            """
            === Dynamic Prompt ===
            Map size: 8x8
            Turn: 3/5000
            Max actions: 2

            Feature locations:
            (0, 0) Neutral Resource Node {resources=20}
            ========================
            """,
            encoding="utf-8",
        )
        new_log.write_text(
            """
            === Dynamic Prompt ===
            Map size: 8x8
            Turn: 7/5000
            Max actions: 2

            Feature locations:
            (1, 1) Ally Worker Unit {HP=1}
            ========================
            """,
            encoding="utf-8",
        )

        sampled = sample_recent_dynamic_prompt(tmp_path, recent_count=2)

        assert sampled is not None
        assert sampled["log_path"] in {str(old_log), str(new_log)}
        assert sampled["time"] in {3, 7}
        assert "Feature locations:" in sampled["text"]
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_resource_advantage_evaluation():
    """Verify that the weighted resource/material score stays bounded and directional."""
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
    """Verify that custom config weights change the resource-advantage objective."""
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


def test_surrogate_version_dispatch_game_round():
    """Verify game-round surrogate dispatch when the config selects that mode."""
    config = EAConfig(surrogate_version="game_round")
    evaluator = Evaluator(None, config=config)

    original_sampler = evaluate_module.sample_recent_dynamic_prompts
    original_json = llm_module.LLM.ollama_generate_json_response
    original_llm = llm_module.LLM.ollama_evaluate_fitness

    try:
        evaluate_module.sample_recent_dynamic_prompts = lambda *args, **kwargs: [{
            "time": 42,
            "text": (
                "Map size: 8x8\nTurn: 42/5000\nMax actions: 2\n\n"
                "Feature locations:\n"
                "(0, 0) Neutral Resource Node {resources=20}\n"
                "(2, 1) Ally Base Unit {resources=4, HP=10}\n"
                "(1, 1) Ally Worker Unit {HP=1}\n"
                "(5, 6) Enemy Base Unit {resources=4, HP=10}\n"
            ),
            "log_path": "fake.log",
        }]
        llm_module.LLM.ollama_generate_json_response = staticmethod(
            lambda prompt, model="llama3.1:8b", temperature=0.2: {
                "thinking": "test",
                "moves": [
                    {
                        "raw_move": "(1, 1): worker harvest((0, 0), (2, 1))",
                        "unit_position": [1, 1],
                        "unit_type": "worker",
                        "action_type": "harvest",
                    }
                ],
            }
        )
        llm_module.LLM.ollama_evaluate_fitness = staticmethod(
            lambda prompt, example=None, model="llama3.1:8b": [0.1, 0.9, 0.1, 0.1]
        )

        scores = evaluator.surrogate_evaluation("test prompt")

        assert scores[0] > 0.0
    finally:
        evaluate_module.sample_recent_dynamic_prompts = original_sampler
        llm_module.LLM.ollama_generate_json_response = original_json
        llm_module.LLM.ollama_evaluate_fitness = original_llm


def test_surrogate_game_round_falls_back_to_llm_when_no_logs():
    """Verify fallback to the prompt-only surrogate when no sampled logs exist."""
    config = EAConfig(surrogate_version="game_round")
    evaluator = Evaluator(None, config=config)

    original_sampler = evaluate_module.sample_recent_dynamic_prompts
    original_llm = llm_module.LLM.ollama_evaluate_fitness

    try:
        evaluate_module.sample_recent_dynamic_prompts = lambda *args, **kwargs: []
        llm_module.LLM.ollama_evaluate_fitness = staticmethod(
            lambda prompt, example=None, model="llama3.1:8b": [0.5, 0.2, 0.7, 0.7]
        )

        scores = evaluator.surrogate_evaluation("test prompt")

        assert scores[0] > 0.0
    finally:
        evaluate_module.sample_recent_dynamic_prompts = original_sampler
        llm_module.LLM.ollama_evaluate_fitness = original_llm


def test_game_round_score_from_llm_response():
    """Verify legality-based scoring for one mocked round-level LLM response."""
    evaluator = Evaluator(None)
    dynamic_prompt = """
    Map size: 8x8
    Turn: 12/5000
    Max actions: 2

    Feature locations:
    (0, 0) Neutral Resource Node {resources=20}
    (2, 1) Ally Base Unit {resources=4, HP=10}
    (1, 1) Ally Worker Unit {HP=1}
    (5, 6) Enemy Base Unit {resources=4, HP=10}
    """
    llm_response = {
        "thinking": "test",
        "moves": [
            {
                "raw_move": "(1, 1): worker harvest((0, 0), (2, 1))",
                "unit_position": [1, 1],
                "unit_type": "worker",
                "action_type": "harvest",
            }
        ],
    }

    score = evaluator._score_game_round_response(llm_response, dynamic_prompt)

    assert score > 0.0


def test_game_round_surrogate_keeps_parent_first_two_scores():
    """Verify that game-round surrogate updates only the third fitness objective."""
    config = EAConfig(surrogate_version="game_round")
    evaluator = Evaluator(None, config=config)
    individual = Individual()
    individual.fitness = [0.7, 0.3, 0.1]

    original_method = evaluator.surrogate_evaluation
    evaluator.surrogate_evaluation = lambda prompt, fitness_recorder=None: [0.8, 0.0, 0.0, 0.0]
    evaluator.construct_prompt = lambda individual: "test prompt"
    evaluator.save_prompt = lambda prompt: None

    class DummyRecorder:
        records = []
        def find_matching_history(self, prompt, opponent):
            """Return no matches so the test exercises surrogate evaluation."""
            return []
        def record_fitness(self, record):
            """Ignore writes because this recorder is only a lightweight stub."""
            return None

    try:
        evaluator.evaluate(
            individual,
            use_real_evaluation=False,
            allow_history_reuse_for_real=False,
            opponent=None,
            fitness_recorder=DummyRecorder(),
        )
        assert individual.fitness == [0.7, 0.3, 0.8]
    finally:
        evaluator.surrogate_evaluation = original_method


def test_real_evaluation_does_not_use_history_shortcut():
    """Verify real-evaluation requests ignore prompt-history cache hits."""
    config = EAConfig()
    evaluator = Evaluator(None, config=config)
    individual = Individual()
    individual.fitness = [0.2, 0.2, 0.2]

    evaluator.construct_prompt = lambda individual: "test prompt"
    evaluator.save_prompt = lambda prompt: None
    evaluator.simulate_games = lambda opponent, stats: ([1.0, 0.1, 0.2], {
        "parsed_log": {},
        "winner": "0",
        "timeout": False,
        "log_path": "fake.log",
        "llm_calls": 1,
    })

    class DummyRecorder:
        records = []

        def find_matching_history(self, prompt, opponent):
            return [{"fitness_score": [0.8, 0.8, 0.8]}]

        def record_fitness(self, record):
            self.records.append(record)

    recorder = DummyRecorder()
    evaluator.evaluate(
        individual,
        use_real_evaluation=True,
        allow_history_reuse_for_real=False,
        opponent="ai.RandomAI",
        fitness_recorder=recorder,
    )

    assert individual.fitness == [1.0, 0.1, 0.2]
    assert recorder.records[0]["evaluation_mode"] == "real"


def test_initial_real_evaluation_can_use_history_shortcut():
    """Verify initial-population real eval may reuse matching history."""
    config = EAConfig()
    evaluator = Evaluator(None, config=config)
    individual = Individual()
    individual.fitness = [0.0, 0.0, 0.0]

    evaluator.construct_prompt = lambda individual: "test prompt"
    evaluator.save_prompt = lambda prompt: None
    evaluator.simulate_games = lambda opponent, stats: (_ for _ in ()).throw(AssertionError("should not run simulation"))

    class DummyRecorder:
        records = []

        def find_matching_history(self, prompt, opponent):
            return [{"fitness_score": [1.0, 0.2, 0.3]}]

        def record_fitness(self, record):
            self.records.append(record)

    recorder = DummyRecorder()
    evaluator.evaluate(
        individual,
        use_real_evaluation=True,
        allow_history_reuse_for_real=True,
        opponent="ai.RandomAI",
        generation=-1,
        fitness_recorder=recorder,
    )

    assert individual.fitness == [1.0, 0.2, 0.3]
    assert recorder.records[0]["evaluation_mode"] == "real_history_reuse_initial"


def test_fitness_history_key_uses_stable_digest_and_runtime_context(tmp_path):
    """Verify cache keys are stable and include runtime settings that affect performance."""
    recorder = FitnessRecorder(tmp_path, EAConfig(run_time_per_game_sec=500, llm_interval=7))
    original_repo_root = recorder.repo_root
    original_history_path = recorder.history_records_path
    try:
        recorder.repo_root = tmp_path
        recorder.history_records_path = str(tmp_path / "fitness_history.jsonl")
        recorder.history = []
        resources_dir = tmp_path / "resources"
        resources_dir.mkdir(exist_ok=True)
        (resources_dir / "config.properties").write_text(
            "map_location=maps/test.xml\n"
            "max_cycles=5000\n"
            "update_interval=50\n",
            encoding="utf-8",
        )

        key = recorder.build_history_key("same prompt", "ai.RandomBiasedAI")

        assert len(key["prompt_digest"]) == 64
        assert key["context"]["run_time_per_game_sec"] == 500
        assert key["context"]["eagle_llm_interval"] == 7
    finally:
        recorder.repo_root = original_repo_root
        recorder.history_records_path = original_history_path


def test_history_only_records_real_evaluations(tmp_path):
    """Verify surrogate/history-reuse records stay out of cross-run history."""
    recorder = FitnessRecorder(tmp_path, EAConfig())
    recorder.history_records_path = str(tmp_path / "fitness_history.jsonl")
    recorder.history = []
    recorder.record_fitness(
        {
            "prompt": "surrogate prompt",
            "fitness_score": [0.9, 0.1, 0.1],
            "opponent": "ai.RandomAI",
            "evaluation_mode": "surrogate",
        }
    )
    recorder.record_fitness(
        {
            "prompt": "real prompt",
            "fitness_score": [1.0, 0.1, 0.1],
            "opponent": "ai.RandomAI",
            "evaluation_mode": "real",
        }
    )

    assert len(recorder.history) == 1
    assert recorder.history[0]["evaluation_mode"] == "real"


def test_set_llm_interval_updates_properties_file(tmp_path):
    """Verify the runner writes llm_interval into config.properties for Java to read."""
    resources_dir = tmp_path / "resources"
    resources_dir.mkdir(parents=True, exist_ok=True)
    config_path = resources_dir / "config.properties"
    config_path.write_text(
        "AI1=ai.abstraction.EAGLE\n"
        "AI2=ai.RandomAI\n",
        encoding="utf-8",
    )

    set_llm_interval(tmp_path, 7)

    updated = config_path.read_text(encoding="utf-8")
    assert "llm_interval=7" in updated


def test_log_multi_objective_generation_includes_evaluation_mode(tmp_path):
    """Verify generation text logs show each individual's evaluation mode."""
    from .basic_ea import EA
    from . import basic_ea as basic_ea_module

    ea = EA.__new__(EA)
    ea.component_pool = object()
    ea.config = EAConfig()
    ind = Individual()
    ind.fitness = [1.0, 0.1, 0.2]
    ind.evaluation_mode = "real_history_reuse_initial"

    original_evaluator = basic_ea_module.Evaluator

    class DummyEvaluator:
        def __init__(self, component_pool, config):
            pass

        def construct_prompt(self, individual):
            return "dummy prompt"

    basic_ea_module.Evaluator = DummyEvaluator
    try:
        ea.log_multi_objective_generation(str(tmp_path), 0, [[ind]])
    finally:
        basic_ea_module.Evaluator = original_evaluator

    contents = (tmp_path / "generation_1_mo.txt").read_text(encoding="utf-8")
    assert "EvalMode: real_history_reuse_initial" in contents


def test_nsga2_pre_real_eval_sort_uses_game_round():
    """Verify pre-real-eval ordering prioritizes the third fitness objective."""
    nsga = NSGA2.__new__(NSGA2)
    a = Individual()
    b = Individual()
    a.fitness = [0.9, 0.9, 0.2]
    b.fitness = [0.1, 0.1, 0.8]

    ordered = nsga._sort_by_game_round_score([a, b])

    assert ordered[0] is b


def test_nsga2_pre_real_eval_sort_only_uses_offspring():
    """Verify that pre-real-eval ordering is applied only to offspring candidates."""
    nsga = NSGA2.__new__(NSGA2)
    parent = Individual()
    child_low = Individual()
    child_high = Individual()

    parent.fitness = [1.0, 1.0, 1.0]
    child_low.fitness = [0.0, 0.0, 0.2]
    child_high.fitness = [0.0, 0.0, 0.9]

    ordered = nsga._sort_by_game_round_score([child_low, child_high])

    assert parent not in ordered
    assert ordered == [child_high, child_low]


def test_steady_state_nsga2_replaces_one_individual_immediately():
    """Verify steady-state NSGA-II inserts one child and trims immediately."""
    nsga = SteadyStateNSGA2.__new__(SteadyStateNSGA2)
    nsga.config = EAConfig(population_size=2)

    parent_a = Individual()
    parent_b = Individual()
    child = Individual()

    parent_a.fitness = [0.1, 0.1, 0.1]
    parent_b.fitness = [0.2, 0.2, 0.2]
    child.fitness = [0.9, 0.9, 0.9]

    next_population = nsga._select_steady_state_survivors([parent_a, parent_b], child)

    assert len(next_population) == 2
    assert child in next_population
    assert parent_a not in next_population
