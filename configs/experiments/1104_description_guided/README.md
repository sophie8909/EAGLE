# Description-guided framework initialization

The new opt-in mode is `framework.initial_strategy_mode: llm_plus_authored`.
It uses the configured experiment LLM to generate one new strategy description
for initial individual 0, then uses the nine existing non-WorkerRush profiles
for individuals 1–9. A separate Coach stage fills every individual's complete
24-slot genome from its description. No real LLM run has been executed for this
change. Local evolution after generation zero retains crossover and mutation.

This config is a new experiment (seeds 8–10, population 10, 100 generations),
not a continuation of the historical 1030 ablation. Start the configured server
separately before executing a real experiment:

```powershell
python -m eagle server --config configs/experiments/1104_description_guided/experiment.yaml
python -m eagle experiment --config-dir configs/experiments/1104_description_guided/experiment.yaml
```

`bundle.json` preserves the exact original framework bytes and expected SHA-256
`f674a580f0db088bd3436232d2dd36d071a231c9886f480a7aaed25669203e2b`.
The local `.gitattributes` prevents Git from changing its line endings; this
avoids an existing LF-to-CRLF hash mismatch in the historical bundle checkout.
Neither the framework mechanisms nor its finite slot domains were changed.

Validation: 69 of 70 related regression checks passed; the one failure loads
that unchanged historical bundle and fails its exact-byte hash check. A
provider-free single-generation CLI mock and completed-run resume passed.
Loaded artifacts contain ten distinct initial descriptions, all 24 slot values,
and correct parent-A description inheritance in the ten refreshed parents and
ten offspring. Actual model quality, policy diversity and match performance
remain unmeasured.
