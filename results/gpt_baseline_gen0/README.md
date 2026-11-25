# GPT baseline（單一 GPT，無演化）

Seed 8，run `20261030_120346_658325`。GPT 呼叫一次，選出唯一的 genome
`gen_0000_d1bf70074e31`。搜尋與固定對手評估都在 G0 完成。

| 評估 | 結果 |
| --- | --- |
| G0 搜尋 Game Performance | −9.001（報告精度） |
| 固定對手平均分數 | −9.505160 |
| 固定對手勝／和／敗 | 265／10／325，共 600 場 |
| 勝率 | 44.17% |

固定評估包含 10 個對手、3 張地圖、雙側各 10 場。固定對手圖以 G0 單點呈現。
逐對手表保留報告記錄的勝和敗與勝率。

[方法 1 的設定](../../configs/experiments/1030_gpt_framework_slot_ablation_seed8_10/01_gpt_framework_gpt_slot_once.yaml) · [實驗報告](../../configs/experiments/1030_gpt_framework_slot_ablation_seed8_10/RESULTS.md) · [固定對手分數精度](../../docs/implementation/current_status.md)
