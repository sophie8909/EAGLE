# EAGLE Config Lifecycle

EAGLE uses `eagle.config.EAConfig` as the canonical runtime config model. The
persisted schema is intentionally flat for now because the runtime, GUI, and
MicroRTS backend already consume those field names directly.

For UI, analysis, and plugin-facing code that wants clearer boundaries, use the
typed section view instead of hand-grouping raw dictionaries:

```python
from eagle.config import config_to_sections, config_to_section_payload
```

The section view groups the same canonical config into `experiment`,
`algorithm`, `llm`, `evaluation`, `microrts`, `components`, and `logging`
sections. It is read-only; new config files are still written with the canonical
flat `EAConfig` payload.

## User Config

User configs are JSON or YAML files selected through the GUI or passed with
`python -m eagle.main --config <path>`. They may omit defaults and may use
relative paths. Committed presets live primarily in `configs/evolution/`.
GUI-generated presets are saved under `configs/experiments/`.

The canonical loader is:

```python
from eagle.config import load_config_from_json, load_config_payload
```

`eagle.experiment.config.load_experiment_config` accepts the current experiment
envelope shape and converts its `ea` section into `EAConfig`.

Compatibility is intentionally narrow: the loader accepts the recent
experiment-envelope `ea` shape and maps the old `llm_intervals` key to
`llm_interval`. New configs are always written in the canonical flat field
shape.

## Resolved Config

At run start, the runtime resolves the config with:

```python
from eagle.config import resolve_config, save_resolved_config
```

Resolution fills defaults, validates selectors, and normalizes config-owned
paths such as `component_pool_path`, `surrogate_log_dir`, and
`prompt_history_path` to repo-relative paths when possible.

New runs save:

```text
logs/eagle/<timestamp>/config.resolved.json
logs/eagle/<timestamp>/config.json
```

`config.resolved.json` is the canonical run artifact. `config.json` is kept as
the legacy filename for existing analysis and final-test tools.

## Resume

Resume uses the selected existing run folder:

```text
python -m eagle.main --resume-log-dir logs/eagle/<run> --config logs/eagle/<run>/config.resolved.json
```

When a run folder is loaded, `eagle.config.select_config_path` prefers
`config.resolved.json` and falls back to `config.json`. Resume does not create a
new log folder and does not rewrite the saved run config at launch.

Use `eagle.config.load_resume_config` when the caller specifically needs the
resume contract: resolved-first loading from an existing run directory without
creating or rewriting artifacts.

## GUI

The GUI loads config files through the canonical config loader, applies the
validated payload into the existing form state, and validates generated configs
before writing them. Existing run summaries also prefer the resolved run config.

## MicroRTS

MicroRTS is the active backend selected by `application: microrts`. Its config
fields are still on `EAConfig` because existing runtime code consumes them
directly:

- `agent_class`
- `gameplay_map_dir`
- `gameplay_opponents`
- `tick_limit`
- `llm_interval`
- `llm_call_limit`
- `save_trace_on_test`
- `surrogate_log_dir`
- `prompt_history_path`

The vendored backend root is centralized in `eagle.project.MICRORTS_ROOT`.

## Examples

Single-objective GA:

```json
{
  "algorithm": "ga",
  "objective_config": {
    "mode": "single",
    "objective": "resource_advantage"
  }
}
```

Multi-objective NSGA-II:

```json
{
  "algorithm": "nsga2",
  "objective_config": {
    "mode": "multi",
    "objectives": ["resource_advantage", "win_score"]
  }
}
```
