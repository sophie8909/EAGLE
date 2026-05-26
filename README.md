# EAGLE

EAGLE is a research framework for evolving LLM-controlled MicroRTS strategies with evolutionary algorithms. The current codebase is MicroRTS-first: Python owns configuration, evolution, evaluation orchestration, analysis, and the NiceGUI dashboard; the vendored MicroRTS tree owns Java gameplay execution.

The target reader is a researcher/developer who is comfortable with Python, Java, LLM backends, and EA experiment artifacts.

## 1. Project overview

The active workflow evolves prompt components, evaluates candidate strategies in MicroRTS, records LLM calls and match evidence, and provides GUI/CLI tools for inspection and analysis.

Main entry points:

```bash
./run.sh
python -m eagle_gui_web.app
python -m eagle.main --config configs/evolution/default.json
python -m scripts.run_evolution --config configs/evolution/default.json
```

Run commands from the repository root so relative config, prompt, log, and MicroRTS paths resolve correctly.

## 2. Research goal

EAGLE studies how evolutionary search can improve LLM gameplay agents by changing structured prompt components and evaluating those prompts against MicroRTS scenarios. The framework is built to support experiment iteration, trace inspection, and reproducible analysis rather than polished end-user packaging.

## 3. Architecture overview

The main runtime flow is:

1. Load `EAConfig` from JSON/YAML config or GUI state.
2. Build an experiment config and component pool.
3. Construct GA, NSGA-II, or surrogate variants through the registry.
4. Generate offspring through crossover, mutation, and optional reflection.
5. Evaluate individuals with MicroRTS round surrogate, gameplay, or final-test paths.
6. Write checkpoints, generation logs, profile rows, match records, and LLM JSONL traces.
7. Use the GUI or analysis CLI to inspect saved artifacts.

Current responsibility boundaries are summarized in `docs/architecture_notes.md`.

## 4. Repository structure

```text
eagle/
  main.py                         CLI entry point for evolution runs
  config.py                       EAConfig and config validation
  evolution/component/            GA/NSGA-II core, individuals, checkpoints
  operators/                      mutation, crossover, selection operators
  eval/microrts/                  MicroRTS round, gameplay, final-test evaluators
  envs/microrts/                  Java process/runtime helpers
  domains/microrts/               MicroRTS prompt/parser/adapter helpers
  llm/                            llama.cpp OpenAI-compatible backend
  analysis/                       result loaders, plots, CLI analysis
  utils/                          trace, logging, checkpoint, scoring utilities
eagle_gui_web/                    NiceGUI dashboard
configs/
  evolution/                      active evolution presets
  evaluation/                     final-test and surrogate-validation presets
  experiments/                    GUI/reference experiment configs
scripts/                          CLI wrappers
third_party/microrts/             vendored MicroRTS runtime
docs/                             architecture and developer notes
logs/                             local run outputs
results/                          analysis/benchmark outputs
```

## 5. Requirements

- Python `>=3.10,<3.13`
- Java/JDK with `java` and `javac` on `PATH`
- Python packages from `requirements.txt`
- Optional Conda environment from `environment.yml`
- llama.cpp server with an OpenAI-compatible `/chat/completions` endpoint for LLM-backed paths

The Python package dependencies are also declared in `pyproject.toml`.

## 6. Setup

Recommended Conda setup:

```bash
conda env create -f environment.yml
conda activate eagle
```

Pip setup:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`run.sh` can create/check the Conda environment and install packages:

```bash
./run.sh --setup
```

Start llama.cpp separately when using mutation, crossover repair, reflection, round surrogate LLM scoring, or Java gameplay LLM calls:

```bash
export LLAMA_CPP_MODEL_PATH=/path/to/model.gguf
./run_llama_cpp.sh
```

Python defaults use `LLAMA_CPP_BASE_URL=http://127.0.0.1:8080/v1` and `LLAMA_CPP_MODEL=local`. The Java gameplay agent reads `EAGLE_LLM_BASE_URL` and `EAGLE_LLM_MODEL`.

## 7. Running GUI

Launch the NiceGUI dashboard:

```bash
./run.sh --gui
```

or:

```bash
python -m eagle_gui_web.app
```

The GUI provides experiment configuration, component editing, run control, final-test launching, LLM trace inspection, and analysis display. It uses existing Python services and analyzers; experiment logic should stay in `eagle/`.

## 8. Running experiments from CLI

Run a normal evolution preset:

```bash
python -m eagle.main --config configs/evolution/default.json
```

Run a quick smoke experiment:

```bash
python -m eagle.main --config configs/evolution/quick_test.json --quick-run --skip-final-test
```

Run through the script wrapper:

```bash
python -m scripts.run_evolution --config configs/evolution/default.json
```

Resume the latest run:

```bash
python -m eagle.main --resume-latest
```

Run surrogate validation:

```bash
python -m scripts.run_surrogate_validation --config configs/evaluation/surrogate_validation.json
```

Run prompt/final-test replay:

```bash
python -m scripts.run_prompt_eval --help
```

## 9. Config files

Important config locations:

- `configs/evolution/default.json`: default evolution preset.
- `configs/evolution/quick_test.json`: small smoke-test preset.
- `configs/evaluation/final_test.json`: final-test replay defaults.
- `configs/evaluation/surrogate_validation.json`: surrogate-validation defaults.
- `configs/experiments/`: GUI-generated and named experiment configs.

`EAConfig` in `eagle/config.py` is the active runtime config surface. It validates current algorithm names only: `ga`, `nsga2`, `ga_surrogate`, and `nsga2_surrogate`.

## 10. Component JSON / prompt representation

Prompt components live primarily under:

```text
eagle/prompts/components.json
configs/experiments/*_components.json
```

Individuals store component selections as:

```json
{
  "component_indices": {
    "component_key": {
      "index": 0,
      "enabled": 1
    }
  }
}
```

`ComponentPool` renders selected components into the static strategy prompt. Few-shot examples are managed through the examples pool JSONL when enabled.

## 11. Evaluation modes

Round surrogate:

- Implemented in `eagle/eval/microrts/round_evaluator.py`.
- Generates MicroRTS state prompts, asks the Python LLM backend for actions, validates JSON/actions, and scores legality, resource advantage, and strategy alignment.

Gameplay:

- Implemented through `eagle/eval/microrts/full_game_evaluator.py` and `eagle/envs/microrts/runner.py`.
- Runs Java MicroRTS games with selected opponents and records match/profile artifacts.

Final test:

- Implemented in `eagle/eval/microrts/final_test_runner.py`, `final_test_batch.py`, and `final_test_report.py`.
- Replays selected prompts/individuals against configured maps and opponents, then writes final-test `results.json` artifacts for analysis.

## 12. LLM backend

Python LLM calls use `eagle/llm/llama_cpp.py` and an OpenAI-compatible llama.cpp endpoint:

```text
<base_url>/chat/completions
```

The Java gameplay agent is:

```text
third_party/microrts/src/ai/eagle/EAGLE.java
```

It loads the runtime prompt, calls the llama.cpp-compatible chat endpoint, parses action JSON, and converts accepted moves into MicroRTS actions.

## 13. Trace and logs

The intended LLM trace path is:

```text
<run_dir>/llm_calls/generation_<generation>.jsonl
```

Trace modes:

- `mutation`
- `crossover`
- `reflection`
- `round_surrogate`
- `gameplay`

Trace records should include `timestamp`, `generation`, `individual_id`, `call_index`, `mode`, `caller` or `source` when available, `turn`, `model`, `input`, `raw_response_body`, `parsed_response`, `final_response`, `fallback_response`, `error`, and `metadata`. Current writers may also include `opponent`, `prompt_chars`, `input_tail`, and `request_payload`.

Common run artifacts are under:

```text
logs/eagle/<run_id>/
logs/microrts/
```

The GUI LLM Calls page reads generation JSONL traces first, then falls back to older debug/prompt records when needed.

## 14. Analysis page / MO analysis

The GUI Analysis page wraps the existing analysis pipeline. CLI analysis entry point:

```bash
python -m eagle.analysis.run_analysis_cli --run-dir logs/eagle/<run_id> --type evolution
python -m eagle.analysis.run_analysis_cli --run-dir logs/eagle/<run_id> --type mo
python -m eagle.analysis.run_analysis_cli --run-dir logs/eagle/<run_id> --type final_test
```

Generated artifacts are written under the selected run directory, usually in `analysis/evolution/`.

## 15. Common debugging commands

Check syntax:

```bash
python -m compileall eagle eagle_gui_web
```

List run folders:

```bash
ls logs/eagle
```

Inspect LLM traces:

```bash
ls logs/eagle/<run_id>/llm_calls
head -n 1 logs/eagle/<run_id>/llm_calls/generation_0.jsonl
```

Run a fast evolution smoke test:

```bash
python -m eagle.main --config configs/evolution/quick_test.json --quick-run --skip-final-test
```

Export a final prompt:

```bash
python -m scripts.export_final_prompt --help
```

## 16. Development notes

- Keep MicroRTS-specific code explicit; do not add generic environment adapters before a second environment exists.
- Keep GUI code thin. Use `eagle_gui_web/services.py` to call existing config, run, trace, and analysis logic.
- Do not change `results.json` or final-test schemas during analysis-only work.
- Keep LLM trace logging best-effort: trace failures should not change evaluation behavior.
- Use Conventional Commits for commits.
