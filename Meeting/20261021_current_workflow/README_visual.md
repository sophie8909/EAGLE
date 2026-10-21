# EAGLE 圖解流程簡報

成果：`deliverables/EAGLE_20261021_opponent_pool_with_stability.pptx`，共 45 頁。保留既有 38 頁 Opponent Pool 圖解與第 5 頁 slot 例子，追加 7 頁 `reports/1021_framework_stability_comparison.md` 的結果圖表：兩批設定與狀態、G20 分數、軌跡、正式測試、強敵剖面、多樣性與結論。圖表與表格均為可編輯的原生物件。

搜尋流程統一採 opponent pool 協定（`self_play` 與 `tournament-v1`）：Game Performance 與語意同層選擇、static 突變、父代快取重用及快照刷新重評。正式 Final Test 是獨立的固定基準。新增的實驗結果為 framework **local**，搜尋期間沒有 candidate-time LLM；與第 38 頁的 Coach 設定範例分開。

依使用者刪頁後的 38 頁順序重製，以 `Meeting/20261019_opponent_pool/opponent_pool.png` 的圖解方向作為參考。文字、節點、對手格與箭頭均為可編輯的 PowerPoint 原生物件。講者備註與完整說明同步描述 opponent pool；Java 產生及反思路徑依各模式啟用。

來源為 `deliverables/EAGLE_20261021_complete_workflow.pptx`，SHA-256：`0ceb9dd90620d68e255ebb9a5922616f4617384331ec4bd666734ac0b1db80e5`。原檔不覆寫，已刪除的頁面不復原。第 2 頁保留人工由 ChatGPT 生成固定 Java framework 的調整。

## 來源檔

- `visual_source.json`：38 頁的標題、文字、表格與備註快照。
- `opponent_pool_content.json`：目前 opponent-pool 協定的標題與講者備註更新。
- `stability_report_data.json`：指定報告的數值快照與算術校核；seed 13 保留報告的 G4 狀態，不代表即時進度。
- `stability_slides.mjs`：新增 7 頁結果、原生圖表與表格；完整 G20 mean／sd 等資料留在講者備註。
- `visual_redesign.mjs`：原生 PPT 建立、封裝檢查、匯入與逐頁渲染。
- `visual_pages_a.mjs`、`visual_pages_b.mjs`：各頁圖解配置。
- `visual_workflow_explained.md`：與備註對應的完整文字說明。

使用本機 Codex bundled Node 與 Artifact Tool 執行 `visual_redesign.mjs`。重建前先將既有成果與 `.codex-build/opponent-pool-with-stability/visual-workflow.validation.json` 移至私人建置備份；finalizer 會拒絕覆寫成果。原稿或報告 SHA 若已變更，需先重新擷取內容，不能沿用舊快照。

本機建置、渲染與檢查檔保留在忽略版本控制的 `.codex-build/opponent-pool-with-stability/`。報告未提供耗時，具名 run artifacts 在此工作區無法取得，因此標明耗時比較缺測。未使用原生 Microsoft PowerPoint 驗證字型排版。
