# EAGLE 圖解流程簡報

成果：`deliverables/EAGLE_20261022_opponent_pool_data_only.pptx`，共 45 頁。前 38 頁 Opponent Pool 流程維持原樣；第 39–45 頁改為純數據，包含批次完成場數、G20 分數、G0–G20 紀錄、正式測試勝和敗、全部十個對手的場數、行為簽章數及各 seed 的實測耗時與勝和敗。已移除結果解讀、結論及建議，包含講者備註。文字、圖表及表格均為可編輯的原生物件。

恢復原 EAGLE 鷹形、羽翼與四角線條背景，保留目前配色、圖解配置及你在第 1 頁移動的「反思與選擇」文字框。原圖存為原生背景填滿，母片、版型與各頁皆能呈現；右下角只保留一組原生自動頁碼。舊的無背景版本仍保留，不覆寫開啟中的檔案。

搜尋流程統一採 opponent pool 協定（`self_play` 與 `tournament-v1`）：Game Performance 與語意同層選擇、static 突變、父代快取重用及快照刷新重評。正式 Final Test 是獨立的固定基準。新增的實驗結果為 framework **local**，搜尋期間沒有 candidate-time LLM；與第 38 頁的 Coach 設定範例分開。

依使用者刪頁後的 38 頁順序重製，以 `Meeting/20261019_opponent_pool/opponent_pool.png` 的圖解方向作為參考。文字、節點、對手格與箭頭均為可編輯的 PowerPoint 原生物件。講者備註與完整說明同步描述 opponent pool；Java 產生及反思路徑依各模式啟用。

來源為 `deliverables/EAGLE_20261021_complete_workflow.pptx`，SHA-256：`0ceb9dd90620d68e255ebb9a5922616f4617384331ec4bd666734ac0b1db80e5`。原檔不覆寫，已刪除的頁面不復原。第 2 頁保留人工由 ChatGPT 生成固定 Java framework 的調整。

## 來源檔

- `visual_source.json`：38 頁的標題、文字、表格與備註快照。
- `opponent_pool_content.json`：目前 opponent-pool 協定的標題與講者備註更新。
- `stability_report_data.json`：原報告加上 2026-10-22 經使用者授權、從 `/home/mhlab/EAGLE` 既有 artifacts 讀取的數據。保存來源聊天及訊息 ID、原始路徑與欄位定義。兩批各 6 runs，seed 13 已完成；共 12 runs、7200 場 Final Test。
- `stability_slides.mjs`：7 頁純數據結果，9 個原生圖表及 6 個原生表格；完整 G20 mean／sd、時間及逐 seed W/D/L/E 留在講者備註。
- `visual_redesign.mjs`：原生 PPT 建立、封裝檢查、匯入與逐頁渲染。
- `visual_pages_a.mjs`、`visual_pages_b.mjs`：各頁圖解配置。
- `visual_workflow_explained.md`：與備註對應的完整文字說明。

使用本機 Codex bundled Node 與 Artifact Tool 執行 `visual_redesign.mjs`，原生起始模板為 `../template/EAGLE.potx`。重建前先將既有成果與 `.codex-build/opponent-pool-data-only/visual-workflow.validation.json` 移至私人建置備份；finalizer 會拒絕覆寫成果。原稿或報告 SHA 若已變更，需先重新擷取內容，不能沿用舊快照。

時間單位為秒，投影片顯示 hh:mm:ss（四捨五入至整秒）。「搜尋 wall」為 `timing.jsonl` 的 G0 開始到 G20 完成，不包含 framework bootstrap 或 Final Test；G0 為該代 `duration_seconds`；G1–20 為完成世代的 duration 加總。「測試對戰」為 600 場 match 的最早開始至最晚完成，排除編譯與 Integration。12 個 run 均有完整 G0–G20，未觀察到 resume。

本機建置、渲染與檢查檔保留在忽略版本控制的 `.codex-build/opponent-pool-data-only/`。已檢查數值加總、逐頁渲染、原生圖表／工作簿、版面與背景；前 38 頁與既有版本比對。PowerPoint 可正常開啟 45 頁，並已檢查結果頁的原生輸出預覽。未重跑實驗；未在其他電腦或 Google Slides 驗證排版。
