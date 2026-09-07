# EAGLE model parameter audit

This audit reconstructs the model and decoding parameters used by EAGLE for
Llama 3.1 8B, Qwen3 8B, Qwen3.5 9B, Ministral 3 8B, and Gemma 3 12B. The
misspellings “ministals” and “gamme” in the audit request are interpreted as
the Ministral and Gemma models actually present in this repository.

The audit distinguishes three sources of behavior:

1. flags passed when EAGLE starts `llama-server`;
2. fields included in the OpenAI-compatible `/v1/chat/completions` request;
3. defaults applied inside the exact llama.cpp build when EAGLE omits a field.

No model was started for this audit. The final request bodies were captured
with a temporary `urllib.request.urlopen` mock, and no implementation or
configuration file was changed.

## Current model setup

All current production experiment configurations use one local llama.cpp
server at `127.0.0.1:8080`. A batch may switch the model between configs, but
only one model process is owned at a time. The four current model configs are:

| Config | Configured model file | GGUF identity | Quantization | Native context metadata | EAGLE context |
|---|---|---|---|---:|---:|
| `configs/experiments/qwen3_5_9b/experiment.yaml` | `experiment_env/model/qwen3-5-9b-ud-q4-k-xl-q4-k-xl-bbcc0f54/model.gguf` | Qwen3.5-9B | UD-Q4_K_XL package; mixed tensor quantization, GGUF `general.file_type` is mostly Q4_K_M | 262144 | 32768 |
| `configs/experiments/qwen3_8b/experiment.yaml` | `experiment_env/model/qwen3-8b-q4-k-m-d7a12a96/model.gguf` | Qwen3 8B AWQ Compatible Instruct | Q4_K_M | 40960 | 32768 |
| `configs/experiments/ministral3_8b/experiment.yaml` | `experiment_env/model/ministral3-8b-instruct-q4-k-m/Ministral-3-8B-Instruct-2512-Q4_K_M.gguf` | Ministral 3 8B Instruct 2512 | Q4_K_M | 262144 | 32768 |
| `configs/experiments/gemma3_12b/experiment.yaml` | `experiment_env/model/gemma3-12b-it-q4-k-m/gemma-3-12b-it-Q4_K_M.gguf` | Gemma 3 12B IT | Q4_K_M | 131072 | 32768 |

The Qwen3.5 path resolves to a Hugging Face cache blob. The other current
paths are ordinary local files. GGUF metadata was read directly. None of the
five audited GGUFs contains `general.sampling.*` metadata, so the current
server does not obtain sampling overrides from these model files.

The current bundled server is:

```text
experiment_env/model/llama.cpp/llama.cpp/build-eagle/bin/llama-server
version 9187, commit 0253fb21f595
```

## Historical setup for Llama 3.1 8B

The preserved completed run `runs/20260816_010853_049949` records commit
`7e7604ca34e7`, backend `openai`, temperature `0.2`, no configured maximum
output token count, and commentator temperature `0.2`. Its model was:

```text
experiment_env/model/meta-llama-3-1-8b-instruct-q4-k-m-q4-k-m-23b52e42/
7b064f5842bf9532c91456deda288a1b672397a54fa729aa665952863033557c
```

Direct GGUF inspection identifies it as Meta Llama 3.1 8B Instruct,
Q4_K_M, with native context metadata 131072. EAGLE launched it with context
32768 and the shared server flags documented below. Llama 3.1 has no current
production config; this is a historical real run.

## Historical setup for Qwen3 8B

The completed real run `runs/20260816_064622_323297` used commit
`7e7604ca34e7` and the same explicit server and request settings as the Llama
run. Only the GGUF path/model identity changed. Qwen3 8B also has a current
production config, with the same effective 32768/8/512/1 server settings and
temperature `0.2`.

## Historical/current setup for Qwen3.5 9B

Qwen3.5 was the sole configured runtime model after commit `65be3259b23`
(`refactor(runtime): reduce EAGLE to qwen3.5`). The completed preserved run
`runs/20260816_134846_209638` used commit `7e7604ca34e7`, temperature `0.2`,
no configured shared maximum output count, and commentator temperature `0.2`.
Earlier real Qwen3.5 runs under commits `59ace…`, `cc2b…`, and `9f54…` show
the same values in their resolved configs.

Qwen3.5 remains a current production config. Its model path changed from being
sent as the request's `model` value in the older runtime to the symbolic name
`qwen3_5_9b` in the current runtime. The server still receives the resolved
GGUF path. llama.cpp uses the already loaded model, so this request-name change
does not change sampling.

One mock smoke run, `runs/20260818_190320_209081`, records temperature `0.0`
and `max_tokens: 8192`. Its generation backend and execution are mock; it is
not evidence of parameters sent to a real llama.cpp server and is excluded
from the effective real-run comparison.

## Historical/current setup for Ministral and Gemma

The completed Ministral run `runs/20260817_123841_424505` used commit
`7e7604ca34e7`. The completed Gemma run `runs/20260818_074603_035419` used
commit `5d8a30d49e5`. Both record backend `openai`, shared temperature `0.2`, no
configured shared maximum output count, and commentator temperature `0.2`.
Both models now have production configs with the same inference settings.

## llama.cpp server parameters

`eagle/runtime/processes.py::build_server_command` currently constructs this
command for every model:

```text
llama-server
  --model <resolved GGUF path>
  --host 127.0.0.1
  --port 8080
  --ctx-size 32768
  --n-gpu-layers -1
  --parallel 1
  --threads 8
  --batch-size 512
  --no-cache-prompt
```

The model path, host, port, context size, GPU layer value, parallel count,
threads, and batch size are explicitly configured in each current experiment
YAML and inherited by the launcher. `--no-cache-prompt` is hard-coded by the
launcher. It was added in commit `cc2b4b1a89d` and is present in all five
preserved comparison runs above.

| Server parameter | Classification | Effective current value | Source of effective value |
|---|---|---:|---|
| model path | explicitly configured | model-specific resolved path | experiment YAML; historical `resolved_config.json` |
| host | explicitly configured | `127.0.0.1` | experiment YAML |
| port | explicitly configured | `8080` | experiment YAML |
| context / `--ctx-size` | explicitly configured | `32768` | experiment YAML |
| GPU layers / `--n-gpu-layers` | explicitly configured | `-1` | experiment YAML; current build interprets `-1` as automatic fitting |
| parallel slots | explicitly configured | `1` | experiment YAML |
| evaluation threads | explicitly configured | `8` | experiment YAML |
| batch threads | omitted | `8` | current llama.cpp derives batch threads from `--threads`; confirmed in runtime logs |
| logical batch | explicitly configured | `512` | experiment YAML |
| physical ubatch | omitted | `512` | current llama.cpp `common_params.n_ubatch` default |
| flash attention | omitted | `auto` | current llama.cpp `LLAMA_FLASH_ATTN_TYPE_AUTO` default |
| server/global seed | omitted | random | current llama.cpp `LLAMA_DEFAULT_SEED` (`-1`) |
| server `n_predict` | omitted | `-1` (no fixed limit) | current llama.cpp `common_params.n_predict` default |
| prompt slot caching | hard-coded | disabled | EAGLE `--no-cache-prompt` |
| RAM prompt cache | omitted | 8192 MiB | current llama.cpp `cache_ram_mib` default; separate from slot `cache_prompt` |
| startup timeout | explicitly configured/defaulted by EAGLE | 180 seconds | Qwen3.5 YAML is explicit; other configs inherit `ModelConfig` default |
| health timeout | explicitly configured/defaulted by EAGLE | 5 seconds | Qwen3.5 YAML is explicit; other configs inherit `ModelConfig` default |

`--n-gpu-layers -1` is a configured request for automatic offload in the
current bundled build, not proof that every historical run used a GPU. Actual
offload depends on the binary build and available device. Some logs show CUDA
offload; an older log also shows a CPU-only warning.

Commits `b91da03b29a`, `a212d14c2dc`, and `65be3259b23` used the same explicit
context/GPU/parallel/thread/batch flag set but did not yet include
`--no-cache-prompt`. Commit `b91da03b29a` briefly had two server definitions
(coder on 8081 and general on 8082); `a212d14c2dc` consolidated them to one
endpoint. This is historical topology only. Current EAGLE owns one server.

The exact llama.cpp binary commit used by the 2026-08-16 through 2026-08-18
runs was not persisted. Therefore the explicit historical flags are known,
but the numeric historical defaults for omitted flags such as ubatch and
flash attention cannot be proven. The values above are exact for the current
bundled build, not retroactively assumed for an unrecorded older binary.

## EAGLE request parameters

EAGLE uses `urllib.request` directly; no OpenAI SDK inserts client-side
defaults. Immediately before the HTTP call, the current request bodies are:

### Generator

```json
{
  "model": "<model.name>",
  "messages": [{"role": "user", "content": "<rendered generation prompt>"}],
  "temperature": 0.2,
  "chat_template_kwargs": {"enable_thinking": false},
  "stream": true
}
```

`max_tokens` is added only when `llm.max_tokens` is not null. It is null/absent
in every current production config and in the preserved real comparison runs.

### Code reflection, code rewrite, Commentator, and Coach

```json
{
  "model": "<model.name>",
  "messages": [{"role": "user", "content": "<role prompt>"}],
  "temperature": 0.2,
  "response_format": {"type": "json_object"},
  "chat_template_kwargs": {"enable_thinking": false},
  "stream": true,
  "max_tokens": 2048
}
```

The `2048` value is an EAGLE hard-coded structured-output fallback in
`eagle/mutation.py` when the shared `llm.max_tokens` setting is absent. The
same fallback existed at commit `7e7604ca34e7`, so it also applied to the
preserved five-model runs.

### Strategy-alignment evaluator

The strategy-alignment call is not a mutation role, but it also reaches the
same server during evaluation. It sends the shared temperature `0.2`, JSON
response format, `enable_thinking: false`, and `stream: true`. It omits
`max_tokens` when the shared value is null.

### Endpoint preflight

The lifecycle preflight is hard-coded to temperature `0`, `max_tokens: 1`,
and `enable_thinking: false`. It is a health check, not candidate generation
or reflection.

### Request field classification

| Request field | Generator | Structured roles | Classification / source |
|---|---|---|---|
| `model` | symbolic current name | symbolic current name | inherited from `model.name`; older runtime sent the model path |
| `messages` | one `user` message | one `user` message | hard-coded envelope; role instruction is inside user prompt |
| `temperature` | `0.2` | `0.2` | explicitly configured and inherited; Commentator/Coach use `match_commentator.temperature` |
| `max_tokens` | omitted | `2048` | generator omitted because config is null; structured fallback is hard-coded |
| `response_format` | omitted | JSON object | hard-coded for structured roles |
| `stream` | `true` | `true` | hard-coded |
| `chat_template_kwargs.enable_thinking` | `false` | `false` | hard-coded |
| `top_p` | omitted | omitted | supplied by llama.cpp server defaults |
| `top_k` | omitted | omitted | supplied by llama.cpp server defaults |
| `min_p` | omitted | omitted | supplied by llama.cpp server defaults |
| `seed` | omitted | omitted | supplied by llama.cpp server defaults |
| `repeat_penalty` | omitted | omitted | supplied by llama.cpp server defaults |
| `repeat_last_n` | omitted | omitted | supplied by llama.cpp server defaults |
| `presence_penalty` | omitted | omitted | supplied by llama.cpp server defaults |
| `frequency_penalty` | omitted | omitted | supplied by llama.cpp server defaults |
| `stop` | omitted | omitted | no client stop sequence; model template/EOS or output limit stops generation |
| typical-p, XTC, DRY, Mirostat, dynamic temperature | omitted | omitted | supplied by llama.cpp server defaults |
| system message | omitted | omitted | EAGLE sends no system-role message |

`random_seed: 7` / `ea_random_seed: 7` is not an inference seed. It controls
EA randomness and deterministic strategy-reflection selection. It never enters
the llama.cpp command or HTTP payload.

## Role-specific differences

| EAGLE call | Prompt source | Temperature | Maximum output | Other decoding difference |
|---|---|---:|---:|---|
| Generator | `initial_generation.txt`, `java_generation.txt`, strategy and API prompt material | 0.2 shared | omitted | none |
| Code reflection diagnosis | `code_reflection.txt` | 0.2 shared | configured shared maximum | JSON response required |
| Code reflection Java revision | `code_revision.txt` | 0.2 shared | configured shared maximum | complete Java response required |
| Prompt reflection generation-prompt rewrite | `prompt_rewrite.txt` | 0.2 shared | configured shared maximum | JSON response required |
| Commentator | `match_commentator.txt` | 0.2 commentator setting | 2048 | JSON response required |
| Coach | one of `coach_refine.txt`, `coach_counter.txt`, `coach_structural.txt`, `coach_alternative.txt` | 0.2 commentator setting | 2048 | uses the same backend instance as Commentator |
| Strategy alignment | `strategy_alignment.txt` | 0.2 shared | omitted | JSON response required |

Current canonical Strategy Reflection invokes Commentator and then Coach. It
does not create a separate decoding configuration for a generic strategy
reflector. `strategy_reflection.txt` and `strategy_rewrite.txt` remain prompt
library entries used by the generic rewrite implementation, but the current
search runtime binds the canonical strategy operator to
`StrategyReflectionMutation` and its Commentator/Coach backend.

Consequently, role behavior differs by prompt, structured-output requirement,
and output cap. It does not differ by top-p, top-k, min-p, seed, penalties, or
system message. Commentator and Coach also do not have independent model or
temperature settings.

## Parameters relying on defaults

For the current bundled llama.cpp build at commit `0253fb21f595`, omitted
request sampler fields resolve as follows. `tools/server/server-task.cpp`
reads each JSON field with the server sampling object as its fallback, and
`common/common.h` defines these defaults. Direct GGUF inspection found no
model sampling metadata that would override them.

| Omitted request parameter | Effective current value | Owner |
|---|---:|---|
| `top_k` | 40 | llama.cpp |
| `top_p` | 0.95 | llama.cpp |
| `min_p` | 0.05 | llama.cpp |
| `seed` | random (`LLAMA_DEFAULT_SEED`) | llama.cpp |
| `repeat_last_n` | 64 | llama.cpp |
| `repeat_penalty` | 1.0 (disabled) | llama.cpp |
| `presence_penalty` | 0.0 | llama.cpp |
| `frequency_penalty` | 0.0 | llama.cpp |
| `typical_p` | 1.0 (disabled) | llama.cpp |
| `top_n_sigma` | -1.0 (disabled) | llama.cpp |
| `xtc_probability` | 0.0 (disabled) | llama.cpp |
| dynamic-temperature range | 0.0 (disabled) | llama.cpp |
| DRY multiplier | 0.0 (disabled) | llama.cpp |
| Mirostat mode | 0 (disabled) | llama.cpp |
| generator/alignment `max_tokens` | server `n_predict: -1`; generation ends at EOS or context capacity | llama.cpp/model template |

Temperature is not defaulted: EAGLE explicitly sends `0.2` for all real EA
role calls. This overrides the current llama.cpp default of `0.8`.

These numeric omitted-field defaults are proven for the current bundled
binary/source only. The historical run artifacts did not record their
llama.cpp version, so their omitted sampler values must be classified as
“llama.cpp server default, exact historical numeric value unknown,” rather
than assumed to match the current build.

## Effective parameter comparison table

All entries below are for real OpenAI-compatible runs/configs. “Server default”
means omitted by EAGLE; the parenthesized number is the current bundled
llama.cpp value, not an asserted historical value.

| Model | Model file / GGUF | Quantization | Effective context | Temperature | Top-p / top-k / min-p | Repeat penalty | Seed behavior | Max output tokens | Other sampling | Server/request source | Status |
|---|---|---|---:|---:|---|---|---|---|---|---|---|
| Llama 3.1 8B | historical hash-named GGUF under `meta-llama-3-1-8b-instruct…` | Q4_K_M | 32768 | 0.2 | server defaults (0.95 / 40 / 0.05 current) | server default (1.0 current) | LLM seed omitted/random; EA seed 7 is unrelated | Generator/alignment omitted; structured roles 2048 | thinking disabled; streaming; JSON for structured roles | server command + run `resolved_config.json`; request code at `7e7604…` | historical completed real run |
| Qwen3 8B | `qwen3-8b-q4-k-m-d7a12a96/model.gguf` | Q4_K_M | 32768 | 0.2 | same server defaults | same | same | same | same | historical run plus current YAML/code | historical and current |
| Qwen3.5 9B | `qwen3-5-9b-ud-q4-k-xl…/model.gguf` | UD-Q4_K_XL mixed | 32768 | 0.2 | same server defaults | same | same | same | same | historical runs plus current YAML/code | historical and current |
| Ministral 3 8B | `Ministral-3-8B-Instruct-2512-Q4_K_M.gguf` | Q4_K_M | 32768 | 0.2 | same server defaults | same | same | same | same | historical run plus current YAML/code | historical and current |
| Gemma 3 12B | `gemma-3-12b-it-Q4_K_M.gguf` | Q4_K_M | 32768 | 0.2 | same server defaults | same | same | same | same | historical run plus current YAML/code | historical and current |

There is no evidence in the preserved real comparison set that switching the
model also changed an explicit sampler parameter. The changed launch-critical
field was the model path; explicit context and runtime flags, temperature,
thinking mode, and role output-cap behavior remained the same.

## Runtime payload verification

A temporary in-memory mock intercepted the serialized body at
`urllib.request.urlopen`. It observed:

| Call path | Fields immediately before HTTP |
|---|---|
| Generator | `model`, one user `messages` entry, `temperature: 0.2`, `enable_thinking: false`, `stream: true`; no `max_tokens` |
| Reflection/rewrite | generator fields plus JSON `response_format` and `max_tokens: 2048` |
| Commentator/Coach | same structured body, commentator temperature `0.2`, `max_tokens: 2048` |
| Strategy alignment | temperature `0.2`, JSON format, thinking disabled, streaming; no `max_tokens` |
| Endpoint preflight | temperature `0`, `max_tokens: 1`, thinking disabled |

This verifies the body EAGLE constructs; it does not merely infer it from the
YAML schema. Since the transport is direct `urllib`, the captured JSON is what
reaches llama.cpp, apart from normal HTTP serialization.

## Relevant files and Git commits

Current sources:

- `configs/experiments/*/experiment.yaml`: model launch and shared request configuration.
- `eagle/config.py`: YAML defaults and config resolution.
- `eagle/runtime/processes.py`: exact llama.cpp command construction.
- `eagle/search_runtime.py`: one shared client, role binding, and preflight body.
- `generation/backend.py`: Generator request body.
- `eagle/mutation.py`: structured reflection/rewrite request body and 2048 fallback.
- `eagle/strategy_reflection.py`: Commentator/Coach role sequence and deterministic EA selection seed.
- `evaluation/strategy_alignment.py`: alignment request body.
- `prompts/manifest.toml` and `prompts/*.txt`: role prompt ownership.
- `experiment_env/model/llama.cpp/llama.cpp/common/common.h`: current server defaults.
- `experiment_env/model/llama.cpp/llama.cpp/tools/server/server-task.cpp`: request-field fallback logic.

Relevant history:

- `b91da03b29a`: introduced shell-managed split coder/general servers.
- `a212d14c2dc`: consolidated execution to one endpoint.
- `65be3259b23`: reduced the runtime config to Qwen3.5.
- `cc2b4b1a89d`: added `--no-cache-prompt`.
- `7e7604ca34e7`: source revision for the preserved Llama, Qwen3, Qwen3.5, and Ministral comparison runs.
- `5d8a30d49e5`: source revision for the preserved Gemma run.
- `62d918a16fb`: current unified experiment/model lifecycle and symbolic request model names.

## Conclusions

- Definitely explicit: model path, host, port, 32768 context, GPU-layers value
  `-1`, parallel `1`, threads `8`, batch `512`, temperature `0.2`, streaming,
  thinking disabled, JSON response format for structured roles, and structured
  role output cap `2048`. `--no-cache-prompt` is launcher-hard-coded.
- Defaults: top-p, top-k, min-p, LLM seed, repetition/presence/frequency
  penalties, ubatch, flash attention, and uncapped Generator/alignment output
  behavior are supplied by llama.cpp when EAGLE omits them. Exact current
  values are documented above; exact historical numeric values are unknown
  because the historical llama.cpp binary revision was not persisted.
- Commentator, Coach, and Generator do not have independent sampler suites.
  Generator uses the shared temperature and no output cap; Commentator and
  Coach share the commentator-temperature backend and the 2048 structured cap.
- The audited real model changes did not also change explicit sampling
  parameters. They changed the GGUF/model identity while keeping the same
  explicit server and request settings.
- Therefore the preserved real experimental comparisons did not accidentally
  compare both different models and different explicit decoding settings.
  They may still depend on model-specific templates/tokenization and on
  unrecorded historical llama.cpp defaults, which cannot be reconstructed
  exactly from the stored artifacts.
