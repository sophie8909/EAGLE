# 2026-10-01 實驗與分析彙整

本資料夾彙整 2026-09-24 之後完成的 EAGLE self-play 實驗，以及先前產出的分析 Markdown。`analysis_md/` 內的檔案是會議用快照，原始檔案仍保留在原位置並作為 canonical source。

## 0924 之後的實驗

| Config | Run ID | 世代 × 族群 | Final test W/L/D/E | Notion |
| --- | --- | ---: | ---: | --- |
| `0925_self_play/self_play_5x40.yaml` | `20260925_134245_911171` | 40 × 5 | 197 / 392 / 11 / 0 | [0925 Self-play 5×40（legacy lexicase）](https://app.notion.com/p/3eac9b9735d9810d87b4ce89769bd4b6?pvs=204) |
| `0926_self_play_sent/self_play_10x10.yaml` | `20260926_195259_768977` | 10 × 10 | 257 / 321 / 22 / 0 | [0926 Self-play 10×10 semantic tie-break](https://app.notion.com/p/3eac9b9735d981f78c00e9a7706af646?pvs=204) |
| `0926_self_play_sent/self_play_5x20.yaml` | `20260927_035808_811233` | 20 × 5 | 0 / 388 / 212 / 0 | [0926 Self-play 5×20 semantic tie-break](https://app.notion.com/p/3eac9b9735d98115b78be874b606a195?pvs=204) |
| `0927/self_play_10x20.yaml` | `20260928_115653_334420` | 20 × 10 | 0 / 444 / 156 / 0 | [0927 Self-play 10×20 semantic tie-break](https://app.notion.com/p/3eac9b9735d981518b7cf0dfe691ade7?pvs=204) |

以上四筆皆已完成 600 場 fixed-roster final test、Integration 7/7，且 match errors 為 0。0925 的來源檔名與實際配置是 5×40，但該 run 的 manifest `experiment_name` 誤記為 `self_play_10x20`；比較時請以 config、run ID 與 artifacts 為準。

## 分析 Markdown 索引

| 1001 快照 | 原始來源 | 主題 |
| --- | --- | --- |
| [20260907_reflection_ratio_full_report.md](analysis_md/20260907_reflection_ratio_full_report.md) | [full_five_generation_report.md](../20260907_reflection_ratio_summary/deliverables/full_five_generation_report.md) | Reflection ratio 五世代完整分析 |
| [20260910_generation_model_comparison.md](analysis_md/20260910_generation_model_comparison.md) | [ministral_vs_qwen_generation_model_analysis.md](../20260910_generation_model_comparison_20x10/ministral_vs_qwen_generation_model_analysis.md) | Generation model 比較 |
| [20260912_initial_population_comparison.md](analysis_md/20260912_initial_population_comparison.md) | [initial_population_comparison_presentation_content.md](../20260912_initial_population_comparison_20x10/initial_population_comparison_presentation_content.md) | 初始族群比較 |
| [20260914_parent_regeneration_comparison.md](analysis_md/20260914_parent_regeneration_comparison.md) | [parent_regeneration_comparison_presentation_content.md](../20260914_parent_regeneration_comparison_20x10/parent_regeneration_comparison_presentation_content.md) | Parent regeneration 比較 |
| [20260923_self_play_20x10.md](analysis_md/20260923_self_play_20x10.md) | [self_play_presentation_content.md](../20260923_self_play_20x10/self_play_presentation_content.md) | 20×10 self-play 實驗分析 |
| [20260926_self_play_comparison.md](analysis_md/20260926_self_play_comparison.md) | [self_play_comparison_presentation_content.md](../20260926_self_play_comparison/self_play_comparison_presentation_content.md) | Self-play 跨實驗比較 |
| [20260928_self_play_10x10_vs_5x20.md](analysis_md/20260928_self_play_10x10_vs_5x20.md) | [results_analysis.md](../../configs/experiments/0926_self_play_sent/results_analysis.md) | 10×10 與 5×20 比較 |
| [experiment_results_after_0907.md](analysis_md/experiment_results_after_0907.md) | [experiment_results_after_0907.md](../../docs/experiment_results_after_0907.md) | 0907 之後實驗結果總覽 |
| [model_parameter_audit.md](analysis_md/model_parameter_audit.md) | [model_parameter_audit.md](../../docs/model_parameter_audit.md) | 模型參數稽核 |
| [version_summary_after_0907.md](analysis_md/version_summary_after_0907.md) | [version_summary_after_0907.md](../../docs/version_summary_after_0907.md) | 0907 之後版本摘要 |

## 使用說明

- 查看本次整理時，從本頁進入 `analysis_md/` 的快照。
- 後續若分析內容更新，請先修改原始來源，再同步此處快照。
- 實驗判讀以 run 內的 `manifest.json`、`config.yaml`、`summary.json`、candidate artifacts 與 `final_test/` 為依據。
