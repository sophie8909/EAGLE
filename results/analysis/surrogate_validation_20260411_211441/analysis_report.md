# Consistency Analysis Report

## Data Summary

- Aligned result pairs: 23
- Unique prompt_ids: 4
- Maps: 1
- Opponents: 6
- Behavior rows available: 0

## Metric Summary

| group_type | group_value | pair_count | pearson | spearman | kendall_tau | mae | rmse | mean_bias | top5 | top10 | top20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| overall | overall | 23 | 0.4769 | 0.5010 | 0.4886 | 0.3478 | 0.5710 | 0.3478 | 1.0000 | 1.0000 | 1.0000 |
| map | __unknown_map__ | 23 | 0.4769 | 0.5010 | 0.4886 | 0.3478 | 0.5710 | 0.3478 | 1.0000 | 1.0000 | 1.0000 |
| opponent | ai.PassiveAI | 4 | N/A | N/A | N/A | 0.1250 | 0.2500 | 0.1250 | 1.0000 | 1.0000 | 1.0000 |
| opponent | ai.RandomAI | 4 | 0.5774 | 0.5774 | 0.5774 | 0.3750 | 0.5590 | 0.3750 | 1.0000 | 1.0000 | 1.0000 |
| opponent | ai.RandomBiasedAI | 4 | N/A | N/A | N/A | 0.2500 | 0.5000 | 0.2500 | 1.0000 | 1.0000 | 1.0000 |
| opponent | ai.abstraction.HeavyRush | 4 | N/A | N/A | N/A | 0.7500 | 0.8660 | 0.7500 | 1.0000 | 1.0000 | 1.0000 |
| opponent | ai.abstraction.LightRush | 4 | N/A | N/A | N/A | 0.5000 | 0.7071 | 0.5000 | 1.0000 | 1.0000 | 1.0000 |
| opponent | ai.abstraction.WorkerRush | 3 | N/A | N/A | N/A | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 1.0000 |

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
| 7fa143672e78313443db0de74ac9217a98ca8a5e280648c837255b1408157eee | 0.5000 | 6 |
| bca488aa853fd7544a37b7e3c412db596bad646ae5d733337e207a9e3ec5d49b | 0.5000 | 6 |
| 1367411486efdb433c6ea4b896e12869756b8d62e0096e5e5931eb4df172435e | 0.4000 | 5 |
| 66def6644765578f2134f99bcde95810624cf725c2bc1f84b5745aaa337ca823 | 0.0000 | 6 |

## Surrogate Validity Interpretation

- Ranking consistency is moderate because Spearman falls between 0.4 and 0.7.
- Top-10 overlap is high, which suggests the surrogate can preserve EA selection pressure.
- Some behavior metrics were unavailable and were skipped: attack_action, barracks_build, combat_unit_composition, first_attack_turn, harvest_action, idle_ratio, resource_collection_rate, worker_production.

## Conclusion

This report summarizes whether the Java agent can preserve prompt-based performance ordering and behavior similarity well enough to act as a practical surrogate.
