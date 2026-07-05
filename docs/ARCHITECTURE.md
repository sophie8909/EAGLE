# Architecture

EAGLE evolves strategy prompts with NSGA-II. The LLM is used before evaluation to generate Java MicroRTS agents. It is not part of runtime game control.

## Pipeline

1. `eagle.search` initializes a population of `strategy_prompt` candidates. The default seed comes from `seed_prompt_template: "microrts_blank_strategy_agent"` and describes MicroRTS, legal high-level operations, and a blank Java strategy skeleton.
2. NSGA-II variation creates offspring through prompt crossover and mutation.
3. `generation/java_agent_generator.py` sends each prompt to a generation backend, extracts Java source, validates the generated class shape, and writes an isolated source file.
4. `evaluation/compiler.py` compiles the generated Java source.
5. Compile failures receive worst objectives and persist compiler output.
6. Compile successes run MicroRTS matches through `evaluation/microrts_runner.py`.
7. `evaluation/game_metrics.py` parses raw match results and computes the game-performance objective from resource difference plus available match metrics.
8. `evaluation/strategy_alignment.py` asks an LLM to compare the strategy prompt, generated Java code, and optional match summary. Mock mode uses a deterministic local scorer.
9. `evaluation/nsga2_objectives.py` converts compile, game, and alignment results into the two maximized NSGA-II objectives.
10. `eagle.search` performs non-dominated sorting and crowding-distance survivor selection.

## Candidate Representation

Each NSGA-II individual is an `eagle.candidate.Candidate` with:

- `strategy_prompt`
- `generated_java_agent_path`
- `compile_status`
- `game_eval_result`
- `strategy_alignment_result`
- `fitness_objectives`

The active objective names are:

- `game_performance`: higher is better. Successful matches use resource difference plus available win/loss and score signals. Compile or match failures get `-1.0`.
- `strategy_alignment`: higher is better. LLM alignment score in `[0, 1]`; compile failures get `0.0`.

Objectives remain separate. EAGLE does not collapse them into one scalar for NSGA-II selection.

## Initial Prompt Template

`generation/agent_template.py` owns the built-in initial prompt. It intentionally avoids a concrete strategy such as rush, turtle, or economy-first. Instead, it gives the LLM:

- MicroRTS unit and resource basics
- available `AbstractionLayerAI` operations: `move`, `harvest`, `train`, `build`, `attack`, and `idle`
- a compilable Java agent skeleton copied from the old runtime-agent action style but stripped of runtime LLM, HTTP, file, and logging behavior
- a blank `defineStrategy` method where evolved strategy logic should be inserted

## Artifact Flow

Each run writes:

```text
runs/<run_id>/
  config.yaml
  results.jsonl
  summary.json
  generation_001_population.json
  generated_agents/<candidate_id>/src/ai/generated/*.java
  classes/<candidate_id>/
  candidates/<candidate_id>/
    strategy_prompt.txt
    generated_java_source.java
    compile_result.json
    raw_microrts_result.json
    game_metrics.json
    strategy_alignment.json
    objectives.json
    individual.json
```

## Runtime Boundary

Generated Java agents are ordinary MicroRTS AIs. The generation prompt asks for code that avoids runtime network, file, or LLM APIs, and source validation rejects common runtime LLM/network patterns. The archived runtime-control design is not active.
