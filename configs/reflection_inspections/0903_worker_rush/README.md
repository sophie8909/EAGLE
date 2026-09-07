# Worker Rush reflection inspection

This standalone experiment evaluates the checked-in Worker Rush policy and Java
once, then runs Strategy, Prompt, and Code Reflection independently three times
from the same fixed mutation subject and evidence.

Run the deterministic validation first:

```bash
./reflection_inspection.sh \
  configs/reflection_inspections/0903_worker_rush/inspection.yaml \
  --mock
```

Run the real Ministral experiment:

```bash
./reflection_inspection.sh \
  configs/reflection_inspections/0903_worker_rush/inspection.yaml
```

Each run is written below `runs/reflection_inspections/`. Open `summary.md` for
the manual-review table. Every trial also contains:

- the production mutation artifacts, including each request, raw response,
  parsed output, retry status, and validation error;
- `request_response_index.json`, which inventories every request and response
  attempt with hashes, separating the fixed root request from downstream
  requests that include earlier stochastic role outputs;
- `changes/`, containing diffs for both prompt genes and Java;
- `trial_summary.json`, which checks the actual changed fields against the
  operator contract.

Expected scope:

- Strategy changes only `strategy_prompt`.
- Prompt changes only `generation_prompt`.
- Code directly changes the selected parent Java without changing either prompt.
- No reflection trial changes the inherited Worker Rush Java input.
