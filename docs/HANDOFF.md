# Handoff

## Current Runnable Command

```bash
python scripts/run_eagle.py --config configs/eagle_minimal.yaml --mock
```

The mock run exercises:

- NSGA-II initialization, prompt crossover, prompt mutation, Pareto ranking, and crowding distance
- prompt-to-Java generation path seeded by `microrts_blank_strategy_agent`
- mock compile adapter
- mock MicroRTS match adapter
- game-performance and strategy-alignment objectives
- full per-individual artifact saving

## Mock Mode

`--mock` forces:

- `MockGenerationBackend`
- mock compile success
- deterministic mock MicroRTS match payloads with resource metrics
- deterministic mock strategy-alignment scoring

This mode does not require `javac`, MicroRTS, or a live LLM endpoint.

The initial prompt starts from the known-good MicroRTS `ai.RandomAI` structure. Future generated agents should edit only the `chooseAction` strategy body while the scaffold keeps imports, class shell, `getAction`, `clone`, and parameters fixed.

## Real MicroRTS Mode Status

Real adapters exist but still need environment validation:

```bash
python scripts/run_eagle.py --config configs/eagle_50x10.yaml
```

Expected real-mode dependencies:

- an OpenAI-compatible LLM endpoint at `llm_base_url`
- a reachable model name in `llm_model`
- `javac`
- vendored MicroRTS under `third_party/microrts`

The MicroRTS command currently targets `rts.MicroRTS` with a JSON-result flag. Confirm the exact batch evaluation class and result contract before treating real-mode results as final.

## Next Steps

1. Run one real generation against the local LLM endpoint and inspect generated Java quality.
2. Confirm and, if needed, adjust the MicroRTS evaluation command.
3. Add stronger Java safety validation after the real generation style is observed.
4. Replace simple text variation with prompt-aware mutation/crossover only if it improves measured search behavior.
