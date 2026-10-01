# EAGLE latest experiment

## Opponent-library self-play in MicroRTS

Presentation-ready analysis for run `20260930_113026_096063`

Date: 2026-10-01

## Executive takeaway

The opponent library improved the selected agent's fixed-roster result from a draw-heavy `0/444/156` W/L/D in the previous 10×20 semantic-tiebreak run to `95/430/75` in this run. The gain came almost entirely against PassiveAI, RandomAI, and RandomBiasedAI. The agent still recorded zero wins against seven stronger opponents, including WorkerRush, LightRush, HeavyRush, AllInBot, Mayari, COAC, and TMA.

The run also exposed two limits. Self-play fitness increased sharply to `33.426`, but the final population converged to only `2` semantic signatures, with `9/10` candidates in the largest equivalence class. In addition, `29/40` parent refresh replicas changed their generated Java hash, so the refresh mechanism did not preserve phenotype identity for most replicas.

Recommended deck message:

> The opponent library reduced draw attraction and created real wins against weak opponents, but it did not yet produce robust play against strong fixed opponents.

## Slide 1: Title

### Opponent-library self-play in EAGLE

Subtitle: Latest MicroRTS experiment, 20 generations, population 10

Show:

- Run `20260930_113026_096063`
- Ministral 3 8B
- Completed on 2026-10-01

Speaker note: This deck evaluates both the evolutionary search signal and the external fixed-roster test. The two measurements answer different questions and should not be merged.

## Slide 2: Research question

### Can a persistent opponent library turn self-play progress into external wins?

The experiment tests whether retaining historical opponents gives evolution a less fragile training target than a short-lived self-play population.

Expected benefit:

- Preserve pressure from earlier behaviors.
- Reduce the chance that the population learns to draw against only the current context.
- Improve transfer to a fixed roster of standard MicroRTS opponents.

Decision rule for the deck: treat fixed-roster W/L/D as the primary external outcome. Treat self-play `game_performance` as a search diagnostic, not as a direct measure of generalization.

## Slide 3: Experimental design

| Dimension | Setting |
| --- | --- |
| Evolution | 20 generations, population 10, μ+λ survivor selection |
| Model | Ministral 3 8B, random seed 7 |
| Candidate representation | Inherited genotype with LLM-generated initial policies |
| Reflection | Static operator mix: Strategy 0.33, Prompt 0.33, Code 0.34 |
| Search objective | Scalar self-play `game_performance` with semantic tie-break |
| Self-play context | Refresh every 5 generations, library capacity 50 |
| Semantic probes | 9 states: 3 maps × early, mid, late |
| Search evaluation | 10 self-play slots × 3 maps × 3 rounds × 2 sides = 180 matches per candidate |
| Final test | 10 fixed opponents × 3 maps × 10 games per side = 600 matches |

Visual: one horizontal experiment pipeline from policy generation to Java generation, self-play evaluation, library refresh, and final fixed-roster test.

Source: `runs/20260930_113026_096063/config.yaml`

## Slide 4: What changed in the search loop

### The library preserved historical opponents across refresh boundaries

At generation 0, the run seeded 10 self-play slots from the initial population. At generations 5, 10, 15, and 20, the run refreshed six active slots from newer candidates while retaining four generation-zero slots.

| Snapshot | Newer library slots | Retained generation-zero slots | Context |
| ---: | ---: | ---: | --- |
| 0 | 0 | 10 | Initial population |
| 5 | 6 | 4 | First refresh |
| 10 | 6 | 4 | Second refresh |
| 15 | 6 | 4 | Third refresh |
| 20 | 6 | 4 | Fourth refresh |

The persisted library ended with 46 opponent entries against a configured capacity of 50.

Visual: stacked slot timeline showing four retained baseline slots and six refreshed slots at each boundary.

Interpretation: The library added historical pressure, but the retained Java phenotype was not stable across all refresh replicas. This matters when attributing improvements to selection rather than rematerialization.

Sources: `generations/generation_*_self_play_snapshot.json`, `archives/self_play_opponents.json`

## Slide 5: Evolutionary search trajectory

### Self-play fitness rose late in the run

| Generation | Best fitness | Mean fitness | Unique semantic signatures | Largest semantic class |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 1.476 | -0.138 | 6 | 2 |
| 5 | 1.723 | 0.601 | 8 | 3 |
| 10 | 0.679 | 0.571 | 3 | 5 |
| 15 | 17.101 | 12.668 | 6 | 3 |
| 20 | 33.426 | 28.925 | 2 | 9 |

The best final candidate was `gen_0020_ba3403af9376` with `game_performance = 33.426347`. The final generation's worst candidate still scored `11.834252`, which shows strong within-generation fitness uplift but also a compressed behavioral range.

Visual: line chart for best and mean fitness, with vertical markers at generations 5, 10, 15, and 20. Add a second line or annotations for unique semantic signatures.

Chart data:

```text
generation,best_fitness,mean_fitness,unique_semantic_signatures
0,1.476,-0.138,6
5,1.723,0.601,8
10,0.679,0.571,3
15,17.101,12.668,6
20,33.426,28.925,2
```

Source: `generations/generation_0000.json`, `generation_0005.json`, `generation_0010.json`, `generation_0015.json`, `generation_0020.json`

## Slide 6: Fixed-roster final test

### The agent gained wins against weak opponents, but lost every game against strong opponents

Final candidate: `gen_0020_ba3403af9376`

| Opponent | Wins | Losses | Draws | Result |
| --- | ---: | ---: | ---: | --- |
| PassiveAI | 30 | 0 | 30 | Wins and draws |
| RandomAI | 42 | 0 | 18 | Wins and draws |
| RandomBiasedAI | 23 | 10 | 27 | Mixed |
| LightRush | 0 | 60 | 0 | All losses |
| HeavyRush | 0 | 60 | 0 | All losses |
| WorkerRush | 0 | 60 | 0 | All losses |
| AllInBot | 0 | 60 | 0 | All losses |
| Mayari | 0 | 60 | 0 | All losses |
| COAC | 0 | 60 | 0 | All losses |
| TMA | 0 | 60 | 0 | All losses |
| Total | **95** | **430** | **75** | **0 errors** |

Headline metrics:

- Win rate: `15.8%`
- Draw rate: `12.5%`
- Loss rate: `71.7%`
- Strong-opponent wins: `0/420`

Visual: a horizontal stacked bar per opponent, with strong opponents grouped separately from weak opponents.

Source: `final_test/final_test_summary.json`

## Slide 7: Comparison with the previous 10×20 run

### The library reduced draw attraction, but did not solve transfer

| Run | Configuration | W/L/D | Win rate |
| --- | --- | ---: | ---: |
| 20260928_115653_334420 | Self-play, no persistent opponent library | 0 / 444 / 156 | 0.0% |
| 20260930_113026_096063 | Self-play with opponent library | **95 / 430 / 75** | **15.8%** |
| 20260925_134245_911171 | Legacy self-play, 5×40 | 197 / 392 / 11 | 32.8% |
| 20260911_072610_382082 | Fixed-roster mixed initial population control | 256 / 332 / 12 | 42.7% |

Change versus the immediate predecessor:

- `+95` wins
- `-14` losses
- `-81` draws
- `+15.8` percentage points of win rate

These comparisons are directional rather than fully controlled. The runs differ in repository state, model sampling, initial populations, and refresh behavior. The safest claim is that this library run improved the observed result relative to the immediately preceding 10×20 run, not that the library alone caused the entire difference.

Visual: grouped W/L/D bars for the four runs, with the latest run highlighted.

Sources: latest `final_test/final_test_summary.json`; prior run summaries under `runs/20260928_115653_334420`, `runs/20260925_134245_911171`, and `runs/20260911_072610_382082`

## Slide 8: Diversity and convergence

### Fitness improved while behavioral diversity collapsed

At generation 20:

- `2/10` candidates had unique semantic signatures.
- The largest semantic equivalence class contained `9/10` candidates.
- The population retained `4` strategy niches.
- One strategy niche represented `7/10` candidates.
- Mean pairwise strategy distance was `0.531`.

The final policy family emphasized aggressive barracks construction, worker-driven resource denial, diversified Heavy and Ranged production, and immediate responses to enemy barracks. That common pattern is consistent with the dominant strategy niche and with the strong-opponent failure pattern.

Visual: left, a 10-point population strip grouped by semantic signature. Right, a small strategy-niche distribution with counts `7, 1, 1, 1`.

Interpretation: The library improved the search signal without maintaining a broad set of executable behaviors. The run selected a strong self-play attractor, but the attractor remained brittle outside the evolved opponent set.

Sources: `generations/generation_0020.json`, `candidates/gen_0020_ba3403af9376/genotype/strategy_signature.json`

## Slide 9: Reliability and artifact caveats

### The run completed cleanly, but refresh behavior limits causal interpretation

Reliability evidence:

- Run status: `complete`
- Completed generations: `20/20`
- Final integration probe: `7/7` checks passed
- Final test: `600/600` matches completed
- Match errors: `0`
- Opponent fault containment or recovery: `0`
- Candidate artifacts: `221 evaluated`, `29 failed`
- Candidate failures: `19 runtime`, `8 compilation`, `1 validation`, `1 integration`

Refresh caveat:

- Four refresh boundaries produced `40` parent rematerialization records.
- `11` replicas preserved the generated Java hash.
- `29` replicas changed the generated Java hash.
- Phenotype preservation rate: `27.5%`.

This does not invalidate the final test. It does mean that the run is not a clean phenotype-preserving ablation of opponent-library selection.

Visual: two-column evidence slide with green completion checks on the left and a red or amber refresh-preservation callout on the right.

Sources: `manifest.json`, `final_test/final_test_summary.json`, candidate records, `generations/generation_*_self_play_parent_refresh.json`

## Slide 10: Conclusions and next experiment

### The next bottleneck is strong-opponent transfer

Conclusions:

1. The opponent library changed the external outcome from all draws and losses to a measurable number of wins.
2. The gains concentrated on weak opponents and did not extend to the seven stronger fixed opponents.
3. Late search fitness growth coincided with semantic convergence, which suggests a narrow self-play attractor.
4. Refresh rematerialization changed Java for most replicas, so future comparisons need phenotype identity checks before selection claims.

Recommended next experiment:

- Keep the opponent library and the same 20×10 budget.
- Add a small fixed-roster evaluation component to selection, focused on LightRush, WorkerRush, and one strong bot such as Mayari.
- Preserve the generated Java artifact across refresh when the genotype is unchanged, or reject the run as a non-preserving refresh.
- Report both self-play fitness and fixed-roster W/L/D at every refresh boundary.
- Keep semantic diversity as a monitored constraint so the final population cannot collapse to one behavior family.

Success criterion: at least one strong-opponent win while retaining the latest run's zero-error evaluation and without reducing the weak-opponent gains to pure draws.

## Appendix: Evidence map

| Evidence | Source |
| --- | --- |
| Run identity and completion | `runs/20260930_113026_096063/manifest.json` |
| Resolved experiment settings | `runs/20260930_113026_096063/config.yaml` |
| Best candidate and final population | `runs/20260930_113026_096063/summary.json` |
| Generation fitness and diversity | `runs/20260930_113026_096063/generations/generation_*.json` |
| Self-play slot contexts | `runs/20260930_113026_096063/generations/*_self_play_snapshot.json` |
| Refresh identity checks | `runs/20260930_113026_096063/generations/*_self_play_parent_refresh.json` |
| Historical opponent library | `runs/20260930_113026_096063/archives/self_play_opponents.json` |
| Fixed-roster outcome | `runs/20260930_113026_096063/final_test/final_test_summary.json` |
| Candidate strategy summary | `runs/20260930_113026_096063/candidates/gen_0020_ba3403af9376/genotype/strategy_signature.json` |

### Important terminology

- `game_performance` is the scalar shaping score used by self-play selection. It includes resource, material, and survival signals. It is not a fixed-roster win rate.
- Semantic signatures summarize action behavior on nine fixed probe states. They are used for tie-breaking and diversity diagnostics.
- The final test uses the fixed 10-opponent roster and does not feed back into evolution.
