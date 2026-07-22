# EAGLE GUI refactor plan

## Previous GUI

The previous application used NiceGUI and lived in `eagle_ui/`. Commit
`9bb3511c` removed its archived copy from `archive/legacy_runtime/eagle_ui/`
after the generated-Java architecture replaced the legacy runtime. The last
fully available version is in the parent of that commit.

## Reused foundation

- NiceGUI application lifecycle and tabbed layout
- Ravenclaw dashboard theme and responsive card layout
- non-blocking subprocess/log-panel pattern
- run/config selectors and explicit refresh actions
- separation between state, services/controllers, views, and components

## Obsolete responsibilities

- prompt-controlled game-agent execution
- surrogate validation and early-end evaluation modes
- legacy component-pool and example-memory editors
- legacy final-test and prompt replay services
- legacy objective metadata, result schemas, and log-directory guessing

Those backend calls are not restored. The current generated Java pipeline,
Phase 4 artifacts, and `runs/` layout are authoritative.

## New module structure

```text
eagle_ui/
  app.py                 NiceGUI composition and lifecycle
  state.py               selected files, dirty state, run/candidate selection
  controllers/           calls canonical EAGLE and shared analysis services
  views/                 run, LLM, prompt, analysis, error, candidate pages
  components/            selectors, log panel, plot panel, config form helpers
eagle/analysis/
  records.py             read-only run and candidate artifact loading
  objectives.py          objective records, directions, Pareto/statistics
  errors.py              shared failure normalization and summaries
  plots.py               reusable Matplotlib figures
eagle/prompts.py          canonical prompt-template loading/rendering/validation
config/prompt_templates.toml
```

## GUI action mapping

| GUI action | Canonical service or artifact |
| --- | --- |
| Validate/start EA run | `ExperimentConfig.from_file`, `scripts/run_eagle.py` |
| Load/save experiment config | `eagle.config` plus comment-preserving top-level edits |
| Load/save/test LLM roles | `eagle.llm_profiles`, `config/llm_endpoints.toml` |
| Initial prompt preview | `Candidate.generation_input` |
| Meta-prompt preview | `eagle.prompts` builders used by mutation/rewrite/generation/alignment |
| Discover runs | canonical `runs/` directory and run snapshots |
| Inspect candidate | `results.jsonl` and documented per-candidate Phase 4 artifacts |
| Objective/Pareto analysis | stored objectives plus EA objective directions |
| Error analysis/export | stored failure fields through shared normalization |

The GUI never evaluates MicroRTS matches, calculates objective scores, or
constructs stage prompts in widget callbacks.
