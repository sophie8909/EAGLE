# EAGLE 圖解流程簡報

成果：`deliverables/EAGLE_20261021_opponent_pool_workflow.pptx`。搜尋流程統一採目前的 opponent pool 協定（`self_play` 與 `tournament-v1`）：Game Performance 與語意同層選擇、static 突變、父代快取重用及快照刷新重評。十個內建對手改以對手池起始成員解釋，正式 Final Test 仍是獨立的固定基準。第 5 頁保留具體 slot 選值例子。

依使用者刪頁後的 38 頁順序重製，以 `Meeting/20261019_opponent_pool/opponent_pool.png` 的圖解方向作為參考。文字、節點、對手格與箭頭均為可編輯的 PowerPoint 原生物件。講者備註與完整說明同步描述 opponent pool；Java 產生及反思路徑依各模式啟用。

來源為 `deliverables/EAGLE_20261021_complete_workflow.pptx`，SHA-256：`0ceb9dd90620d68e255ebb9a5922616f4617384331ec4bd666734ac0b1db80e5`。原檔不覆寫，已刪除的頁面不復原。第 2 頁保留人工由 ChatGPT 生成固定 Java framework 的調整。

## 來源檔

- `visual_source.json`：38 頁的標題、文字、表格與備註快照。
- `opponent_pool_content.json`：目前 opponent-pool 協定的標題與講者備註更新。
- `visual_redesign.mjs`：原生 PPT 建立、封裝檢查、匯入與逐頁渲染。
- `visual_pages_a.mjs`、`visual_pages_b.mjs`：各頁圖解配置。
- `visual_workflow_explained.md`：與備註對應的完整文字說明。

使用本機 Codex bundled Node 與 Artifact Tool 執行 `visual_redesign.mjs`。重建前先將既有圖解版成果與 `.codex-build/visual-redesign/visual-workflow.validation.json` 移至私人建置備份；finalizer 會拒絕覆寫成果。來源 SHA 若已變更，需先重新擷取使用者的最新頁面，不能沿用舊快照。

本機建置、渲染與檢查檔保留在忽略版本控制的 `.codex-build/visual-redesign/`。未使用原生 Microsoft PowerPoint 驗證字型排版。
