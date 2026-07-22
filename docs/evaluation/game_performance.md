# `game_performance`

This is the single canonical implementation guide for the `game_performance` formula. Normative source: specification section 14.

## Preconditions and direction

- Higher is better.
- Aggregate exactly 10 valid matches.
- If any required match is missing/invalid or an earlier pipeline stage failed, set `game_performance = -1000` and retain partial evidence.

## Per-match components

Base result score:

```text
Win  = +100
Draw =    0
Loss = -100
```

For each recorded tick `t`:

```text
material_difference_t = player_material_t - enemy_material_t
mean_material_difference = mean(material_difference_t)
unit_material_score = 5 * tanh(mean_material_difference / material_scale)
```

`unit_material_score` range is `[-5, +5]`. Unit material values and `material_scale` must be centralized, resolved configuration values.

At the final tick:

```text
final_resource_difference = player_final_resources - enemy_final_resources
final_resource_score = 3 * tanh(final_resource_difference / resource_scale)
```

`final_resource_score` range is `[-3, +3]`; `resource_scale` is a resolved configuration value.

Survival/finish-speed shaping:

```text
survival_ratio = final_tick / max_cycles

if result == loss:
    survival_score = 2 * survival_ratio
if result == win:
    survival_score = 2 * (1 - survival_ratio)
if result == draw:
    survival_score = 0
```

`survival_score` range is `[0, +2]`.

Final per-match formula:

```text
shaping_score = clamp(
    unit_material_score + final_resource_score + survival_score,
    -10,
    +10
)

match_score = result_score + shaping_score
```

Expected score bands are Win `[+90, +110]`, Draw `[-10, +10]`, and Loss `[-110, -90]`. This preserves `Win > Draw > Loss > Failure`.

## Candidate aggregation

```text
game_performance = mean(match_score_1 ... match_score_10)
```

Persist:

- `wins`, `draws`, `losses`, `win_rate`;
- `mean_result_score`, `mean_material_score`, `mean_final_resource_score`, `mean_survival_score`;
- `score_stddev`, `minimum_match_score`, `maximum_match_score`;
- `completed_match_count`;
- all per-match component inputs and outputs.

If `completed_match_count != 10`, the objective is `-1000` regardless of the partial mean.

## Configuration and versioning

Resolved configuration must contain material values for every supported unit type, `material_scale`, `resource_scale`, `matches_per_candidate = 10`, opponent, map, cycles, and match seeds. Persist an `objective_formula_version`; formula changes require schema migration notes and an update to the Chinese overview.

## Tests

- Exact win/draw/loss baselines.
- Saturation and signs of both `tanh` components.
- Survival behavior for win, draw, and loss.
- Shaping clamp at both bounds.
- Result ordering under worst/best shaping.
- Ten-match arithmetic and persisted statistics.
- Zero through nine completed matches yield `-1000` while retaining evidence.
- Player/opponent perspective is never reversed.

## Current mismatch

The active formula uses unbounded state/resource terms and a large unconditional survival reward. It is not an alternative contract. See gap `G-06` in [`../implementation/architecture_gaps.md`](../implementation/architecture_gaps.md).

