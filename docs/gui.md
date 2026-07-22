# EAGLE GUI

The EAGLE GUI is a NiceGUI interface over the current prompt-to-Java EA
pipeline. It restores the previous `eagle_ui` framework and visual style while
using the generated-agent configuration, prompt builders, CLI entrypoint, and
Phase 4 artifacts as the canonical backend.

## Launch

Install the project dependencies and start the application from the repository
root:

```bash
python3 -m pip install -e .
python3 -m eagle_ui
```

The GUI opens in the default browser. Closing it through **Close GUI** stops the
NiceGUI server. If the GUI owns an active CLI child process, shutdown also
terminates that child so it cannot remain hidden.

## Pages

- **Run** loads one canonical experiment config, exposes the supported
  population/generation/seed/map/run-directory fields, validates and explicitly
  saves edits, and starts `scripts/run_eagle.py` outside the UI event loop. It
  shows combined stdout/stderr, generation/candidate progress, success/failure
  counts, and the resolved run directory.
- **LLM Roles** edits `reflector`, `rewriter`, and `generator` in the endpoint
  handoff file. Each role has its own enabled state, URL, model, timeout,
  context size, temperature, maximum output tokens, and server label. Multiple
  roles may use the same values. The connection action requests `/health` and
  `/v1/models` without issuing a completion.
- **Prompts** separates initial strategy prompts, seed Java context, and final
  generation instructions. Its preview calls `Candidate.generation_input`.
  The meta-prompt editor lists stable IDs, roles, stages, source paths, required
  placeholders, validation errors, and mock-context previews.
- **Runs & Candidates** lazily opens one candidate from a discovered `runs/`
  directory and shows lineage, objectives, prompts, LLM output, Java sources,
  validation/compilation/integration diagnostics, matches, failures, timing,
  and paths.
- **Objectives** filters stored candidate records, renders a jittered generation
  distribution with mean/median, an interactive objective scatter, the
  nondominated candidates, and generation statistics.
- **Errors** filters normalized failure records, shows category percentages,
  generation trends, grouped root causes, candidate evidence, and exports the
  filtered table to CSV or JSON under a caller-selected path.

## Module structure

```text
eagle_ui/
  app.py
  state.py
  controllers/
    run_controller.py
    llm_controller.py
    prompt_controller.py
    artifact_controller.py
    analysis_controller.py
    error_controller.py
  views/
    run_view.py
    llm_view.py
    prompt_view.py
    candidate_view.py
    analysis_view.py
    error_view.py
  components/
    log_panel.py
    run_selector.py

eagle/analysis/
  records.py
  objectives.py
  errors.py
  plots.py
```

Views own widgets only. Controllers translate UI actions into canonical service
calls. `eagle.analysis` is UI-independent and is shared with command-line
analysis where applicable.

## Canonical configuration

| Concern | Canonical source |
| --- | --- |
| EA settings and initial strategy/generation prompt | selected `configs/*.yaml` |
| LLM endpoints and role assignments | `config/llm_endpoints.toml` |
| LLM handoff example | `config/llm_endpoints.toml.example` |
| Meta prompts | `config/prompt_templates.toml` |
| Seed complete Java context | `eagle/java_templates/CandidateAgent.java` or selected `agent_template_path` |

The launcher scripts may still write legacy `[general]` and `[coder]` endpoint
sections. The role loader maps reflection/rewrite to `general` and generation to
`coder` when explicit `[roles.*]` sections do not exist. Saving the GUI form
adds explicit role sections while preserving unrelated sections and comments.

Edited values remain in widgets until **Save** is selected. Starting an EA run
is rejected when Run-page edits differ from the last loaded/saved config. It
does not silently write temporary settings or overwrite repository defaults.
Every new run stores `resolved_config.json`, the selected `config.yaml`, and
`prompt_snapshot.json` with the effective LLM routing, prompt bodies, and source
hashes.

## Prompt behavior

The current meta-prompt IDs are:

- `strategy_reflection`
- `code_reflection`
- `strategy_rewrite`
- `code_rewrite`
- `java_generation`
- `strategy_alignment`

Uniform crossover has no separate LLM prompt: it selects the three candidate
components, then the shared `java_generation` template performs crossover final
generation. This usage is recorded in that template's `stages` metadata.

The GUI validates missing required placeholders, unsupported placeholders,
malformed `$name` syntax, and empty templates. It never embeds stage prompt text
in widget code.

## Run and candidate artifacts

Run discovery reads `results.jsonl`, `resolved_config.json`, and `summary.json`.
Candidate inspection uses the documented paths in
`eagle.analysis.records.CANDIDATE_ARTIFACT_PATHS`, including:

- `individual.json`, `lineage.json`, and `prompt.json`
- `generation/response_raw.txt`, extracted Java, and normalized Java
- validation, compilation, and integration result JSON
- match, game-metric, code-quality, and objective artifacts
- `result.json`, mutation metadata, and timing

`individual.json` is required for a selected candidate. Other files are
optional; missing optional artifacts render as empty or unavailable without
hiding the artifacts that do exist. Opening a run or candidate never mutates
it.

## Objective analysis

The EA objectives remain `game_performance` and `code_quality`. The GUI also
exposes stored code-quality components when present: compilation score,
function capability, and strategy alignment. It never recomputes those values.

Optimization directions are read from `resolved_config.json` and fall back to
`evaluation.nsga2_objectives.OBJECTIVE_DIRECTIONS`. The Pareto calculation
supports both maximize and minimize directions. Generation statistics contain
min, max, mean, median, success count, and failure count.

## Error analysis

`eagle.analysis.errors` is the single normalization layer used by the GUI and
the existing run-analysis CLI. Existing artifact categories remain valid;
normalization adds more specific context-overflow, timeout, response-parsing,
and artifact failures when the evidence supports them. Unknown categories are
not discarded. Compiler root causes reuse the same javac grouping as the CLI.

Exports contain only the currently filtered derived table and do not change
the source artifacts.

## Limitations

- The current EA runner has no checkpoint-safe stop/resume API, so the Run page
  intentionally does not expose a Stop button. GUI shutdown prevents an owned
  child process from being orphaned, but this is emergency lifecycle cleanup,
  not resumable cancellation.
- Evaluation opponent and ten-match semantics are fixed by the current
  canonical pipeline and are displayed rather than independently reimplemented.
- Run summaries stream `results.jsonl`, while selected candidate evidence is
  loaded lazily. Extremely large result files are not indexed in a database.
- Endpoint testing depends on a currently running reachable llama.cpp server.
- GUI tests cover controllers and analysis logic; browser-rendering assertions
  are intentionally minimal.
