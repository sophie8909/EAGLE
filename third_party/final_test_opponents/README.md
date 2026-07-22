# Final-test champion dependencies

This directory owns only post-evolution opponents. Champion code is never copied into
the EAGLE Python packages or `third_party/microrts/src`.

Prepare all three pinned opponents from WSL with:

```bash
python3 scripts/setup_final_test_opponents.py
```

The setup command checks out the exact commits in `manifest.toml`, rebuilds each JAR
from pinned Java source against the vendored MicroRTS runtime, discovers concrete
MicroRTS AI classes from the resulting JAR, verifies the documented upstream
entrypoint can be loaded and instantiated, and writes `resolved_manifest.json`.
It never substitutes a baseline bot and fails if any opponent cannot be prepared.

TMA's upstream `TMA.jar` contains Java source rather than compiled classes. Mayari's
upstream repository contains both source and a prebuilt JAR. COAC contains source
only. EAGLE therefore rebuilds all three from source and records available upstream
archive hashes for comparison.

At the pinned revisions, none of the three repositories contains a repository-level
`LICENSE`, `COPYING`, or `NOTICE` file. Their source and generated JARs are consequently
downloaded for local evaluation only and are ignored by Git. EAGLE does not
redistribute them. Review upstream terms before using the downloaded code outside
this reproducibility workflow.
