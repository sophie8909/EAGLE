# EAGLE 三種 Reflection 等比例實驗：完整五代演化紀錄

- 實驗 run：`/home/mhlab/EAGLE/runs/20260907_154823_943103`
- 實驗日期：2026-09-07
- 模型：`ministral3_8b`
- 範圍：初始族群 Generation 0，加上 Generation 1–5 的五次演化
- Config：`configs/experiments/0907_3_reflection_equal_5gen_3pop/ministral3_8b_static_0.33_0.33_0.34_5gen_3pop_llm_mixed.yaml`
- 狀態：搜尋完成；本次以 `--skip-final-test` 執行，因此沒有額外 final-test tournament

## 1. 實驗設定

| 項目 | 設定 |
| --- | --- |
| Population | 3 |
| Evolution generations | 5 |
| 初始族群 | 1 個 Worker Rush policy + 2 個獨立 LLM policy |
| Generation 0 Java | 三個個體共用固定 Worker Rush Java |
| Java 模式 | `inherited_genotype` |
| Parent selection | seeded lexicase |
| Survivor selection | `mu_plus_lambda` lexicase；父代與子代共同競爭 |
| Crossover rate | 0.75 |
| Mutation rate | 1.0 |
| Reflection mode | `static` |
| Strategy / Prompt / Code | 0.33 / 0.33 / 0.34 |
| 每個可執行個體 | 10 opponents × 3 maps × 3 rounds × 2 sides = 180 matches |
| Fitness | 十個 opponent-wise cases；aggregate Game Performance 僅供報告，不直接決定 lexicase |

機率是每個 offspring 的獨立抽樣，不是每代固定配額。15 個正式提交的 offspring 實際抽到 Strategy 6 次、Prompt 6 次、Code 3 次，即 40% / 40% / 20%。

## 2. 五代總覽

表中的「最佳」與「平均」均是該代最後三個 survivor 的 aggregate Game Performance；數值越高越好。

| Snapshot | S / P / C 抽樣 | Mutation 成功 | 最佳 | 平均 | 相較前代平均 | Aggregate 最佳個體 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Gen 0 | 0 / 0 / 0 | — | -90.301470 | -90.584344 | — | `gen_0000_9c608be22e73` |
| Gen 1 | 2 / 1 / 0 | 2 / 3 | -89.643787 | -90.155098 | +0.429246 | `gen_0001_a7938a7eb1a0` |
| Gen 2 | 1 / 2 / 0 | 3 / 3；其中 1 個 Java 最終失敗 | -89.466790 | -90.173634 | -0.018536 | `gen_0002_ba7ec9bbd583` |
| Gen 3 | 1 / 1 / 1 | 2 / 3 | -88.531043 | -89.213873 | +0.959761 | `gen_0003_55fef5bff473` |
| Gen 4 | 1 / 1 / 1 | 2 / 3 | -89.306820 | -89.550586 | -0.336713 | `gen_0004_10691d288d46` |
| Gen 5 | 1 / 1 / 1 | 2 / 3 | -89.035711 | -89.606706 | -0.056120 | `gen_0005_ea6d658df151` |

Gen 4、Gen 5 的平均或最佳值可以下降，原因是 survivor selection 使用十個 opponent cases 的 lexicase，不是依 aggregate 排序；MicroRTS match 本身也未宣稱完全 deterministic。

## 3. Generation 0：初始族群

三個 policy 不同，但 Java 完全相同，均直接執行固定 Worker Rush seed，沒有 Java Generator 呼叫。因此本代分數差異來自 match 隨機性，而不是 Java 行為差異。

| Candidate | Policy 來源 | Policy 摘要 | Aggregate | Code Quality | 結果 |
| --- | --- | --- | ---: | ---: | --- |
| `gen_0000_777745bdc87f` | configured seed | 連續產 Worker；一名 Worker 採集，其餘 rush；不造 Barracks | -90.710516 | 49.705742 | 留下 |
| `gen_0000_9c608be22e73` | LLM generated | 15 條混合 Worker、生產、擴張與 combat-support 規則 | **-90.301470** | 49.705742 | 留下 |
| `gen_0000_3189a402c218` | LLM generated | Ranged/Light 防守、Barracks 建造、經濟與擴張混合策略 | -90.741046 | 49.705742 | 留下 |

十個 fitness cases：

| Candidate | passive | random | randombias | lightrush | heavyrush | workerrush | allinbot | mayari | coac | tma |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `777745` | 3.399455 | 0.976548 | -45.236210 | -100.841740 | -101.095999 | -100.250835 | -99.706806 | -102.442790 | -102.301715 | -101.180077 |
| `9c608b` | 3.399455 | -4.822482 | -28.957208 | -100.841740 | -101.095999 | -100.250835 | -99.706806 | -102.498048 | -102.309913 | -101.180077 |
| `3189a4` | 3.399455 | 0.568717 | -45.281815 | -100.841740 | -101.095999 | -100.250835 | -99.706806 | -102.500838 | -102.321121 | -101.180077 |

Gen 0 survivor：`777745`、`9c608b`、`3189a4`。

## 4. Generation 1

### 4.1 三個 offspring

| Candidate | Parents | Strategy / Prompt / Java provenance | 抽到的 operator | Applied | Java attempts | Aggregate | Quality | 是否留下 |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| `gen_0001_71168d84f174` | `777745` + `9c608b` | `9c608b` / `9c608b` / `777745` | Strategy | 是 | 2 | -90.627361 | 22.392772 | 否 |
| `gen_0001_a7938a7eb1a0` | `9c608b` + `9c608b` | `9c608b` / `9c608b` / `9c608b` | Strategy | 否 | 3 | **-89.643787** | 13.483835 | 是 |
| `gen_0001_edc0461c26b6` | `777745` + `777745` | `777745` / `777745` / `777745` | Prompt | 是 | 1 | -90.110992 | 40.015364 | 是 |

### 4.2 Mutation 內容

- `71168d` 的 Strategy Reflection 成功，將原 15-rule policy 改成 10-rule 的 Barracks + mixed combat policy。第一次 Java 驗證因使用不存在的 `getUnitAt` 失敗，第 2 次 compile repair 通過。
- `a7938a` 抽到 Strategy Reflection，但 Coach 提案違反 closed-world contract，例如部分 actor/action 條件沒有完整表達 idle actor、reachable Resource、合法 production cost 等。Mutation 被拒絕，policy 保留 `9c608b` 的版本；之後仍以 crossover 後 genotype 產生 Java，直到第 3 次成功。
- `edc046` 的 Prompt Reflection 成功。Reviewer 判定 `policy_clear_but_java_violates`；第 1 次 rewrite 因包含具體 `Worker` 被拒，第 2 次新增以下 reusable rule：

> `[rule-d0f3b52a4631] targeting_fallback | Map conditional targeting to explicit branches that enforce sequential movement toward enemy territory before attacking encountered units or structures.`

十個 fitness cases：

| Candidate | passive | random | randombias | lightrush | heavyrush | workerrush | allinbot | mayari | coac | tma |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `71168d` | 2.745227 | -3.893001 | -34.120093 | -100.615763 | -100.764780 | -100.558297 | -99.671991 | -102.617200 | -102.747889 | -101.597539 |
| `a7938a` | 3.399455 | -0.079696 | -23.464883 | -99.977857 | -100.238521 | -100.148115 | -99.706806 | -102.104484 | -102.113608 | -101.130242 |
| `edc046` | 3.399455 | -0.115799 | -34.791839 | -99.977857 | -100.323431 | -100.148115 | -99.706806 | -102.153918 | -102.100984 | -101.130242 |

### 4.3 Survivor selection

最後留下 `edc046`、`a7938a` 與父代 `777745`。Strategy 成功的 `71168d` aggregate 較差且未通過 lexicase survivor selection。

## 5. Generation 2

### 5.1 三個 offspring

| Candidate | Parents | Strategy / Prompt / Java provenance | Operator | Applied | Java attempts | Aggregate | Quality | 是否留下 |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| `gen_0002_220c49fef464` | `edc046` + `a7938a` | `a7938a` / `a7938a` / `a7938a` | Prompt | 是 | 1 | -91.410325 | 13.416945 | 是 |
| `gen_0002_ba7ec9bbd583` | `a7938a` + `a7938a` | `a7938a` / `a7938a` / `a7938a` | Prompt | 是 | 1 | **-89.466790** | 14.196434 | 是 |
| `gen_0002_24e6407ccab1` | `a7938a` + `a7938a` | `a7938a` / `a7938a` / `a7938a` | Strategy | 是 | 5，全部失敗 | -1000.000000 | -1000.000000 | 否 |

### 5.2 Mutation 內容

- `220c49` Prompt Reflection 新增：

> `[rule-9ca6ed90a26c] priority_ordering | Enforce explicit conditional ordering by evaluating higher-priority rules before lower-priority fallback branches in every decision cycle.`

- `ba7ec9` Prompt Reflection 新增：

> `[rule-323a0623d9c1] priority_ordering | For conditional fallback logic, enforce strict priority by evaluating higher-precedence conditions first and only proceeding to lower-priority branches if all preceding checks fail.`

- `24e640` Strategy Reflection 成功產生新的 10-rule mixed strategy，但 Java Generator 和 repair 共用完 5 次仍無法編譯，最終錯誤是 `incompatible types: int cannot be converted to AgentContext`。它保留完整 mutation 與失敗 artifact，但 fitness 十項全為 -1000。

十個 fitness cases：

| Candidate | passive | random | randombias | lightrush | heavyrush | workerrush | allinbot | mayari | coac | tma |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `220c49` | 3.399455 | -5.637648 | -62.027740 | -99.977857 | -100.238521 | -100.148115 | -99.706806 | -102.115146 | -102.113608 | -101.130242 |
| `ba7ec9` | 4.590174 | 1.894182 | -32.962688 | -98.793043 | -98.689978 | -99.992694 | -99.666667 | -102.496433 | -101.177640 | -100.469256 |
| `24e640` | -1000 | -1000 | -1000 | -1000 | -1000 | -1000 | -1000 | -1000 | -1000 | -1000 |

### 5.3 Survivor selection

最後留下 `ba7ec9`、父代 `a7938a`、`220c49`。雖然 `220c49` aggregate 很差，它仍可能在 lexicase 的特定 opponent case 中被選上；aggregate 不是選擇目標。

## 6. Generation 3

### 6.1 三個 offspring

| Candidate | Parents | Strategy / Prompt / Java provenance | Operator | Applied | Java attempts | Aggregate | Quality | 是否留下 |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| `gen_0003_55fef5bff473` | `ba7ec9` + `ba7ec9` | `ba7ec9` / `ba7ec9` / `ba7ec9` | Code | 是 | 2 | **-88.531043** | 14.582314 | 是 |
| `gen_0003_abf0c70391f3` | `ba7ec9` + `ba7ec9` | `ba7ec9` / `ba7ec9` / `ba7ec9` | Strategy | 是 | 3 | -90.384457 | 29.043091 | 否 |
| `gen_0003_0d1da536be42` | `ba7ec9` + `a7938a` | `a7938a` / `ba7ec9` / `ba7ec9` | Prompt | 否 | 1 | -88.648014 | 14.515424 | 否 |

### 6.2 Mutation 內容

- `55fef5` 是第一個正式提交的 Code Reflection offspring。流程確實是：
  1. 先對父代 Java 產生 `reflection_conclusion.json`；
  2. 再把同一份 parsed conclusion、父代 Java、policy 與 immutable contracts 放入 revision request；
  3. revision Java 直接進 validation，不再呼叫一般 Generator。
- 這次 conclusion 為 `code_faithfully_implements_strategy`、`diagnosis: []`，列出 14 項要保留的行為。儘管沒有 required change，revision 仍重寫 Java；原始 reflected output 相對父代為 +23/-51 行，且缺少 lifecycle/scaffold requirement，經 1 次 compile repair 後，canonical phenotype 相對父代實際只剩 +1/-3 行：移除兩個 `continue`，並把 low-HP Base 判斷由 `<10` 改成 `<=2`。
- `abf0c7` Strategy Reflection 成功，產生 10-rule Barracks/Light/Ranged/Worker mixed policy；Java 第 3 次成功，但未被選留。
- `0d1da5` Prompt Reviewer 判定 Java 有 policy mismatch，但三次 rewrite 最終仍含具體詞 `resource`，違反 reusable policy-agnostic rule contract。Mutation 被拒；crossover 後原 genotype 繼續正常產生 Java。

十個 fitness cases：

| Candidate | passive | random | randombias | lightrush | heavyrush | workerrush | allinbot | mayari | coac | tma |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `55fef5` | 4.590174 | 2.244523 | -34.106863 | -98.793043 | -98.689978 | -99.992694 | -99.661667 | **-96.445610** | -101.186585 | -100.469256 |
| `abf0c7` | 2.763441 | 1.111548 | -30.008020 | -100.711300 | -101.550123 | -100.879014 | -99.647222 | -102.449545 | -102.855417 | -101.847199 |
| `0d1da5` | 4.590174 | 1.869158 | -33.967551 | -99.109505 | -99.055190 | -99.981667 | -99.664028 | -96.481297 | -101.410988 | -100.543541 |

### 6.3 Survivor selection

最後留下父代 `a7938a`、父代 `ba7ec9` 與 Code offspring `55fef5`。本代平均提升最大（+0.959761）；`55fef5` 的主要 aggregate 優勢來自 Mayari case 由約 -102.5 上升至 -96.45。

## 7. Generation 4

### 7.1 三個 offspring

| Candidate | Parents | Strategy / Prompt / Java provenance | Operator | Applied | Java attempts | Aggregate | Quality | 是否留下 |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| `gen_0004_4161d4c2eab0` | `55fef5` + `55fef5` | `55fef5` / `55fef5` / `55fef5` | Code | 是 | 2 | -89.808873 | 14.582314 | 否 |
| `gen_0004_b354952e7577` | `a7938a` + `ba7ec9` | `a7938a` / `a7938a` / `ba7ec9` | Prompt | 是 | 1 | -89.878148 | 15.094244 | 是 |
| `gen_0004_10691d288d46` | `ba7ec9` + `55fef5` | `55fef5` / `ba7ec9` / `55fef5` | Strategy | 否 | 1 | **-89.306820** | 14.582314 | 是 |

### 7.2 Mutation 內容

- `4161d4` Code Reflection conclusion 同樣為 `code_faithfully_implements_strategy`、空 diagnosis、14 項 preservation notes。原始 reflected output相對父代為 +12/-35 行，因缺 strategy markers 被 repair；最終 phenotype 相對父代只有一行有效差異：距離 ≥15 時由 `commandAttack(worker, enemyBase)` 改成 `commandMove(...)`。它完成評估但沒有被選留。
- `b35495` Prompt Reflection 成功，在 base generation prompt 上新增：

> `[rule-4582c3c39d19] priority_ordering | When multiple conditional branches apply, enforce explicit fallback ordering by evaluating lowest-priority conditions only after higher-priority alternatives are exhausted.`

- `10691d` Strategy Reflection 提案因部分 Heavy/Ranged/Worker branch 沒有完整表達 idle actor、現存 target 與合法 attack condition，被 closed-world contract 拒絕。Mutation 沒套用，但 crossover 已經從 `55fef5` 取得 strategy 與 Java component、從 `ba7ec9` 取得 generation prompt，因此仍形成可評估的新組合並被保留。

十個 fitness cases：

| Candidate | passive | random | randombias | lightrush | heavyrush | workerrush | allinbot | mayari | coac | tma |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `4161d4` | 4.590174 | -9.656760 | -29.739097 | -98.793043 | -98.689978 | -99.992694 | -99.660555 | -102.537927 | -101.198440 | -100.469256 |
| `b35495` | 4.590174 | -9.850390 | -29.302660 | -99.109505 | -99.055190 | -99.981667 | -99.652639 | -102.459051 | -101.369295 | -100.543541 |
| `10691d` | 4.590174 | 0.900717 | -27.842887 | -98.793043 | -98.689978 | -99.992694 | -99.655972 | -102.528205 | -101.188337 | -100.469256 |

### 7.3 Survivor selection

最後留下 Prompt offspring `b35495`、父代 `ba7ec9` 與 mutation 被拒但 crossover 有效的 `10691d`。Code offspring `4161d4` 被淘汰；前代 aggregate 最佳 `55fef5` 也沒有留在本代 snapshot。

## 8. Generation 5

### 8.1 三個 offspring

| Candidate | Parents | Strategy / Prompt / Java provenance | Operator | Applied | Java attempts | Aggregate | Quality | 是否留下 |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| `gen_0005_493b33588612` | `b35495` + `ba7ec9` | `ba7ec9` / `ba7ec9` / `b35495` | Strategy | 否 | 1 | -89.906259 | 11.744704 | 是 |
| `gen_0005_47c31f864eb5` | `ba7ec9` + `b35495` | `b35495` / `ba7ec9` / `b35495` | Prompt | 是 | 1 | -89.660541 | 14.708365 | 否 |
| `gen_0005_ea6d658df151` | `ba7ec9` + `b35495` | `ba7ec9` / `b35495` / `ba7ec9` | Code | 是 | 4 | **-89.035711** | 14.196434 | 是 |

### 8.2 Mutation 內容

- `493b33` Strategy Reflection 提案因 Light production 沒有同時說明 idle Barracks、至少 2 resources，且 Heavy attack branch 沒有完整處理 target range，被 contract 拒絕。它仍保留 crossover 組合並通過 Java/evaluation，最後被 lexicase 留下。
- `47c31f` Prompt Reflection 移除 `rule-323a0623d9c1`，換成：

> `[rule-3cdc2e4db57c] priority_ordering | For conditional priority logic, evaluate all precedence conditions in strict order and short-circuit to the highest-priority valid action.`

- `ea6d65` Code Reflection conclusion 仍為 `code_faithfully_implements_strategy`、空 diagnosis、14 項 preservation notes。原始 revision 相對父代為 +3/-109 行，缺 lifecycle methods；後續三次 repair 中又兩度使用禁止的 `GameState.free`，第 4 個 generation attempt 才通過。最終 canonical phenotype 相對父代只改一行：low-HP Base 判斷 `<10` 改為 `<=2`。

十個 fitness cases：

| Candidate | passive | random | randombias | lightrush | heavyrush | workerrush | allinbot | mayari | coac | tma |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `493b33` | 4.590174 | -9.538836 | -33.117424 | -98.793043 | -98.689978 | -99.992694 | -99.664722 | -102.351803 | -101.173961 | -100.469256 |
| `47c31f` | 4.590174 | 1.749768 | -35.102158 | -99.109505 | -99.055190 | -99.981667 | -99.667917 | -102.512483 | -101.390704 | -100.543541 |
| `ea6d65` | 4.590174 | 2.130108 | **-23.240056** | -98.793043 | -98.689978 | -99.992694 | -99.635972 | -102.311505 | -101.188661 | -100.469256 |

### 8.3 Final survivor population

最後留下：

1. `gen_0005_ea6d658df151`：Code Reflection offspring，aggregate -89.035711。
2. `gen_0004_b354952e7577`：前代 Prompt Reflection survivor，aggregate -89.878148。
3. `gen_0005_493b33588612`：Strategy mutation 被拒，但 crossover genotype 有效，aggregate -89.906259。

## 9. 三種 Reflection 的整體結果

| Operator | 抽到次數 | 成功套用 | 成功產生可執行 Java | 最終代 survivor 中直接代表 | 主要觀察 |
| --- | ---: | ---: | ---: | ---: | --- |
| Strategy | 6 | 3 | 2 | 0；但 `493b33` 是 rejected-mutation crossover child | 能改變 strategy 類型；closed-world contract 擋下 3 次規則表述不完整；另有 1 次 Java 五次皆失敗 |
| Prompt | 6 | 5 | 5 | 1 (`b35495`) | 主要反覆增加或替換 `priority_ordering`；1 次因具體詞 `resource` 被拒 |
| Code | 3 | 3 | 3 | 1 (`ea6d65`) | 兩階段順序正確，但三次 reflection 都判定原 code 已 faithful；revision 仍改 code，且三次都需後續 repair |

### 關鍵判讀

1. **Code Reflection 的控制流程已正確分成「先結論、後改 code」**。三個 candidate 都有獨立 diagnosis 與 revision artifacts，revision request 也包含原 parsed conclusion。
2. **目前 Code Reflection 的語意決策仍有一個值得修正的點**：三次 assessment 都是 `code_faithfully_implements_strategy` 且 diagnosis 為空，但系統仍強制呼叫 revision 並改動 Java。若設計意圖是「只有發現 mismatch 才改 code」，應在 faithful + empty diagnosis 時直接保留父代，或要求 conclusion 明確提供 revision objective。
3. **Revision 對 scaffold 的一次成功率仍低**：三次原始 revision 全部需要 compile-repair，分別需要 1、1、3 次 repair。最終 canonical code 差異其實很小，但原始 reflected files 的改寫幅度很大。
4. **Prompt Reflection 有實際 genotype 變化，但多數變化集中在相似的 priority-ordering 規則**。它不是完全沒運作，只是策略/行為層面的可見差異有限。
5. **Strategy Reflection 的方向最可見，但有效率為 3/6，且成功改 policy 不保證 Java 能生成成功或被選留。**
6. **五代內 aggregate 最佳由 -90.301470 改善至 -89.035711（+1.265759）**；全程最佳 observation 是 Gen 3 的 `55fef5`：-88.531043，但它在 Gen 4 lexicase selection 後消失。

## 10. 唯一 policy 版本索引

本 run 實際出現六個不同 policy hash；其餘 candidate 都繼承其中之一。

| Policy hash | 首次出現 | 說明 | Canonical artifact |
| --- | --- | --- | --- |
| `effc9103a539` | `gen_0000_777745bdc87f` | configured Worker Rush | `/home/mhlab/EAGLE/runs/20260907_154823_943103/candidates/gen_0000_777745bdc87f/genotype/policy_prompt.txt` |
| `a97fe8e2bf91` | `gen_0000_9c608be22e73` | LLM 15-rule mixed Worker policy；後續主幹 | `/home/mhlab/EAGLE/runs/20260907_154823_943103/candidates/gen_0000_9c608be22e73/genotype/policy_prompt.txt` |
| `0502d589c745` | `gen_0000_3189a402c218` | LLM Ranged/Light defensive expansion | `/home/mhlab/EAGLE/runs/20260907_154823_943103/candidates/gen_0000_3189a402c218/genotype/policy_prompt.txt` |
| `ad34caaa229f` | `gen_0001_71168d84f174` | Strategy Reflection：Barracks mixed combat | `/home/mhlab/EAGLE/runs/20260907_154823_943103/candidates/gen_0001_71168d84f174/genotype/policy_prompt.txt` |
| `428c3b3e1d52` | `gen_0002_24e6407ccab1` | Strategy Reflection：10-rule mixed strategy；Java 失敗 | `/home/mhlab/EAGLE/runs/20260907_154823_943103/candidates/gen_0002_24e6407ccab1/genotype/policy_prompt.txt` |
| `341a33994b4b` | `gen_0003_abf0c70391f3` | Strategy Reflection：Barracks/Light/Ranged strategy | `/home/mhlab/EAGLE/runs/20260907_154823_943103/candidates/gen_0003_abf0c70391f3/genotype/policy_prompt.txt` |

## 11. 重要 artifact 索引

### Run 與每代 snapshot

- `/home/mhlab/EAGLE/runs/20260907_154823_943103/manifest.json`
- `/home/mhlab/EAGLE/runs/20260907_154823_943103/config.yaml`
- `/home/mhlab/EAGLE/runs/20260907_154823_943103/generations/generation_0000.json`
- `/home/mhlab/EAGLE/runs/20260907_154823_943103/generations/generation_0001.json`
- `/home/mhlab/EAGLE/runs/20260907_154823_943103/generations/generation_0002.json`
- `/home/mhlab/EAGLE/runs/20260907_154823_943103/generations/generation_0003.json`
- `/home/mhlab/EAGLE/runs/20260907_154823_943103/generations/generation_0004.json`
- `/home/mhlab/EAGLE/runs/20260907_154823_943103/generations/generation_0005.json`
- `/home/mhlab/EAGLE/runs/20260907_154823_943103/analysis/generation_metrics.csv`
- `/home/mhlab/EAGLE/runs/20260907_154823_943103/analysis/plots/game_performance_by_generation.png`

### Code Reflection evidence

- Gen 3 conclusion：`/home/mhlab/EAGLE/runs/20260907_154823_943103/candidates/gen_0003_55fef5bff473/mutation/code_reflection/reflection_conclusion.json`
- Gen 3 revision request：`/home/mhlab/EAGLE/runs/20260907_154823_943103/candidates/gen_0003_55fef5bff473/mutation/code_reflection/revision_request.txt`
- Gen 3 parent/reflected/final Java：`mutation/code_reflection/parent_candidate.java`、`mutation/code_reflection/reflected_candidate.java`、`phenotype/CandidateAgent.java`
- Gen 4 conclusion：`/home/mhlab/EAGLE/runs/20260907_154823_943103/candidates/gen_0004_4161d4c2eab0/mutation/code_reflection/reflection_conclusion.json`
- Gen 5 conclusion：`/home/mhlab/EAGLE/runs/20260907_154823_943103/candidates/gen_0005_ea6d658df151/mutation/code_reflection/reflection_conclusion.json`

### Prompt Reflection evidence

每個 Prompt candidate 的完整 Reviewer、Rewriter request/raw response 與 metadata 位於：

`/home/mhlab/EAGLE/runs/20260907_154823_943103/candidates/<candidate_id>/mutation/prompt_reflection/`

### Strategy Reflection evidence

每個 Strategy candidate 的 selected matches、10 個 Commentator 結果、Coach input/output、contract rewrite 與最終 policy 位於：

`/home/mhlab/EAGLE/runs/20260907_154823_943103/candidates/<candidate_id>/mutation/strategy_reflection/`

## 12. 報告口徑

- 本文件只納入已完成且由 Generation 0–5 正式 snapshot 對應的 offspring。
- 實驗曾在修正 Ministral structured-output shape 後 resume；中斷期間留下但未進入 atomic generation 的 `gen_0001_65ecdb3c8d04` 與 `gen_0003_0cdef300c6ac` 不列入正式演化統計。
- 所有分數、lineage、mutation status、attempt count 與 survivor 名單均取自 canonical `eagle-run-v2` candidate/generation artifacts；沒有用檔名或 prompt 文字相等推測 provenance。
