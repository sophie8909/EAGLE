# EAGLE 父代重新生成實驗簡報內容

日期：2026-09-14

主題：父代在每代評估時重新生成 Java，與沿用既有 phenotype 的差異

形式：投影片內容草稿，不含簡報版面製作

---

## Slide 1｜父代評估方式比較

### 標題

本次實驗中，父代重生削弱跨代保留效果

### 副標題

相同 generation 0、20 代、族群大小 10、Ministral 3 8B、opponent-wise lexicase

### 講者備註

本次比較回答一個架構問題：已通過評估並被選入下一代的父代，後續應直接沿用既有 Java phenotype 與 fitness，還是用相同 genotype 再呼叫 Generator、重新評估。正式設計採用前者，本次額外補跑後者作為診斷實驗。

---

## Slide 2｜結論摘要

### 投影片文字

父代重生在這次實驗中同時降低戰力與增加成本：

| 指標 | 不重生 `reuse_cached` | 重生 `regenerate_same_genotype` | 重生差異 |
|---|---:|---:|---:|
| 最終最佳 Game Performance | **-50.51** | -79.34 | -28.83 |
| 最終族群平均 | **-65.35** | -87.29 | -21.94 |
| 最終族群勝率 | **28.33%** | 4.89% | -23.44 個百分點 |
| 20 代 committed time | **16.43 小時** | 26.25 小時 | +59.8% |
| 最終 case-wise maxima | **9/10 cases 較高** | 1/10 case 較高 | 明顯落後 |

### 頁面結論

這份單次對照支持目前的正式設計：父代通過評估後，後續世代沿用既有 phenotype 與 fitness。

### 建議視覺

中央放置兩個主要數字：`-50.51 vs -79.34`、`16.43 h vs 26.25 h`。右下角標示「case-wise maxima：9/10」。

### 講者備註

Game Performance 是加權報告指標。EAGLE 的 survivor selection 實際使用 10 個 opponent cases 執行 lexicase，因此 case-wise maxima 是更貼近 optimizer 的證據。兩種證據得到相同方向。

---

## Slide 3｜實驗控制與共同起點

### 投影片文字

| 項目 | 不重生 | 重生 |
|---|---|---|
| Run | `20260911_072610_382082` | `20260912_parent_regenerate_same_genotype_from_20260911_gen0` |
| 父代評估模式 | 欄位不存在，採預設 `reuse_cached` | `regenerate_same_genotype` |
| Generation 0 | 1 個 Worker Rush policy，加 9 個 LLM policies | 從左側 run 的 generation 0 checkpoint 分支 |
| Generation 0 Java | 10 個 candidate 共用 Worker Rush Java seed | candidate IDs、三個 genotype components、phenotype hashes 完全相同 |
| 規模 | 20 代，族群大小 10 | 20 代，族群大小 10 |
| LLM parallel | 1 | 1 |

兩份 resolved config 的實質差異只有：

- `experiment_name`
- `parent_evaluation_mode`

### 頁面結論

兩組從同一個已完成的 generation 0 出發，避免重新抽樣九個初始 LLM policies 所造成的混淆。

### 講者備註

本次 treatment 使用 checkpoint fork，不重新建立 generation 0。兩組共用 random seed、模型、mutation 機率、地圖、對手與評估矩陣。

---

## Slide 4｜兩種父代評估流程

### 投影片文字

| 階段 | 不重生 `reuse_cached` | 重生 `regenerate_same_genotype` |
|---|---|---|
| 父代進入下一代 | 保留原 candidate ID | 建立 fresh-ID replica |
| Java phenotype | 沿用已驗證與評估的 Java | 用相同 genotype 再呼叫 Generator |
| Fitness | 沿用既有 10-case vector | 重新完成 validation、compile、integration 與 180 matches |
| Survivor pool | cached parents 加 offspring | regenerated parent replicas 加 offspring |
| 原父代 artifact | 保留且可追溯 | 保留，但不直接參與下一輪 selection |

重生模式限制在：

- `candidate_java_mode: inherited_genotype`
- `reflection_operator_mode: static`
- 每代另存 parent rematerialization audit sidecar

### 頁面結論

重生模式保留的是 genotype。原本通過 selection 的 Java phenotype 與 fitness 不受保護。

### 建議視覺

以左右兩欄流程呈現。左側只有一次 phenotype 與 evaluation，右側每代重複 Generator 與 evaluation。

---

## Slide 5｜最終族群戰力差距

### 投影片文字

分數越高越好。下表來自 generation 20 survivor population。

| 指標 | 不重生 | 重生 | 不重生優勢 |
|---|---:|---:|---:|
| Best GP | **-50.51** | -79.34 | +28.83 |
| Mean GP | **-65.35** | -87.29 | +21.94 |
| Median GP | **-67.67** | -89.63 | +21.96 |
| Worst GP | **-73.69** | -90.68 | +16.98 |
| W / D / L | **510 / 169 / 1,121** | 88 / 384 / 1,328 | 多 422 勝 |
| 勝率 | **28.33%** | 4.89% | +23.44 個百分點 |

兩組 final population 都完成 `1,800 / 1,800` 場搜尋評估，沒有 survivor evaluation failure。

### 頁面結論

重生組的差距涵蓋最佳個體、族群中央趨勢與最差個體，並非少數 outlier 造成。

### 建議視覺

左側用 box-like summary 顯示 best、median、worst。右側使用 100% stacked bar 呈現 W/D/L。

### 講者備註

這裡的 W/D/L 來自搜尋期間固定 evaluation matrix。Treatment 以 `--skip-final-test` 完成，因此沒有可與 baseline final test 對照的 holdout 結果。

---

## Slide 6｜十個 lexicase cases 的最終上限

### 投影片文字

Final population 中，每個 opponent case 的最高分：

| Opponent case | 不重生 max | 重生 max | 重生差異 |
|---|---:|---:|---:|
| Passive | **106.33** | 102.37 | -3.95 |
| Random | **107.41** | 33.46 | -73.94 |
| RandomBiased | **106.54** | 26.79 | -79.75 |
| LightRush | **18.05** | -65.79 | -83.84 |
| HeavyRush | **35.60** | -65.94 | -101.54 |
| WorkerRush | **-49.13** | -99.20 | -50.06 |
| AllInBot | **-66.30** | -99.68 | -33.38 |
| Mayari | **-68.24** | -100.02 | -31.78 |
| COAC | **-67.03** | -100.15 | -33.12 |
| TMA | -100.45 | **-99.90** | +0.55 |

### 頁面結論

不重生組在 9 個 cases 保留較強 specialist。重生組只在 TMA 高 0.55 分，兩組對 TMA 都是 180 場全敗，沒有形成實質競爭力。

### 建議視覺

使用水平 dumbbell chart。以 0 分作為參考線，保留所有負分，不截斷座標。

### 講者備註

Lexicase 不直接最佳化 aggregate GP。Case-wise maxima 顯示重生造成的傷害也存在於 optimizer 真正使用的 opponent objectives。

---

## Slide 7｜跨代演化軌跡

### 投影片文字

| Generation | 不重生 best | 重生 best | 不重生 mean | 重生 mean |
|---:|---:|---:|---:|---:|
| 0 | -90.29 | -90.29 | -90.65 | -90.65 |
| 1 | -81.96 | -90.10 | -89.88 | -91.24 |
| 5 | -78.26 | -80.50 | -86.44 | -86.43 |
| 10 | -69.34 | -79.82 | -79.14 | -83.30 |
| 15 | -52.10 | -78.93 | -70.74 | -87.85 |
| 20 | **-50.51** | -79.34 | **-65.35** | -87.29 |

Generation 0 到 generation 20：

- 不重生 best 改善 `+39.78`，mean 改善 `+25.29`
- 重生 best 改善 `+10.95`，mean 改善 `+3.35`
- 重生組的 run 內 best 峰值為 generation 8 的 `-78.69`，後續沒有突破

### 頁面結論

兩組在前五代差距仍小。Generation 10 之後，不重生組持續累積 specialist，重生組停在約 -80 的 best GP。

### 建議圖表

雙折線圖分成上下兩層。上層畫 best GP，下層畫 population mean。兩圖共用 generation 軸與 0 分參考線。

---

## Slide 8｜相同 genotype 不會產生穩定 phenotype

### 投影片文字

20 代共產生 200 個 parent replicas：

| Audit 指標 | 結果 |
|---|---:|
| 三個 genotype component hashes 完全相同 | **200 / 200** |
| 重新生成後 Java hash 改變 | **184 / 200（92.0%）** |
| Replica evaluation failure | **9 / 200（4.5%）** |
| Replica 被選入 survivor population | **111 / 200（55.5%）** |

九次 replica failure 包含 7 次 compilation failure 與 2 次 validation failure。

只看 191 個成功評估的 replicas：

- 與 source parent 相比，weighted GP 平均變化 `-0.28`
- 中位數變化 `-0.20`
- 85 次改善，106 次下降
- 單次變化範圍為 `-11.69` 到 `+11.04`

### 頁面結論

Generator 對同一 genotype 具有高度取樣變異。成功重生的平均 GP 漂移不大，但方向不穩定，另有 4.5% 的 catastrophic failure tail。

### 講者備註

九個失敗 replica 會收到十個 `-1000` fitness sentinels。若把失敗也放入 paired aggregate，比較平均會降到 `-41.29`。這個數值受 sentinel 主導，因此投影片正文分開呈現成功漂移與失敗率。

---

## Slide 9｜重生移除了 phenotype 層級的 elitism

### 投影片文字

Final population 的 birth generation：

| 條件 | Generation 20 survivor 的出生代 |
|---|---|
| 不重生 | 12、16、18、18、18、19、19、20、20、20 |
| 重生 | 20、20、20、20、20、20、20、20、20、20 |

觀察：

- 不重生組保留 7 個較早世代的 survivor
- 最老的 survivor 從 generation 12 保留到 generation 20
- 重生組每代將舊父代替換成 fresh-ID replica
- Replica 雖有 55.5% 被選回，保留下來的是新抽樣 phenotype

### 頁面結論

重生模式讓 lineage 看起來每代更新，也使已驗證的強 phenotype 無法跨代鎖定。Selection 必須反覆承擔 Generator 與 match evaluation 的取樣風險。

### 建議視覺

用簡單 timeline 顯示不重生組的長壽 survivor。重生組每一代只顯示當代 birth marker。

---

## Slide 10｜運算成本

### 投影片文字

以下採用 20 個正式提交 generation timing 的總和，不含 generation 0：

| 時間指標 | 不重生 | 重生 | 倍率 |
|---|---:|---:|---:|
| Generation wall time | **16.43 h** | 26.25 h | 1.60× |
| 平均每代 | **49.28 min** | 78.75 min | 1.60× |
| LLM requests 累積時間 | **4.52 h** | 10.87 h | 2.40× |
| Evaluation 累積時間 | **5.41 h** | 8.99 h | 1.66× |

重生組每代額外處理 10 個 parent replicas：

- 再次執行 Java generation
- 再次 validation、compilation 與 integration
- 成功時再次執行 180 matches

### 頁面結論

重生增加約 9.82 小時的 committed search time。最大增量來自額外 LLM decoding 與完整 evaluation。

### 講者備註

Treatment 在 generation 2 曾中斷並從 generation 1 的 atomic checkpoint resume。表內只加總正式提交的 generation records，排除中斷段的額外成本，因此 60% 是保守估計。

---

## Slide 11｜性能下降的作用機制

### 投影片文字

實驗 artifact 支持以下機制：

1. 同一 genotype 再次送入 Generator，92% 產生不同 Java
2. 新 Java 改變 opponent-wise fitness，成功 replicas 仍有 106/191 下降
3. 4.5% replicas 失敗，其中 7 次停在 compilation、2 次停在 validation
4. Lexicase 在新的 case vector 上選擇，原本的高分 phenotype 不再保證存活
5. 每代重複此過程，跨代 elitism 逐步被 decoder 與 match noise 取代

### 頁面結論

重生測量的是 genotype 經過一次新 decode 後的樣本，不再是原本被 selection 接受的 agent。這會改變演化狀態的語義。

### 講者備註

即使 successful replica 的 aggregate GP 平均只下降 0.28，lexicase 仍會對個別 opponent case 的變化敏感。Aggregate 接近不代表 selection behavior 接近。

---

## Slide 12｜可支持與不可支持的結論

### 投影片文字

目前證據支持：

- Baseline 確實使用不重生行為
- 相同 genotype 在重新 decode 後通常產生不同 Java phenotype
- 本次重生 run 的 final population 在 9/10 lexicase cases 落後
- 重生增加約 60% committed wall time
- 正式流程應維持 `parent_evaluation_mode: reuse_cached`

目前證據仍有限制：

- 每個條件只有一個 evolutionary run，沒有跨 seed 變異
- Treatment 曾在 generation 2 中斷並安全 resume
- LLM decoding 與 MicroRTS repetitions 具有隨機性，兩條 trajectory 無法 request-by-request 配對
- Treatment 沒有 final test，不能宣稱 holdout 泛化差距

### 頁面結論

這是一個控制良好的架構診斷，足以確認重生的作用與風險。跨 seed 重複實驗仍是統計性結論的必要條件。

---

## Slide 13｜架構決策

### 投影片文字

正式路徑：

- 保持 `parent_evaluation_mode: reuse_cached` 為預設值
- Survivor 直接沿用 candidate ID、phenotype、compiled classes 與 fitness
- Offspring 才進行 mutation、materialization 與完整 evaluation

診斷路徑：

- 保留 `regenerate_same_genotype` 作為非正式實驗模式
- 保留 source parent 與 replica 的 hash、fitness、status、selection sidecar
- 禁止將重生模式結果當作正常 EAGLE 演化基準

後續驗證：

- 若需要統計置信度，至少補多個 evolutionary seeds
- 為兩個條件都執行相同 final-test protocol
- 另做固定 genotype 的多次 decode，分離 Generator variance 與 match variance

### 頁面結論

目前不需要修改正式行為。實驗模式已提供足夠 observability，可用於未來的 variance decomposition。

---

## Slide 14｜資料來源與指標定義

### Run artifacts

- [不重生 baseline run](../../runs/20260911_072610_382082/)
- [父代重生 treatment run](../../runs/20260912_parent_regenerate_same_genotype_from_20260911_gen0/)
- [Baseline final generation](../../runs/20260911_072610_382082/generations/generation_0020.json)
- [Treatment final generation](../../runs/20260912_parent_regenerate_same_genotype_from_20260911_gen0/generations/generation_0020.json)
- [Treatment generation 20 rematerialization audit](../../runs/20260912_parent_regenerate_same_genotype_from_20260911_gen0/generations/generation_0020_parent_rematerialization.json)

### Configs

- [Canonical reuse-cached config](../../configs/experiments/0912_parent_evaluation_comparison_20x10/01_reuse_cached_20x10.yaml)
- [Regenerate-same-genotype config](../../configs/experiments/0912_parent_evaluation_comparison_20x10/02_regenerate_same_genotype_20x10.yaml)

### 指標定義

- Fitness：10 個 opponent scores，lexicase selection 的實際輸入
- Game Performance：固定權重總和 12.5 的 reporting aggregate
- Complete candidate：10 opponents × 3 maps × 3 rounds × 2 sides，共 180 matches
- Failure sentinel：任一 terminal evaluation failure 對 10 個 cases 全部記為 `-1000`
- Committed time：`timing.jsonl` 中 `event: generation` 的 duration 總和

### 講者備註

簡報中的所有比較都從 `eagle-run-v2` manifest、generation snapshots、candidate artifacts、parent rematerialization sidecars 與 committed timing records 重算。沒有使用 partial terminal output 推估正式結果。
