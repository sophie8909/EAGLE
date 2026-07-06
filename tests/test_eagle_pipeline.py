import json
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig, parse_minimal_yaml
from eagle.search import run_search
from eagle.selection import dominates
from evaluation.game_metrics import compute_game_metrics
from evaluation.microrts_runner import MatchResult
from generation.agent_template import microrts_blank_strategy_prompt
from generation.backend import MockGenerationBackend, generated_class_name
from generation.java_agent_generator import (
    clean_generated_java_output,
    generate_java_agent,
    normalize_java_agent_source,
    validate_java_agent_source,
)


class EaglePipelineTests(unittest.TestCase):
    def test_parse_minimal_yaml(self) -> None:
        payload = parse_minimal_yaml(
            """
seed_prompts:
  - "Generate an agent."
generations: 2
population_size: 3
"""
        )
        self.assertEqual(payload["seed_prompts"], ["Generate an agent."])
        self.assertEqual(payload["generations"], 2)
        self.assertEqual(payload["population_size"], 3)

    def test_mock_generation_returns_valid_java_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Candidate(strategy_prompt="Generate an agent.")
            agent = generate_java_agent(candidate, MockGenerationBackend(), Path(temp_dir))
            self.assertIn("package ai.generated;", agent.source)
            self.assertIn("extends AbstractionLayerAI", agent.source)
            self.assertIn("private void defineStrategy", agent.source)
            self.assertIn("STRATEGY LOGIC GOES HERE", agent.source)

    def test_seed_prompt_template_expands_to_blank_strategy_prompt(self) -> None:
        config = ExperimentConfig.from_mapping({"seed_prompt_template": "microrts_blank_strategy_agent"})
        self.assertEqual(len(config.seed_prompts), 1)
        self.assertEqual(config.seed_prompts[0], microrts_blank_strategy_prompt())
        self.assertIn("Available high-level operations", config.seed_prompts[0])
        self.assertIn("STRATEGY LOGIC GOES HERE", config.seed_prompts[0])

    def test_mock_search_writes_nsga2_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "seed_prompts:",
                        '  - "Generate a Java MicroRTS economy agent."',
                        '  - "Generate a Java MicroRTS defensive agent."',
                        "generations: 2",
                        "population_size: 3",
                        "crossover_rate: 1.0",
                        "mutation_rate: 1.0",
                        'generation_backend: "mock"',
                        'alignment_backend: "mock"',
                        f'runs_dir: "{(root / "runs").as_posix()}"',
                        "matches_per_candidate: 1",
                    ]
                ),
                encoding="utf-8",
            )
            config = ExperimentConfig.from_file(config_path)
            result = run_search(config, config_path=config_path, mock=True, run_id="test_run")
            self.assertTrue((result.run_dir / "config.yaml").exists())
            self.assertTrue((result.run_dir / "candidates").is_dir())
            self.assertTrue((result.run_dir / "generated_agents").is_dir())
            self.assertTrue((result.run_dir / "results.jsonl").exists())
            summary = json.loads((result.run_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["objectives"], ["game_performance", "strategy_alignment"])
            self.assertEqual(len(summary["final_population"]), 3)
            candidate_dir = next((result.run_dir / "candidates").iterdir())
            self.assertTrue((candidate_dir / "strategy_prompt.txt").exists())
            self.assertTrue((candidate_dir / "generated_java_source.java").exists())
            self.assertTrue((candidate_dir / "compile_result.json").exists())
            self.assertTrue((candidate_dir / "raw_microrts_result.json").exists())
            self.assertTrue((candidate_dir / "game_metrics.json").exists())
            self.assertTrue((candidate_dir / "strategy_alignment.json").exists())
            self.assertTrue((candidate_dir / "objectives.json").exists())

    def test_generate_java_agent_uses_candidate_class_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Candidate(strategy_prompt="Generate a Java MicroRTS agent.")
            agent = generate_java_agent(candidate, MockGenerationBackend(), Path(temp_dir))
            self.assertEqual(agent.class_name, generated_class_name(candidate.id))
            self.assertTrue(agent.source_path.exists())

    def test_clean_generated_java_output_strips_markdown_fences(self) -> None:
        output = """Here is the Java:
```java
package ai.generated;

import rts.units.UnitTypeTable;

public class GeneratedAgent_test {
    public GeneratedAgent_test(UnitTypeTable utt) {
    }
}
```
Done.
"""
        cleaned = clean_generated_java_output(output)
        self.assertNotIn("```", cleaned)
        self.assertTrue(cleaned.startswith("package ai.generated;"))
        self.assertTrue(cleaned.endswith("}"))

    def test_validate_java_agent_source_rejects_non_java_output(self) -> None:
        with self.assertRaisesRegex(ValueError, "class declaration"):
            validate_java_agent_source("Here is a strategy explanation with no Java.", "GeneratedAgent_test")

    def test_validate_java_agent_source_rejects_nonexistent_helper(self) -> None:
        source = """package ai.generated;

import rts.units.UnitTypeTable;

public class GeneratedAgent_test {
    public GeneratedAgent_test(UnitTypeTable utt) {
    }

    private void defineStrategy() {
        nearestIdleAlly(null, 0, null);
    }
}
"""
        with self.assertRaisesRegex(ValueError, "nearestIdleAlly"):
            validate_java_agent_source(source, "GeneratedAgent_test")

    def test_validate_java_agent_source_rejects_direct_unit_iteration(self) -> None:
        source = """package ai.generated;

import rts.units.UnitTypeTable;

public class GeneratedAgent_test {
    public GeneratedAgent_test(UnitTypeTable utt) {
    }

    private void defineStrategy() {
        for (Object unit : pgs.getUnits()) {
        }
    }
}
"""
        with self.assertRaisesRegex(ValueError, "copy game units"):
            validate_java_agent_source(source, "GeneratedAgent_test")

    def test_validate_java_agent_source_accepts_existing_helper_usage(self) -> None:
        source = """package ai.generated;

import rts.units.UnitTypeTable;

public class GeneratedAgent_test {
    public GeneratedAgent_test(UnitTypeTable utt) {
    }

    private void defineStrategy() {
        commandIdle(null);
    }

    private boolean commandIdle(Object unit) {
        return true;
    }
}
"""
        validate_java_agent_source(source, "GeneratedAgent_test")

    def test_clean_generated_java_output_preserves_valid_java_source(self) -> None:
        source = """package ai.generated;

import ai.RandomBiasedAI;
import rts.units.UnitTypeTable;

public class GeneratedAgent_test extends RandomBiasedAI {
    public GeneratedAgent_test(UnitTypeTable utt) {
        super(utt);
    }
}
"""
        self.assertEqual(clean_generated_java_output(source), source.strip())

    def test_normalize_java_agent_source_repairs_common_llm_imports(self) -> None:
        source = """package ai.generated;

import ai.RandomBiasedAI;
import ai.UnitTypeTable;

public class GeneratedAgent_test extends RandomBiasedAI {
    public GeneratedAgent_test(UnitTypeTable utt) {
        super(utt);
    }

    @Override
    public void act() {
    }
}
"""
        normalized = normalize_java_agent_source(source)
        self.assertIn("import rts.units.UnitTypeTable;", normalized)
        self.assertNotIn("import ai.UnitTypeTable;", normalized)
        self.assertNotIn("@Override\n    public void act", normalized)

    def test_normalize_repairs_elided_abstraction_helpers(self) -> None:
        source = """package ai.generated;

import ai.abstraction.AbstractionLayerAI;
import ai.abstraction.pathfinding.AStarPathFinding;
import ai.abstraction.pathfinding.PathFinding;
import ai.core.AI;
import rts.GameState;
import rts.PhysicalGameState;
import rts.PlayerAction;
import rts.units.Unit;
import rts.units.UnitType;
import rts.units.UnitTypeTable;

public class GeneratedAgent_test extends AbstractionLayerAI {
    protected UnitTypeTable utt;
    protected UnitType resourceType;
    protected UnitType workerType;
    protected UnitType baseType;
    protected UnitType barracksType;

    public GeneratedAgent_test(UnitTypeTable aUtt) {
        this(aUtt, new AStarPathFinding());
    }

    public GeneratedAgent_test(UnitTypeTable aUtt, PathFinding aPf) {
        super(aPf);
        reset(aUtt);
    }

    public void reset(UnitTypeTable aUtt) {
        utt = aUtt;
        resourceType = utt.getUnitType("Resource");
        workerType = utt.getUnitType("Worker");
        baseType = utt.getUnitType("Base");
        barracksType = utt.getUnitType("Barracks");
    }

    @Override
    public AI clone() {
        return new GeneratedAgent_test(utt, pf);
    }

    @Override
    public PlayerAction getAction(int player, GameState gs) throws Exception {
        applyAutoDefense(player, gs);
        return translateActions(player, gs);
    }

    private void defineStrategy(int player, GameState gs) {
        PhysicalGameState pgs = gs.getPhysicalGameState();
        Unit base = ownBase(player, pgs);
        if (base != null) {
            commandTrain(base, workerType);
        }
    }

    // Helper methods...
}
"""
        normalized = normalize_java_agent_source(source)
        self.assertIn("private boolean commandMove", normalized)
        self.assertIn("private void applyAutoDefense", normalized)
        self.assertIn("public List<ParameterSpecification> getParameters()", normalized)
        self.assertNotIn("Helper methods...", normalized)

    def test_game_metrics_use_resource_difference(self) -> None:
        result = MatchResult(
            ok=True,
            score=0.5,
            command=[],
            raw_result={"winner": 0, "final_scoreboard": {"p0_resources": 14, "p1_resources": 8}},
        )
        metrics = compute_game_metrics([result])
        self.assertEqual(metrics.resource_difference, 6)
        self.assertGreater(metrics.objective, 6)

    def test_dominates_uses_two_objectives(self) -> None:
        strong = Candidate(fitness_objectives={"game_performance": 2, "strategy_alignment": 0.8})
        weak = Candidate(fitness_objectives={"game_performance": 1, "strategy_alignment": 0.8})
        tradeoff = Candidate(fitness_objectives={"game_performance": 3, "strategy_alignment": 0.2})
        self.assertTrue(dominates(strong, weak))
        self.assertFalse(dominates(strong, tradeoff))


if __name__ == "__main__":
    unittest.main()
