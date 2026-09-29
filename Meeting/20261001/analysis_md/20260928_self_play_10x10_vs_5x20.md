# Self-play `10x10` 與 `5x20` 實驗結果分析

## 結論摘要

- **固定對手泛化能力：`10x10` 明顯優於 `5x20`。** `10x10` 的 final test 為 **257 勝 / 321 敗 / 22 和**（勝率 42.83%）；`5x20` 為 **0 勝 / 388 敗 / 212 和**（勝率 0%）。兩者皆完成 600 場、無執行錯誤，且 final-test Integration 7/7 通過。
- **`5x20` 收斂到和局型策略。** 被送進 final test 的個體在演化期 self-play 是 **0 勝 / 180 和 / 0 敗**，`game_performance = 1.326067` 來自資源、兵力與存活 shaping，而非勝局。它對固定對手完全沒有取勝，顯示 self-play objective 與外部泛化間存在明顯落差。
- **語意 tie-break 有作用，但不能創造候選池中不存在的多樣性。** `5x20` 在 generation 8 的同 fitness tier 中有 10 種語意，最後保留 5 種不同語意；但 generation 20 的候選池只剩 2 種，最終也只能保留 2 種。`10x10` 自 generation 2 起最高 fitness tier 只有 1 種語意，最終 10 個 survivor 全部是同一語意。
- **更多 generations 並未換得更好的泛化。** `5x20` 雖有較長的搜尋鏈與較高的最終 self-play fitness，卻落入無勝局的 draw attractor；`10x10` 的較大 population 最後至少保留了一個能擊敗基礎對手、並在小地圖對部分強對手取勝的策略。
- **這不是乾淨的單因子比較。** 兩組各只有一次 run；LLM sampling 不受 `random_seed` 完整控制，generation 0 的實際初始策略不同；兩組的 self-play snapshot 數量也不同。更重要的是，refresh audit 有多筆 `generated_java_preserved: false`，因此不能把結果差異完全歸因於 `10x10` 與 `5x20` 的配置差異。

## 實驗與資料來源

| 項目 | `10x10` | `5x20` |
|---|---:|---:|
| Config | [`self_play_10x10.yaml`](self_play_10x10.yaml) | [`self_play_5x20.yaml`](self_play_5x20.yaml) |
| Run | [`20260926_195259_768977`](../../../runs/20260926_195259_768977/) | [`20260927_035808_811233`](../../../runs/20260927_035808_811233/) |
| Manifest 狀態 | complete，generation 10 | complete，generation 20 |
| Population × generations | 10 × 10 | 5 × 20 |
| 一般 offspring 預算 | 100 | 100 |
| Self-play refresh interval | 5 | 5 |
| Fitness tie tolerance | ≤ 1.0，含邊界 | ≤ 1.0，含邊界 |
| Semantic probes | 3 maps × early/mid/late，共 9 個 | 同左 |
| 搜尋 candidate artifacts | 130 | 130 |
| Final test | 10 opponents × 3 maps × 10 rounds × 2 sides = 600 | 同左 |

主要依據為兩個 run 的 `manifest.json`、`summary.json`、`generations/generation_*.json`、candidate evaluation artifacts、self-play refresh sidecars、`timing.jsonl`，以及 `final_test/final_test_summary.json` / CSV。演化期數字是當代 survivor snapshot；final test 則是固定十個對手，兩者不可當成同一個 evaluation context。

兩組共用模型、地圖、mutation/crossover 設定與 EA random seed；唯一刻意變動的是 population/generation 配比。但 LLM 生成具有隨機性，兩組 generation 0 並不是相同的初始 population，因此本分析只能比較這兩次實際 run，不能視為嚴格控制實驗。

## 1. 演化期結果

### 1.1 里程碑

`語意數` 是 survivor population 中不同 global semantic signatures 的數量；`平均距離` 是可用 9-probe signatures 的兩兩 normalized Hamming distance。

| Run | Gen | Best | Mean | Worst | 語意數 | 平均距離 | 備註 |
|---|---:|---:|---:|---:|---:|---:|---|
| `10x10` | 0 | 91.388695 | 1.924307 | -17.238125 | 7 / 8 可用 | 0.853 | 1 個 candidate failure；另有 1 個 signature 不可用 |
| `10x10` | 5 | 0.666667 | 0.666667 | 0.666667 | 1 / 10 | 0.000 | snapshot refresh 後全體同 fitness、同語意 |
| `10x10` | 10 | 0.666667 | 0.666667 | 0.666667 | 1 / 10 | 0.000 | 最終 population 完全語意收斂 |
| `5x20` | 0 | -19.550481 | -24.660100 | -28.434889 | 5 / 5 | 0.911 | 2 個 candidate failure 不納入 objective 統計 |
| `5x20` | 5 | 0.000000 | 0.000000 | 0.000000 | 3 / 5 | 0.422 | refresh 後進入全和局區域 |
| `5x20` | 10 | 0.252530 | ≈0.000000 | -0.063133 | 5 / 5 | 0.867 | 全部都在同一個 ≤1 fitness tier |
| `5x20` | 15 | 1.400661 | 0.807199 | 0.593958 | 3 / 5 | 0.289 | fitness span 0.806703，仍屬同一 tier |
| `5x20` | 20 | 1.326067 | 1.065213 | 1.000000 | 2 / 5 | 0.400 | 4 個同 signature，1 個為另一 signature |

> 每次 snapshot refresh 都會更換 self-play 對手 context，因此 refresh 前後的 fitness 絕對值不能直接解讀為策略退步或進步。例如 `10x10` generation 4 的 91.388695 與 generation 5 的 0.666667，是在不同對手 snapshot 下得到的分數。

### 1.2 Semantic tie-break 的實際行為

`10x10` 的 population 在 generation 2 已收斂成單一語意，並維持到 generation 10。檢查每代 parent+offspring selection pool 後可見：最高 fitness tier 從 generation 0 起都只有 **1 種語意**。因此這不是「有不同語意卻沒有被 tie-break 保留」；而是符合 fitness 門檻的候選本身沒有語意替代方案。tie-break 只能在同一 fitness tier 中排序，不能跨越大於 1 的 fitness 差距保留較差但不同的行為。

`5x20` 則提供了 tie-break 生效的正面例子：

- generation 5：同 tier 10 個候選、3 種語意，最終 5 個 survivor 保留 3 種；
- generation 8：同 tier 10 個候選、10 種語意，最終 5 個 survivor 全部語意不同；
- generation 20：同 tier 10 個候選只剩 2 種語意，最終保留兩者，但分布為 4+1。

也就是說，`fitness 差距 ≤ 1` 的語意保留機制確實在候選池有選擇時發揮作用，但 **較小 population 的語意多樣性仍會受到 drift 與單一高分語意擴張影響**。兩個 final-test candidates 的 9 個 probe actions 全部不同，跨 run Hamming distance 為 1.0，證明它們是完全不同的 probe-level 行為。

### 1.3 被選入 final test 的個體

| 項目 | `10x10` | `5x20` |
|---|---|---|
| Candidate | `gen_0010_ff9036cb460e` | `gen_0020_c7d5a03cdc63` |
| Self-play fitness | 0.666667 | 1.326067 |
| Self-play W/D/L | 60 / 60 / 60 | 0 / 180 / 0 |
| Policy 重點 | Ranged early pressure、worker economy、Barracks、Light/Heavy support | Worker economy、Base expansion、Light/Ranged 專打 Worker |
| Code Quality（diagnostic） | 22.517652 | 35.877278 |
| Strategy Alignment（diagnostic） | 6 / 10 | 7 / 10 |

`5x20` 的 Code Quality 與 Alignment 都較高，但固定對手結果反而大幅較差。這符合系統設計：兩者只是 diagnostic，並非 selection objective；也再次說明「程式較簡單／較符合文字策略」不等同於「遊戲表現較好」。

## 2. 固定對手 final test

### 2.1 整體表現

| 指標 | `10x10` | `5x20` | 差異 |
|---|---:|---:|---:|
| Wins | 257（42.83%） | 0（0.00%） | `10x10` +257 |
| Losses | 321（53.50%） | 388（64.67%） | `10x10` 少 67 敗 |
| Draws | 22（3.67%） | 212（35.33%） | `5x20` 多 190 和 |
| Errors | 0 | 0 | 相同 |
| p0 W/L/D | 114 / 179 / 7 | 0 / 194 / 106 | `10x10` p0 勝率 38.00% |
| p1 W/L/D | 143 / 142 / 15 | 0 / 194 / 106 | `10x10` p1 勝率 47.67% |
| Contained opponent faults | 0 | 0 | 相同 |

`10x10` 不只會擊敗 Passive/Random，也能在部分 map 上擊敗 rush 與 tournament agents。`5x20` 則只有拖和能力，沒有任何固定對手勝局。

### 2.2 各對手 W/L/D

每個對手共 60 場。

| Opponent | `10x10` W/L/D | `5x20` W/L/D | 解讀 |
|---|---:|---:|---|
| PassiveAI | 60 / 0 / 0 | 0 / 0 / 60 | `10x10` 完勝；`5x20` 全和 |
| RandomAI | 60 / 0 / 0 | 0 / 0 / 60 | `10x10` 完勝；`5x20` 全和 |
| RandomBiasedAI | 46 / 2 / 12 | 0 / 8 / 52 | `10x10` 勝率 76.67% |
| LightRush | 20 / 40 / 0 | 0 / 40 / 20 | `10x10` 只在 8×8 取勝 |
| HeavyRush | 30 / 20 / 10 | 0 / 40 / 20 | `10x10` 對此對手最有競爭力 |
| WorkerRush | 10 / 50 / 0 | 0 / 60 / 0 | 兩者皆弱，`10x10` 僅 8×8/p1 可勝 |
| AllInBot | 10 / 50 / 0 | 0 / 60 / 0 | 同上；無 opponent fault containment |
| Mayari | 11 / 49 / 0 | 0 / 60 / 0 | `10x10` 有少量勝局 |
| COAC | 10 / 50 / 0 | 0 / 60 / 0 | `10x10` 主要在 16×16/p1 取勝 |
| TMA | 0 / 60 / 0 | 0 / 60 / 0 | 兩者皆完全無法取勝 |

### 2.3 各地圖 W/L/D

每張地圖整合十個對手，共 200 場。

| Map | `10x10` W/L/D | `10x10` 勝率 | `5x20` W/L/D | `5x20` 勝率 |
|---|---:|---:|---:|---:|
| 8×8 | 130 / 70 / 0 | 65.00% | 0 / 103 / 97 | 0.00% |
| 16×16 | 77 / 111 / 12 | 38.50% | 0 / 144 / 56 | 0.00% |
| 24×24 | 50 / 140 / 10 | 25.00% | 0 / 141 / 59 | 0.00% |

`10x10` 有明顯的 map-size degradation：地圖越大，勝率越低。這和它偏向 early pressure 的策略一致；在 24×24 上，接觸時間變長、經濟與長期 production 更重要，策略優勢下降。`5x20` 在三張圖都沒有勝局，問題不是單一地圖特化，而是整體缺乏終結比賽的能力。

## 3. 穩定性與成本

| 指標 | `10x10` | `5x20` |
|---|---:|---:|
| Candidate artifacts | 130 | 130 |
| Evaluated / failed | 125 / 5 | 127 / 3 |
| Failure stages | runtime 2、integration 1、compilation 1、validation 1 | runtime 3 |
| Search match attempts | 22,860 | 23,400 |
| Failed match attempts | 12（0.05%） | 54（0.23%） |
| LLM request events | 831 | 763 |
| Active generation time | 8:02:10 | 10:19:12 |
| Aggregate evaluation time | 2:44:15 | 5:45:47 |
| Aggregate LLM request time | 1:59:09 | 1:12:41 |
| Generation wall span | 8:02:11 | 18:00:39 |

`5x20` 雖然 LLM request 較少、總 offspring 數相同，但 evaluation time 是 `10x10` 的約 2.1 倍。主要原因是它產生大量跑到 tick limit 的和局／長局。其 wall span 額外包含 generation 3 到 4 間約 7 小時 41 分的空檔；artifacts 只能證明有此空檔與 generation 4 的額外 refresh，無法單憑結果檔確定停頓原因。

## 4. Artifact 有效性警告

目前架構契約要求 self-play refresh 使用既有 phenotype、不得重新生成 Java。兩個 run 的 `generation_*_self_play_parent_refresh.json` 卻記錄了以下 audit 結果：

| Run | Refresh records | Java hash preserved | Java hash changed |
|---|---:|---:|---:|
| `10x10` | 20（gen 5、10） | 5 | 15 |
| `5x20` | 25（gen 4、5、10、15、20） | 8 | 17 |

sidecar 的 mode 雖標示 `phenotype_preserving_fitness_refresh`，但多數 record 的 `generated_java_preserved` 為 `false`，且 source/replica SHA-256 不同。`5x20` 還多出 generation 4 的 context migration refresh；這使兩組 candidate 數同為 130，但 refresh 組成不同。

因此：

1. final test 本身仍是可讀的實際執行結果；兩個受測 candidate 都通過 Integration，600 場也沒有 error。
2. 演化路徑不應視為完全符合目前的 phenotype-preserving self-play contract。
3. 不能將最終差異只歸因於 population 10/5 與 generations 10/20；refresh Java 漂移是明確的混淆因子。

## 5. 綜合判斷

就這兩次 run 而言，**`10x10` 是較好的設定**：它的外部泛化、勝局數與小／中地圖戰力都遠高於 `5x20`。`5x20` 的較長演化沒有帶來更強策略，反而找到一個在 self-play shaping 下略為正分、但幾乎只會拖和或落敗的局部最優解。

語意 tie-break 本身不是主要失敗點。它在 `5x20` 的中期確實保留不同 probe behavior；真正的限制是：

- fitness tier 中若只剩單一語意，tie-break 無從選擇；
- 9 個固定 probe states 只能表示局部 action semantics，不能保證完整對局的進攻性或泛化；
- self-play snapshot 可能共同收斂到互相和局的族群；
- shaping score 可讓「沒有勝局但資源／兵力略優」的策略高於其他全和局策略。

## 6. 建議後續實驗

1. **先修正並加嚴 refresh invariant。** refresh 時若 source/replica phenotype SHA-256 不同，應直接 fail，而不是只在 sidecar 留下 `false`。
2. **至少重跑 3 個獨立 replicates。** 保留相同兩種 budget 配置，但需分開記錄 LLM 初始 population；只靠同一 `random_seed` 無法控制 LLM sampling。
3. **增加 checkpoint fixed-roster evaluation。** 建議在每次 refresh 前後測一次代表 candidate，及早偵測 self-play fitness 上升但固定對手退化的 draw attractor。
4. **另列 win-based 指標。** 保留現有 Game Performance shaping，但報表應同時呈現 self-play W/D/L；必要時可測試把勝率或「非全和局」約束加入 selection，而不是只看 shaped mean。
5. **擴充 semantic probes。** 目前 9 個 probes 能分辨 action semantics，但不足以識別「長期不終結比賽」。可增加需要 production、接敵與終局處理的 probe states，或加入短 rollout behavior signature。
6. **若只能先選一個配置，使用 `10x10` 作為下一輪 baseline。** 它目前有明確可驗證的 fixed-roster 戰力；`5x20` 應在修正 refresh 與 draw-attractor 偵測後再重跑。
