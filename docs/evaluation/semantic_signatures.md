# Semantic signatures

Self-play uses deterministic full-agent behavior signatures only to preserve
behavioral diversity among candidates whose Game Performance is effectively
equal. They are not a second objective.

## Dataset

`evaluation/semantic_signature.py` creates one versioned dataset from exactly
the three configured evaluation maps. `WorkerRush` versus `HeavyRush` supplies
the deterministic reference trajectory. For the configured player side, one
actionable non-terminal state is saved for each early, middle, and late phase,
giving nine probes. Each manifest records map/state hashes, target and actual
cycles, player side, phase fractions, reference agents, and normalization
version. The serialized `GameState` is reloaded before use.

## Candidate signature

A fresh compiled full `CandidateAgent` instance receives each state and returns
one `PlayerAction`. Unit actions are sorted by unit ID and represented with only
stable action fields before hashing. A candidate summary contains the ordered
probe IDs, nine action hashes, global hash, and map/phase hashes. Exact equality
defines equivalence; normalized Hamming distance over compatible ordered hashes
defines diversity.

The cache key includes phenotype source hash, dataset hash, and action
normalization version. Full results live in
`archives/semantic_signature_cache/`; each candidate stores a small
`evaluation/semantic_signature.json` wrapper. Probe failure is diagnostic and
produces an unavailable signature rather than changing fitness. Mock mode does
not fabricate signatures.

## Selection and analysis

Self-play forms non-chained scalar-fitness tiers using the tier maximum as the
anchor. A difference of at most `1.0` is a tie. Compatible semantics choose a
different second parent and use seeded max-min selection when a survivor tier
crosses the population boundary. Missing/incompatible evidence is fallback.

`python -m eagle analyze --run-dir <run> --semantics` reads artifacts only and
writes `semantic_candidates.csv`, `semantic_probe_signatures.csv`,
`semantic_uniqueness.csv`, and `semantic_library.json`, including global,
per-map, and per-phase exact-equivalence statistics.
