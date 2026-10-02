# EAGLE 可維護性重構計畫

日期：2026-10-02。本計畫先於程式修改建立。

## 目標

以作者能快速找到、看懂、修改程式為優先，移除重複工作。重新組織 Python 架構，保留 EA 行為、設定、prompt／Java assets、lineage、run artifacts 與 checkpoint 格式。不新增依賴、plugin registry、通用 operator framework 或額外 fallback。效率改善以可驗證的重複計算減少為準，不宣稱未量測的 LLM／比賽加速。

## 掃描結果

已掃描 Python 檔案、模組大小、核心流程、imports、canonical contracts、CLI、scripts 與測試 patch targets。

| 現況 | 問題 | 處理 |
| --- | --- | --- |
| `eagle/search.py` 1,142 行 | lifecycle、單代流程、offspring、parent refresh 混合 | 依階段拆開，fresh/resume 共用 generation owner |
| `eagle/evaluation.py` 1,934 行 | decoder retry、pipeline、opponent setup、match execution 混合 | 分開 pipeline、decoding、opponents、matches、records |
| EA operators 散在 `eagle/` | 修改單一 operator 不易定位 | 集中到 operators，各自獨立實作 |
| 三個頂層 Python packages | 同一應用分散 | generation/evaluation 統一到 eagle 下，既有 helper 直接重用 |
| offspring loop 重複找 generation-best | 同一代反覆掃 population | 在 loop 前計算一次 |
| compatibility forwarding | owner 不明確 | callers 直接 import owner，移除舊 shim |

Meeting 簡報與生成資料為既有無關修改，保留並排除於提交。

## 新架構

```text
eagle/
  candidate.py, config.py       # 核心資料與設定
  experiment.py, final_test.py  # 實驗／最終測試 lifecycle
  operators/
    initialization.py          # Generation zero
    selection.py               # Parent + survivor selection
    crossover.py               # Component crossover
    adaptive.py                # Static/AOS operator selection + credit
    strategy.py                # Strategy: Commentator + Coach
    prompt.py                  # Prompt: Reviewer + reusable-rule rewrite
    code.py                    # Code: diagnosis + deferred Java revision
    reflection.py              # 共用 records/transport/parsing
    context.py                 # Evidence projection
    reflection_prompts.py, reusable_prompt.py, strategy_compliance.py
  evolution/
    search.py                  # Fresh run lifecycle / generation loop
    resume.py                  # Checkpoint / resumed generation loop
    generation.py              # Phase ordering / survivor persistence
    offspring.py               # Assignment -> reflection -> materialization
    parent_refresh.py          # Fitness refresh / diagnostic parent replicas
    runtime.py                 # Shared fresh/resume dependencies
  generation/                  # 既有 backend / scaffold / extraction / validation
  evaluation/
    pipeline.py                # Population + candidate evaluation
    decoding.py                # Bounded decode / validate / compile / repair
    opponents.py               # Fixed/self-play preparation and preflight
    matches.py                 # Matrix dispatch / match workers
    records.py                 # 跨階段 typed results
    ...                        # 既有 scoring/compiler/integration/trace helpers
  runtime/, analysis/, cli/    # 延用既有責任邊界
  artifacts.py, run_artifacts.py, timing.py, prompts.py
```

依賴方向：experiment -> evolution -> operators / generation / evaluation。Operator 只修改自己的 gene 或 Java output；evaluation 不選 parent/survivor。共用 result records 不依賴 pipeline，避免循環匯入。Package init 保持簡單，不用隱藏 re-export 或動態載入。

修改 selection/crossover/三種 mutation 分別到對應 operator；只有 phase ordering 變更才需要改 evolution。既有低階 scoring/match helpers 不重寫。

## 保留契約與錯誤處理

- seeded EA 隨機呼叫順序、ten-case lexicase、self-play scalar/semantic selection、mu-plus-lambda。
- 所有 assignment -> 所有 reflection/rewrite -> materialization -> evaluation；Code revision 不被 Generator 覆蓋。
- two-prompt / inherited Java 的 genotype/phenotype、provenance 與 operator evidence 邊界。
- fresh/resume 共用單代流程；self-play library/context refresh。
- 每個 decoder sample 最多編譯一次；第一個成功 classes 直接提升。
- match workers、結果順序、matrix、tick caps、failure artifacts、原子 checkpoint。
- 保留外部 LLM、generated Java、subprocess、path/write 與 process ownership 的必要檢查。內部 programmer error 直接拋出，不新增 catch-all 或重複檢查。

## 實作順序

1. 先輸出本計畫，執行既有測試基線。
2. 移動模組；一次更新 imports、scripts、tests/mock targets、package discovery；修正移動後 __file__ roots，assets 維持原路徑。
3. 拆出 evolution owners 與 evaluation stages；移除 compatibility forwarding；generation-best 移到 loop 外。
4. 更新 repository map、canonical references、current status、migration/traceability 與中文文件 map；記錄 operator 修改入口。
5. targeted + full validation、final diff review、只 stage 本次檔案、Conventional Commit。

普通函式、既有 dataclass、明確 imports；不以行數硬切、不增加只有一個 implementation 的 interface。

## 驗證與完成條件

- WSL `.venv/bin/python -m compileall eagle`。
- operator、phase ordering、generation attempts、self-play、resume、runtime、artifacts tests；最後完整 unittest discover。
- bounded shell/direct Python mock CLI、resume、offline analysis；temporary settings/runs，不執行完整實驗。
- 既有 bounded real Java/MicroRTS integration tests；報告 skipped/environment limits。
- stale imports/resource paths、package import/build check、git diff --check。
- 測試更新 owner imports/patch targets，必要時修正環境 portability；不改演算法預期、不用 shim 讓過時 target 假通過。

## 執行記錄

已完成並依本計畫實作：

- EA initialization、selection、crossover、adaptive、strategy、prompt、code 各有獨立 operator；共用 evidence／transport 保留明確 owner，未新增 registry、interface 或依賴。
- search 拆成 lifecycle、shared generation、offspring、parent refresh；evaluation 拆成 pipeline、decoding、opponents、matches、records。generation/evaluation 統一於 eagle package，移除舊入口與 forwarding。
- generation-best 每代只掃一次 population；fresh/resume 使用同一個 generation step。必要外部邊界檢查保留，移除重複內部長度檢查與相容別名。
- 更新 imports、test patch targets、scripts、CI、package discovery、canonical ownership 文件與 operator 修改入口。內部 semantic probe 隨 evaluation owner 移動；設定、使用者 assets 與 artifacts 路徑契約保持。

驗證結果：

| 驗證 | 結果 |
| --- | --- |
| 重構前基線 | 493 tests，3 failures、1 error、1 skipped；涉及 CRLF 與缺少 upstream AlliBot JAR |
| 最終完整 WSL unittest discover | 493 tests，OK，1 skipped，405.908 秒 |
| compileall／package imports | 通過，70 個 EAGLE modules 可匯入，evaluation records type hints 可解析 |
| evaluation 結構比對 | 32 個搬移 classes/functions 的 AST 在 owner imports、路徑深度及共用 UTC helper 正規化後一致 |
| Python CLI | bounded mock experiment、resume、offline analysis 通過 |
| shell CLI | conda eagle 環境下 experiment.sh mock 啟動及 generation checkpoint 通過 |
| Python wheel | 建置通過，包含新 modules、Java scaffold、seed、adapter 與 semantic probe |
| 差異檢查 | git diff --check 通過；只提交本次重構範圍 |

測試 portability 修正：seed hash 改以正規化換行後的相同 Java source 驗證，保留既有 expected hash；shell 以 .gitattributes 固定 LF；AlliBot metadata fixture 驗證正確 pinning 及 tampered JAR 拒絕，並實際 javac 編譯 reflection adapter。未放寬 production preflight 或改變演算法預期。

唯一 skipped 是缺少歷史 candidate／upstream 資產的 AlliBot runtime regression；其真實歷史情境尚未驗證。完整測試包含既有 Java／MicroRTS integration；本次未執行完整真實 evolutionary experiment 或 live LLM benchmark，不宣稱整體實驗加速比例。
