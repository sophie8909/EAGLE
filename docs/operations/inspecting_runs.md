# Inspecting EAGLE runs

Use `./analyze.sh` to select the latest valid direct child of the configured
run root, or pass one explicit relative or absolute canonical run folder:

```bash
./analyze.sh
./analyze.sh runs/20260728_143000_eagle
./analyze.sh /home/mhlab/EAGLE/runs/20260728_143000_eagle
```

A canonical run is identified by a supported `manifest.json`, a supported
resolved configuration, and either a completed generation or an initialized
run status. Latest selection prefers `manifest.last_update_time` and falls
back to directory mtime.

Derived Markdown, JSON, CSV, and static Matplotlib plots are written under
`RUN_DIR/analysis/`. The canonical loader reads compact generation, final
population, timing, and error artifacts. It never reads `results.jsonl`.

Historical layouts are rejected. They require an explicit migration command:

```bash
python -m eagle migrate-run RUN_DIR
```
