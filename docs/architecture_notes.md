# EAGLE Architecture Notes

These notes describe the current repository shape for researchers and developers working on the LLM + evolutionary algorithm workflow around MicroRTS.

## Current repository map

- `eagle/main.py` is the CLI entry point for running or resuming evolutionary search. It resolves config input, quick-run overrides, opponents, component pools, algorithm construction, and optional final-test execution.
- `eagle/config.py` defines `EAConfig`, the flat runtime configuration object used by the current experiment pipeline. Defaults are loaded from `configs/evolution/default.json`; validation keeps the active algorithm, objective, surrogate, and MicroRTS runtime settings coherent.
- `eagle/evolution/component/` contains the component-level EA implementation: individuals, GA/NSGA-II loops, parent selection, environment selection, checkpoint/log parsing helpers, and shared algorithm base behavior.
- `eagle/operators/` contains mutation, crossover, reflection, parent-selection, and environment-selection operators used by the component evolution layer.
- `eagle/eval/microrts/` contains MicroRTS-specific evaluation paths, including round surrogate evaluation, full-game evaluation, final-test execution/reporting, generation replay, prompt history, and surrogate validation.
- `eagle/llm/` contains the Python llama.cpp backend wrapper. It sends OpenAI-compatible `/chat/completions` requests and records per-generation LLM trace records when run context is available.
- Trace/logging is not a standalone package in this checkout. The current trace layer is spread across `eagle/utils/llm_call_logger.py`, `eagle/utils/llm_debug.py`, `eagle/eval/microrts/round_evaluator.py`, `eagle/llm/llama_cpp.py`, `third_party/microrts/src/ai/eagle/EAGLE.java`, and the `eagle_ui` LLM Calls view.
- `eagle_ui/` is the NiceGUI interface for configuration, run control, trace inspection, and analysis display. It wraps existing services and analyzers rather than owning experiment logic.
- `third_party/microrts/src/ai/eagle/EAGLE.java` is the active Java gameplay agent used by MicroRTS runs. It loads the prompt, calls a llama.cpp-compatible chat endpoint, translates JSON responses into actions, and writes Java-side LLM trace records when trace metadata is supplied.
- `configs/` stores active experiment, evolution, and evaluation presets. `configs/experiments/` contains GUI-generated and reference experiment configs.
- `scripts/` contains command-line wrappers for running evolution, surrogate validation, prompt evaluation/final test, batch runs, analysis, final-prompt export, and MicroRTS log organization.
- `run.sh`, `run_llama_cpp.sh`, `tmux_services.sh`, and `network_watchdog.sh` are setup/runtime convenience scripts.
- `README.md` is the top-level project guide and should describe current commands and supported workflows only.

## Main runtime flow

1. A config is loaded from the CLI, GUI, or default preset.
2. `eagle.main` builds an experiment config and component pool.
3. `eagle.experiment.runner` constructs the selected GA/NSGA-II algorithm.
4. Evolution operators generate or modify component prompt individuals, optionally using the Python LLM backend.
5. MicroRTS evaluators score individuals through round surrogate evaluation, Java-backed gameplay, or final-test replay.
6. LLM calls are recorded under the active run directory when logging context is available.
7. GUI and analysis modules read run artifacts from disk for inspection and plotting.

## Current responsibility boundaries

- Evolution core: owns population state, generation loops, checkpoint/resume data, component individuals, parent/environment selection, and mutation/crossover/reflection operator orchestration.
- MicroRTS evaluation: owns round surrogate scoring, Java gameplay execution, final-test replay, MicroRTS log parsing, prompt history, scoring records, and validation outputs.
- LLM backend: owns the prompt-in/response-out boundary for Python-side llama.cpp calls. It should not decide EA policy or MicroRTS scoring semantics.
- Trace layer: owns JSONL records for LLM calls and experiment evidence. It records what happened at backend/runtime boundaries without changing evaluation behavior.
- GUI: owns configuration editing, run control, trace inspection, and analysis display. It should call existing services/analyzers instead of duplicating experiment logic.

## LLM trace flow

The intended trace path is one JSON object per LLM call, appended to:

```text
<run_dir>/llm_calls/generation_<generation>.jsonl
```

The call modes should identify the runtime boundary that produced the record:

- `mutation`: Python evolution operator asks the LLM to rewrite component text.
- `crossover`: Python evolution operator asks the LLM to repair or combine component text.
- `reflection`: Python reflection operator asks the LLM to revise a component using evaluation evidence.
- `round_surrogate`: Python round evaluator asks the LLM for a one-state MicroRTS action response, and may make a second judge call for alignment.
- `gameplay`: Java `ai.eagle.EAGLE` agent asks the LLM for actions during a MicroRTS match.

Required JSONL fields:

- `timestamp`
- `generation`
- `individual_id`
- `call_index`
- `mode`
- `caller` or `source` when available
- `turn`
- `model`
- `input`
- `raw_response_body`
- `parsed_response`
- `final_response`
- `fallback_response`
- `error`
- `metadata`

Current records also include practical fields such as `opponent`, `prompt_chars`, `input_tail`, and `request_payload`. Readers should tolerate additional fields because Python and Java traces are written at different runtime boundaries.

## Do not generalize yet

- MicroRTS is currently the only third-party environment supported by this repository.
- Keep MicroRTS-specific assumptions explicit in `eagle/eval/microrts/`, `eagle/envs/microrts/`, `eagle/domains/microrts/`, and the vendored `third_party/microrts/` tree.
- Do not create generic third-party adapters until there is a real second environment with tested requirements.
- Prefer readable MicroRTS-first boundaries over abstract interfaces that only wrap one implementation.
