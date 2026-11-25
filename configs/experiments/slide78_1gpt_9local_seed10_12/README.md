# 第 78 頁｜1 GPT＋9 local 補跑 Seeds 10–12

| 版本 | 補跑設定 | 對應的 EAGLE runtime | Survivor selection |
| --- | --- | --- | --- |
| 第一階段 Original | [1109 YAML](1109_original_1gpt_9local_seed10_12.yaml) | `608b97ad` | 按 Game Performance 分層。分數層跨過保留邊界時，才以行為距離選擇 |
| 第二階段 Diversity control | [1111 YAML](1111_diversity_control_1gpt_9local_seed10_12.yaml) | `c092de5c` | 先保留 8 個高分個體，再以 max-min 行為距離選 2 個多樣性席位 |

每組跑 seed 10、11、12，各一次。兩組共用原始 frozen GPT genome 和 framework
bundle，另外 9 個初始 genome 依 seed 產生。族群大小為 10，演化至 G50。
固定對手終測維持每個 seed 600 場。

Survivor selection 由各版程式決定。請透過各自的歷史 runtime 啟動 YAML。
同一份 YAML 在不同 runtime 下可能採用不同的 selection。

## 本機 WSL 執行

在目前 EAGLE checkout 的 WSL 終端執行對應那一組。每組使用獨立 runtime
內的 `batch/`（只含該組 YAML），將各次結果寫到該 runtime 的 `runs/`。

```bash
# 第一階段 Original
(
  cd runtime/slide78-runtimes/1109_original_1gpt_9local_seed10_12 &&
  ~/EAGLE/.venv/bin/python -m eagle experiment --config-dir batch
)

# 第二階段 Diversity control
(
  cd runtime/slide78-runtimes/1111_diversity_control_1gpt_9local_seed10_12 &&
  ~/EAGLE/.venv/bin/python -m eagle experiment --config-dir batch
)
```

批次中斷後，在同一個 runtime 目錄用 `--resume batch` 取代
`--config-dir batch`，由批次索引接續。
第二階段的歷史 launcher 在終測後還會接著跑跨世代固定評估。

版本與既有 seed 8、9 的數據見 [1113 實驗報告](../../../Meeting/1113/report.md)。
