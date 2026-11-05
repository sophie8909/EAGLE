# Description-guided framework initialization

Updated: 2026-11-05 (Asia/Taipei)

New launches use direct OpenAI GPT (`framework.model: gpt-6.1-sol`) to select
all ten initial complete genomes (`framework.gpt_initial_candidates: 10`). Each
candidate receives a different authored strategy description from
`prompts/framework_initial_strategies.txt`, including WorkerRush at index 0.
Each GPT selection request includes that candidate's description and the frozen
bundle's complete slot domains. Subsequent evolution uses local crossover and
mutation. Distinct descriptions do not guarantee different selected genomes.

The previous configuration used `initial_strategy_mode: llm_plus_authored`:
one experiment-LLM-generated description plus nine authored profiles, with
experiment-LLM batch slot selection. Historical results below describe that
previous configuration, not the new all-GPT initialization. Existing runs retain
their frozen resolved configs; launch a fresh run to use the new initialization.

This remains separate from the historical 1030 ablation (seeds 8–10,
population 10, 100 generations).

## Current execution status

The new all-GPT initialization has not been run against the live provider.
It requires a GPT API key in `api_key/gpt`. A local model server is not needed.

```powershell
python -m eagle experiment --config-dir configs/experiments/1104_description_guided/experiment.yaml
```

## Two-machine configs (2026-11-05)

| Machine | Config | Seeds |
| --- | --- | --- |
| Ubuntu | `ubuntu_seed8_9.yaml` | 8, 9 |
| Windows | `windows_seed10.yaml` | 10 |

Both reuse the checked-in `bundle.json`, an exact-byte copy of the original
1030 ablation framework (SHA-256
`f674a580f0db088bd3436232d2dd36d071a231c9886f480a7aaed25669203e2b`).
No new framework is generated. The local `.gitattributes` preserves those bytes
on both operating systems. GPT selects all ten initial genomes from distinct
strategy descriptions; later evolution stays local. The two configs differ only
in experiment name and seed list, with population 10 and 100 generations each.

Ubuntu (from the repository root):

```bash
python -m eagle experiment --config-dir configs/experiments/1104_description_guided/ubuntu_seed8_9.yaml
```

Windows PowerShell (from the repository root):

```powershell
python -m eagle experiment --config-dir configs/experiments/1104_description_guided/windows_seed10.yaml
```

In the GUI, refresh the Config list, select the file for that machine, load and
validate it, then start the current settings with Mock unchecked. Each machine
needs its own `api_key/gpt` file. No local model server is needed. Select the
exact YAML file rather than passing this whole directory, which also contains
the original combined-seed config. Resume uses the chosen run's frozen config.

## Historical execution status (previous 1+9 configuration)

| Seed | Run | Status |
| ---: | --- | --- |
| 8 | `runs/20261104_173400_452494` | Complete: generation 100 and final test |
| 9 | `runs/20261105_093045_996218` | Not started successfully: LLM endpoint preflight failed |
| 10 | — | Not started |

The old seed 9 directory contains no generation result and is excluded below.

## Seed 8 result summary

| Item | Result |
| --- | ---: |
| Completed generations | G0–G100 |
| Evaluated candidate matrices | 1,210 |
| Search matches | 217,800 / 217,800 successful |
| Search evaluation failures | 0 |
| Final candidate | `gen_0100_330603955b0b` |
| Final search Game Performance | 8.302 |
| Final test | 600 / 600 matches, 0 errors |
| Final-test W / D / L | 315 / 11 / 274 |
| Final-test win rate | 52.50% |
| Final-test mean match score | 9.043 |
| End-to-end search time | approximately 15 h 54 min |

The final test selected the generation 100 best candidate without fallback. It
passed compilation and all seven ordered integration checks. No AllInBot
upstream fault required containment or score neutralization.

## Initialization outcome

The generated description was a defensive **Heavy Anchor** strategy. Its G0
Game Performance was **-72.555**, ranking sixth among the ten initial
candidates. It was no longer present as a survivor description at G1. The best
G0 description was the authored **Ranged offensive timing** profile at
**-46.335**.

The authored **Mixed army control** profile started second at **-60.216**, then
became dominant: all ten generation 100 survivors carry this description. The
best final genome is therefore evidence for successful slot evolution under an
authored description, not evidence that the newly generated Heavy Anchor
description supplied the winning lineage. Because description labels follow
survivor inheritance, this observation does not by itself exclude every
possible earlier crossover contribution from the generated candidate.

## Search trajectory

Search Game Performance uses the active self-play context. Six opponent slots
refresh every five generations, so scores across refresh boundaries are useful
for within-run trajectory inspection but are not a frozen cross-generation
benchmark.

| Generation | Best | Population mean | Semantic unique | Mean pair distance |
| ---: | ---: | ---: | ---: | ---: |
| 0 | -46.335 | -68.819 | 10/10 | 0.9062 |
| 1 | -20.625 | -39.583 | 8/10 | 0.7556 |
| 5 | 3.996 | 1.338 | 2/10 | 0.0444 |
| 10 | 21.764 | 15.083 | 3/10 | 0.1333 |
| 20 | 33.312 | 17.837 | 4/10 | 0.1185 |
| 50 | 29.170 | 27.959 | 2/10 | 0.1111 |
| 95 | 29.874 | 28.423 | 1/10 | 0.0000 |
| 100 | 8.302 | 5.226 | 2/10 | 0.0667 |

The run moved from a fully distinct initial population to only two semantic
signatures at G100, with nine of ten survivors in the largest equivalence
class. Description-guided initialization created ten distinct initial
behaviors, but it did not prevent rapid diversity collapse under the current
selection and local-variation settings.

## Generation 100 final test

Each opponent has 60 matches: three maps, ten games per side per map.

| Opponent | W | D | L | Win rate |
| --- | ---: | ---: | ---: | ---: |
| PassiveAI | 60 | 0 | 0 | 100.0% |
| RandomAI | 60 | 0 | 0 | 100.0% |
| RandomBiasedAI | 59 | 1 | 0 | 98.3% |
| LightRush | 30 | 0 | 30 | 50.0% |
| HeavyRush | 50 | 10 | 0 | 83.3% |
| WorkerRush | 30 | 0 | 30 | 50.0% |
| AllInBot | 21 | 0 | 39 | 35.0% |
| Mayari | 5 | 0 | 55 | 8.3% |
| COAC | 0 | 0 | 60 | 0.0% |
| TMA | 0 | 0 | 60 | 0.0% |
| **Total** | **315** | **11** | **274** | **52.5%** |

The final candidate is reliable against the three simple baselines and strong
against HeavyRush. Its performance is map-dependent against LightRush,
WorkerRush, and AllInBot, and it remains weak against Mayari with no wins
against COAC or TMA. The positive overall mean score is therefore driven mainly
by baseline and rush matchups rather than broad strength against the four
hardest opponents.

## Current interpretation and limits

- The new LLM-generated description did not provide the best initialization in
  seed 8 and did not survive as a description beyond G0.
- All final survivors and the final-test candidate carry the authored Mixed
  army description label; exact earlier crossover contribution remains a
  separate lineage question.
- Local evolution substantially improved the selected strategy, but semantic
  diversity collapsed quickly.
- This is one completed seed. Seeds 9 and 10 are required before drawing a
  causal conclusion about `llm_plus_authored` initialization.
- The completed final test evaluates only the G100 representative. A frozen
  every-five-generation evaluation has not yet been run for this experiment.

## Artifact sources

- Run summary: [`summary.json`](../../../runs/20261104_173400_452494/summary.json)
- Generation 0: [`generation_0000.json`](../../../runs/20261104_173400_452494/generations/generation_0000.json)
- Generation 100: [`generation_0100.json`](../../../runs/20261104_173400_452494/generations/generation_0100.json)
- Final-test summary: [`final_test_summary.json`](../../../runs/20261104_173400_452494/final_test/final_test_summary.json)
- Final-test table: [`final_test_results.md`](../../../runs/20261104_173400_452494/final_test/final_test_results.md)
- Generated initial description evidence: [`result.json`](../../../runs/20261104_173400_452494/initialization/framework_initial_strategy/attempt_001/result.json)

`bundle.json` preserves the exact original framework bytes and expected SHA-256
`f674a580f0db088bd3436232d2dd36d071a231c9886f480a7aaed25669203e2b`.
The local `.gitattributes` prevents Git from changing its line endings; this
avoids an existing LF-to-CRLF hash mismatch in the historical bundle checkout.
Neither the framework mechanisms nor its finite slot domains were changed.

Implementation validation before the live run: 69 of 70 related regression
checks passed; the one failure loaded the unchanged historical bundle and
failed its exact-byte hash check. A provider-free single-generation CLI mock
and completed-run resume passed. The live seed 8 artifacts now additionally
confirm ten distinct initial semantic signatures, complete evaluation through
G100, and a valid 600-match final-test matrix.
