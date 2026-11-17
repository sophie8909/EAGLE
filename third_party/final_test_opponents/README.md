# Pinned MicroRTS champion dependencies

The search roster and the final test use these locally built JARs.
With Git, Python and JDK 17 available, run the following from the repository root.
The Windows installer also runs this command.

```bash
python3 scripts/setup_final_test_opponents.py
```

The command builds the vendored MicroRTS runtime, checks out the commits pinned
in the manifest, and compiles each opponent JAR against that runtime. It checks
that the expected AI class was built for each opponent.

TMA's upstream `TMA.jar` contains Java source rather than compiled classes. Mayari's
upstream repository contains both source and a prebuilt JAR. COAC contains source
only. EAGLE rebuilds all three from source.


The pinned TMA README identifies its original `strategies` folder as outdated and
instructs users to remove it when the bot does not work. The manifest therefore
builds the unchanged `TMA.java` entrypoint and active `strategiesV2` sources. TMA's
entrypoint retains a stale wildcard import of the old package, so EAGLE supplies the
behavior-free `adapters/tma/ai/tma/strategies/CompatibilityMarker.java` solely to
make that package resolvable by `javac`.
At the pinned revisions, none of the three repositories contains a repository-level
`LICENSE`, `COPYING`, or `NOTICE` file. Their source and generated JARs are consequently
downloaded for local evaluation only and are ignored by Git. EAGLE does not
redistribute them. Review upstream terms before using the downloaded code outside
this reproducibility workflow.
