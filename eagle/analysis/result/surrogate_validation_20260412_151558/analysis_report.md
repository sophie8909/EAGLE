# Consistency Analysis Report

## Data Summary

- Aligned result pairs: 60
- Unique prompt_ids: 10
- Maps: 1
- Opponents: 6
- Behavior rows available: 0

## Metric Summary

| group_type | group_value | pair_count | pearson | spearman | kendall_tau | mae | rmse | mean_bias | top5 | top10 | top20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| overall | overall | 60 | N/A | N/A | N/A | 0.4833 | 0.4916 | 0.0167 | 0.6000 | 1.0000 | 1.0000 |
| map | __unknown_map__ | 60 | N/A | N/A | N/A | 0.4833 | 0.4916 | 0.0167 | 0.6000 | 1.0000 | 1.0000 |
| opponent | ai.PassiveAI | 10 | N/A | N/A | N/A | 0.4000 | 0.4472 | 0.4000 | 1.0000 | 1.0000 | 1.0000 |
| opponent | ai.RandomAI | 10 | N/A | N/A | N/A | 0.5000 | 0.5000 | 0.1000 | 0.8000 | 1.0000 | 1.0000 |
| opponent | ai.RandomBiasedAI | 10 | N/A | N/A | N/A | 0.5000 | 0.5000 | -0.2000 | 0.8000 | 1.0000 | 1.0000 |
| opponent | ai.abstraction.HeavyRush | 10 | N/A | N/A | N/A | 0.5000 | 0.5000 | 0.2000 | 0.8000 | 1.0000 | 1.0000 |
| opponent | ai.abstraction.LightRush | 10 | N/A | N/A | N/A | 0.5000 | 0.5000 | 0.1000 | 0.6000 | 1.0000 | 1.0000 |
| opponent | ai.abstraction.WorkerRush | 10 | N/A | N/A | N/A | 0.5000 | 0.5000 | -0.5000 | 1.0000 | 1.0000 | 1.0000 |

## Figures

- Scatter consistency: `figures/scatter_consistency.png`
  This plot shows whether Java scores track prompt-based scores along the y=x line.
- Bland-Altman: `figures/bland_altman.png`
  This plot highlights systematic bias and spread of Java minus prompt-based scores.
- Error histogram: `figures/error_histogram.png`
  This histogram shows how large the absolute prediction errors are across aligned samples.
- Top-k overlap: `figures/topk_overlap.png`
  This chart shows how much Java preserves the top-ranked prompt_ids used by EA selection.
- Pairwise win-resource: `figures/pairwise_win_resource.png`
  This plot compares prompt-based and Java distributions in win-resource space.
- Pairwise win-accuracy: `figures/pairwise_win_accuracy.png`
  This plot compares prompt-based and Java distributions in win-accuracy space.
- Pairwise resource-accuracy: `figures/pairwise_resource_accuracy.png`
  This plot compares prompt-based and Java distributions in resource-accuracy space.
- Win consistency: `figures/win_consistency.png`
  This scatter plot compares prompt-based and Java win values directly.
- Resource consistency: `figures/resource_consistency.png`
  This scatter plot compares prompt-based and Java resource values directly.
- Accuracy consistency: `figures/accuracy_consistency.png`
  This scatter plot compares prompt-based and Java accuracy values directly.

## Behavior Summary

_No rows available._

## Largest Prompt Bias

| prompt_id | mean_abs_gap | pair_count |
| --- | --- | --- |
| 101f3ea05035b3847d6229629c826ef1ef41e27f8f9cef5d555c01bf74119045 | 0.5000 | 6 |
| 19bbd60e0dd6a5cae4e512d6599bf85834634d60ce1ee49214d368d7e296cb7c | 0.5000 | 6 |
| 727cd3efc6af9ebd66527ef262aaffd8af9656d9fc34c7bf52837168bcb1537b | 0.5000 | 6 |
| 80283732042f9e5ab322d31ecd18aab3cb9ba068fa9fe7ad617b10734dc29abd | 0.5000 | 6 |
| 9ed75b562f8efaae20e7cdc843735a31340ab965f5d09a3ccf314c9b70c4476e | 0.5000 | 6 |

## Surrogate Validity Interpretation

- Ranking consistency could not be estimated because there were not enough aligned samples.
- Top-10 overlap is high, which suggests the surrogate can preserve EA selection pressure.
- Some behavior metrics were unavailable and were skipped: attack_action, barracks_build, combat_unit_composition, first_attack_turn, harvest_action, idle_ratio, resource_collection_rate, worker_production.

## Conclusion

This report summarizes whether the Java agent can preserve prompt-based performance ordering and behavior similarity well enough to act as a practical surrogate.
