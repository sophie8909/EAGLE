# AlliBot GUI dependency

AlliBot is an upstream opponent used by EAGLE search evaluation and the GUI
inspection utility. Its upstream implementation ships against its own MicroRTS
source tree; the local resolved JAR and libraries are checked before real
search evaluation.

Prepare the locally ignored dependency with:

```bash
python scripts/setup_allibot.py
```

The setup script pins `drchangliu/MicroRTS` to commit
`ef99dcfe38ecc255928e336869ab95bf4992a931`, copies and adapts the complete
upstream `src/` tree (including AlliBot's dependencies), and writes a local JAR
plus a hash-checked resolution manifest. The adapter sends LLM requests to the
llama.cpp OpenAI-compatible `/v1/chat/completions` endpoint; it never calls
Ollama. The upstream repository is GPL-3.0; source and generated artifacts are
downloaded only for local GUI use and are never committed or redistributed by
EAGLE.

Run it with:

```bash
conda run -n eagle python scripts/run_gui_match.py \
  --run-dir runs/<run_id> --candidate-id <candidate_id> \
  --opponent allibot --cycles 5000 --interval-ms 50
```

By default, EAGLE sets `ALLI_USE_SEARCH_LLM=false` and
`ALLI_SMALLMAP_LLM_ADVISOR=false`, so the GUI match does not make runtime LLM
requests. To enable the configured local llama.cpp server, pass:

```bash
--allibot-runtime-llm \
--allibot-llama-cpp-url http://127.0.0.1:8080 \
--allibot-llama-cpp-model qwen3.5-9b
```

The URL and model default to those values (or `LLAMA_CPP_BASE_URL` and
`LLAMA_CPP_MODEL`), matching `configs/runtime.yaml` by default.
