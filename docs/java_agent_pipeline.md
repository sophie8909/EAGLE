# Java Agent Pipeline

EAGLE now treats Java-agent generation as a sequence of small stages. The goal is to make failed candidates easy to inspect.

## Stages

1. Prompt/input building
   - Owned by `generation/backend.py`.
   - The backend prompt asks for only the body of `chooseAction(int player, GameState gs)`.

2. LLM generation
   - Owned by the configured `GenerationBackend`.
   - The raw text is saved in `CandidateResult.raw_llm_output`.

3. Output extraction
   - Owned by `generation/java_agent_generator.py`.
   - `extract_code_from_output()` removes wrappers and keeps only strategy-body code.

4. Java assembly
   - Owned by `generation/agent_template.py`.
   - The scaffold is based directly on MicroRTS `ai.RandomAI`.
   - The scaffold owns imports, class shell, constructors, `reset`, `clone`, `getAction`, and `getParameters`.
   - The LLM owns only statements inside `chooseAction`.
   - This RandomAI-based scaffold is the known-good Java agent starting point. Future generated agents should edit strategy logic from this baseline.

5. Java validation
   - Owned by `generation/java_agent_generator.py`.
   - The generated body must not define imports, classes, fields, helper methods, `Optional`, `StrategyTable`, streams, or lambdas.
   - Unit loops must not iterate directly over `gs.getUnits()` or `pgs.getUnits()`.

6. Java compilation
   - Owned by `evaluation/compiler.py`.
   - Compile errors are stored in `compile_result.json` and `CandidateResult.compile_result`.

7. Match evaluation
   - Owned by `evaluation/microrts_runner.py` and coordinated in `eagle/evaluation.py`.
   - Match outputs are stored in `raw_microrts_result.json` and `CandidateResult.match_result`.

8. Scoring/result recording
   - Failure-to-score mapping lives in `evaluation/nsga2_objectives.py`.
   - Any failure category receives `game_performance = -1000.0` and `strategy_alignment = 0.0`.
   - Artifacts are written by `eagle/artifacts.py`.

## Failure Categories

- `Backend request failure`
- `Java validation failure`
- `Java compile failure`
- `Runtime match failure`
- `Timeout`
- `Other`

## Debugging

For each failed candidate, inspect:

- `runs/<run_id>/failed_candidates/<candidate_id>/raw_llm_output.txt`
- `runs/<run_id>/failed_candidates/<candidate_id>/extracted_code.java`
- `runs/<run_id>/failed_candidates/<candidate_id>/assembled_java.java`
- `runs/<run_id>/failed_candidates/<candidate_id>/failure.json`

The normal per-candidate folder still contains:

- `strategy_prompt.txt`
- `candidate_result.json`
- `compile_result.json`
- `raw_microrts_result.json`
- `objectives.json`
- `individual.json`
