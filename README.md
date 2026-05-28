# EAGLE

EAGLE is a reusable research framework for evolving LLM-controlled MicroRTS agents. Python owns experiment configuration, evolutionary search, evaluator orchestration, objective aggregation, trace writing, and analysis. The vendored MicroRTS tree owns Java gameplay execution.

## Quick Start

Run from the repository root:

```bash
./run.sh --setup
./run.sh
```

The GUI entry point is:

```bash
python -m eagle_ui.app
```

The CLI entry point is:

```bash
python -m eagle.main --config configs/evolution/default.json
```

Start a llama.cpp OpenAI-compatible server before using LLM-backed mutation, crossover repair, reflection, round-surrogate scoring, or Java gameplay LLM calls.

## Run An Experiment

Experiment configuration is loaded through `eagle.experiment.config.ExperimentConfig`. JSON files may use the current flat `EAConfig` shape or the canonical envelope:

```json
{
  "algorithm": "nsga2",
  "evaluator": "gameplay",
  "opponents": ["ai.abstraction.LightRush"],
  "evaluator_params": {},
  "ea": {
    "population_size": 8,
    "num_generations": 10
  }
}
```

The runtime resolves the config, builds a component pool, constructs the selected algorithm through the registry, evaluates individuals, aggregates objectives outside evaluators, and writes run artifacts under `logs/eagle/<run_id>/`.

## Extension Points

### Add An Evaluator

Implement `eagle.eval.base.BaseEvaluator.evaluate(individual, context) -> EvaluationResult`.

Return raw measurements in `EvaluationResult.metrics` and file paths in `EvaluationResult.artifacts`. Do not aggregate objectives inside the evaluator.

Register the evaluator with `eagle.core.registry.EVALUATORS` or the domain package registry wiring.

### Add An Objective

Create an `Objective` subclass under `eagle/objectives/<domain>/`.

Set `key`, `application`, `eval_modes`, `direction`, and `required_metrics`. Implement `compute(eval_result)` by reading evaluator metrics. Objective selection is controlled by `objective_config` and resolved through `eagle.objectives.registry`.

Single-objective algorithms use one selected objective or a weighted mix. Multi-objective algorithms receive selected objective names from config.

### Add An Operator

Create an operator under `eagle/operators/<type>/` and inherit the matching base class from `eagle.operators.base`.

Operators should support the common facade:

```python
operator.apply(parents, OperatorContext(component_pool=pool, config=config, algorithm=ea))
```

Keep operator-specific settings local to the operator/config. Operators should return modified individuals and should not write logs directly.

### Add An Algorithm

Implement the lifecycle in `eagle.core.algorithm.BaseAlgorithm` or extend the component EA classes under `eagle/evolution/component/`.

Algorithms own parent selection, variation, evaluation scheduling, objective aggregation, survivor selection, and checkpoint timing. Evaluators return `EvaluationResult`; algorithms decide how selected objectives become `individual.fitness`.

Register algorithms through `eagle.core.registry.ALGORITHMS`.

## Log Layout

Run artifacts stay under:

```text
logs/eagle/<run_id>/
  config.json
  run_state.json
  checkpoints.jsonl
  timing_events.jsonl
  profile.jsonl
  match_score_records.jsonl
  llm_calls/
    generation_<n>.jsonl
```

Use `eagle.logging.trace.record(event_type, payload, context)` for new trace events and `eagle.logging.checkpoints` for checkpoint writes. Preserve this layout for resume compatibility.

## Reproduce Paper Experiments

Use committed configs under `configs/evolution/` and keep the component pool path fixed. Record the exact config, git commit, opponents, maps, llama.cpp model, and MicroRTS runtime settings with the run artifacts.

Typical command:

```bash
python -m eagle.main --config configs/evolution/default.json
```

Analyze a completed run with:

```bash
python -m eagle.analysis.run_analysis_cli --run-dir logs/eagle/<run_id>
```

Final-test workflows use the existing MicroRTS evaluation scripts and write analysis artifacts beside the selected run.

## Repository Map

```text
eagle/core/                  framework interfaces and registries
eagle/experiment/            ExperimentConfig loading/saving
eagle/evolution/component/   GA/NSGA-II runtime and Individual implementation
eagle/eval/microrts/         round, surrogate, gameplay, final-test evaluators
eagle/objectives/            objective plugins and registry
eagle/operators/             mutation, crossover, selection operator plugins
eagle/logging/               trace and checkpoint writers
eagle/analysis/              result loading, plotting, and analysis CLI
eagle/envs/microrts/         Java process helpers
eagle_ui/                    NiceGUI dashboard over the same config/runtime paths
third_party/microrts/        vendored Java runtime
```
