# EAGLE Model Registry

This directory is the local model index for the EAGLE experiment environment.

Run:

```bash
./experiment_env/start.sh
```

Then choose `Discover and organize models`.

Discovery writes `model_registry.local.json` and creates per-model directories containing symbolic links such as `model.gguf`, optional `mmproj.gguf`, and shard links. The scripts do not copy, move, delete, download, convert, or quantize model weights.

The registry and generated model links are machine-local and ignored by Git. Keep this README tracked so every checkout has the expected directory shape.
