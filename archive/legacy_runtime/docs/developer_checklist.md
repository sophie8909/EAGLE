# Developer Checklist

## Before running experiments

- Confirm the config path and component JSON path are the intended files.
- Start the llama.cpp server if the run uses LLM-backed mutation, crossover repair, reflection, round surrogate, or gameplay.
- Confirm `java` and `javac` are available before Java-backed MicroRTS runs.
- Use a quick run before long experiments:

```bash
python -m eagle.main --config configs/evolution/quick_test.json --quick-run --skip-final-test
```

## After changing evaluator code

- Run a small config that exercises the changed evaluator mode.
- Check that `eval_result` still contains the objective fields expected by `eagle/objectives/`.
- Inspect one profile or match record in the run directory.

## After changing operators

- Run a quick evolution smoke test.
- Confirm generated individuals keep the `{index, enabled}` component entry shape.
- Check mutation/crossover/reflection trace modes when the operator calls the LLM.

## After changing Java EAGLE agent

- Confirm `third_party/microrts/src/ai/eagle/EAGLE.java` still compiles in the MicroRTS classpath.
- Run one short gameplay match before using it in evolution.
- Inspect `<run_dir>/llm_calls/generation_<generation>.jsonl` for `gameplay` records.

## After changing GUI

- Launch `python -m eagle_ui.app`.
- Check config load/save, run control, final-test controls, LLM Calls, and Analysis for the touched area.
- Keep GUI code as a wrapper around services/analyzers instead of duplicating experiment logic.

## Before committing results

- Keep generated run logs and large analysis artifacts out of code commits unless they are intentionally part of the change.
- Run syntax checks:

```bash
python -m compileall eagle eagle_ui
```

- Review `git diff --stat` for accidental config, log, or result churn.
