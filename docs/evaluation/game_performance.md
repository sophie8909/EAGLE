# `game_performance`

This is the single canonical implementation guide for the `game_performance` formula. Normative source: specification section 14.

## Preconditions and direction

- Higher is better.
- Aggregate 18 valid matches per opponent: 3 maps × 3 rounds × both candidate
  sides. The fixed ten-opponent batch is 180 matches; generation 1+ is 198 when
  `eagle_previous_best` is enabled.
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
fixed_weight_sum = 12.5
total_weight = fixed_weight_sum + eagle_weight
opponent_average[o] = mean(match_score_i for i in o's 18 records)
game_performance = sum(weight[o] * opponent_average[o] for o) / total_weight
```

The fixed opponents have weights `(0.5, 0.5, 0.5, 1, 1, 1, 2, 2, 2, 2)` in
canonical order. `eagle_weight` is zero in generation 0; for generation `g >= 1`,
`0.5 + 3.5 * ((g-1)/max(G-2,1))**2`, clipped to `[0.5, 4.0]`.

Persist the ordered ten-opponent breakdown in addition to the aggregate:

- `opponent_results`: one result for every configured opponent, including failed attempts;
- `opponent_scores`: one 18-match average per fixed opponent, followed by the dynamic score when present;
- each opponent summary: expected/completed/missing counts, P0/P1 averages, map averages, and weighted contribution;
- `game_performance`: the candidate-level aggregate used by EA selection.

Persist:

- `wins`, `draws`, `losses`, `win_rate`;
- `mean_result_score`, `mean_material_score`, `mean_final_resource_score`, `mean_survival_score`;
- `score_stddev`, `minimum_match_score`, `maximum_match_score`;
- `completed_match_count`;
- all per-match component inputs and outputs.

If `completed_match_count` is not the expected 180/198, the objective is `-1000` regardless of the partial mean. Missing matrix records are retained in failure artifacts.
An attempted opponent that fails is still retained with score `-1000`; it is never
removed from the breakdown or reflection evidence.

## Configuration and versioning

Resolved configuration must contain material values for every supported unit type, `material_scale`, `resource_scale`, `matches_per_opponent = 18`, `matches_per_candidate = 180`, the three maps, round seed schedule, side policy, cycles, and opponent weights. Persist an `objective_formula_version`; formula changes require schema migration notes.

## Tests

- Exact win/draw/loss baselines.
- Saturation and signs of both `tanh` components.
- Survival behavior for win, draw, and loss.
- Shaping clamp at both bounds.
- Result ordering under worst/best shaping.
- 18-match opponent arithmetic, weighting order, and persisted map/side statistics.
- Any incomplete 18/180/198 matrix yields `-1000` while retaining evidence.
- Player/opponent perspective is never reversed.

## Historical note

Older gap notes describe pre-matrix scoring experiments. The formulas above and
`evaluation/game_performance.py` are the current runtime authority.
