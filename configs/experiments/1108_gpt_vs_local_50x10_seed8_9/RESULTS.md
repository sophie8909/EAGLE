# 50-generation comparison: 10 GPT initial vs 1 GPT + 9 local

Updated: 2026-11-10 (Asia/Taipei)

Both treatments use the same finite-slot framework bundle
(`f674a580f0db088bd3436232d2dd36d071a231c9886f480a7aaed25669203e2b`),
population size 10, seeds 8 and 9, and 50 evolutionary generations.

## Results

`G0 best` and `G50 best` are the best `game_performance` values in the
self-play search population. The final test uses the selected G50 candidate
and contains 600 matches (10 opponents × 3 maps × 10 games × 2 sides).

| Treatment | Seed | G0 best | G50 best | Selected candidate generation | Final-test W/D/L | Final-test win rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 GPT initial | 8 | -1.26 | 38.06 | 46 | 439/9/152 | 73.17% |
| 10 GPT initial | 9 | 2.36 | 10.71 | 50 | 327/20/253 | 54.50% |
| 1 GPT + 9 local | 8 | -9.50 | 2.72 | 46 | 364/9/227 | 60.67% |
| 1 GPT + 9 local | 9 | -9.52 | 42.32 | 48 | 431/0/169 | 71.83% |

## Two-seed average

| Treatment | Mean G0 best | Mean G50 best | Mean final-test win rate |
| --- | ---: | ---: | ---: |
| 10 GPT initial | -0.55 | 24.39 | 63.83% |
| 1 GPT + 9 local | -9.51 | 22.52 | 66.25% |

## Interpretation

- `10 GPT initial` starts substantially higher at G0, improving the two-seed
  mean from -9.51 to -0.55.
- By G50, the two treatments are close: 10 GPT initial is ahead by 1.87
  points in mean best search performance, but the result is seed-sensitive.
- The 1 GPT + 9 local treatment has the higher mean final-test win rate in
  these two seeds, 66.25% versus 63.83%.
- Seed variance is large: seed 8 favors 10 GPT initial, while seed 9 favors
  1 GPT + 9 local. These results do not establish a consistent winner.

The search `game_performance` values are evaluated in the evolving self-play
context. They should not be interpreted as a frozen cross-generation benchmark.

## Run artifacts

### 10 GPT initial

- Seed 8: [`20261108_144319_755348`](../../../runs/20261108_144319_755348/)
- Seed 9: [`20261109_000650_966551`](../../../runs/20261109_000650_966551/)

### 1 GPT + 9 local

- Seed 8: [`20261109_072720_479146`](../../../runs/20261109_072720_479146/)
- Seed 9: [`20261109_150205_472817`](../../../runs/20261109_150205_472817/)

The generated batch index is [`experiment.yaml`](experiment.yaml).
