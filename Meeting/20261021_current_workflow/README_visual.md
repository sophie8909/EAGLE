# EAGLE 圖解流程簡報

## 人工修改主版本（2026-10-22）

目前以 `J:\我的雲端硬碟\Lab\Meeting\EAGLE_20261022_opponent_pool_data_only.pptx` 為主。使用者已刪頁，讀取時共 43 頁；本次重寫第 4 頁為 local 演化圖解，新增第 5 頁為完整 Coach 流程，共 44 頁。保留其他頁面的人工內容、背景與原生圖表，只更新頁碼。新增頁明示目前這批 local 實驗未啟用 Coach。

最新快照為 `deliverables/EAGLE_20261022_opponent_pool_clarified.pptx`，仍為 44 頁。第 6 頁集中解釋對手池：內建與歷代策略來源、容量 50、入池及滿池 18 場替換，以及凍結的 4＋6 十人對戰名單。第 5 頁 Coach 圖改用「對手池」，第 7 頁明確區分當代族群的繁殖父代選擇；第 2 頁將「歷屆冠軍」更正為固定保護對手。`edit_manual_opponent_pool.mjs` 保留新圖解的可編輯來源，私有備份及驗證位於 `.codex-build/manual-opponent-pool/`。本次雲端來源 SHA-256：`aa66e857c94329040e780fa74fb2216b79c8777f8fb3327655c096efe4fc626b`。

版本控制快照：`deliverables/EAGLE_20261022_opponent_pool_local_coach.pptx`。`edit_manual_local_coach.mjs` 以 Artifact Tool 建立兩頁原生物件，`merge_manual_local_coach.py` 將局部變更合併回雲端來源封裝，並檢查其他頁面內容與全部圖表／工作簿保持原樣。修改前雲端 SHA-256：`b12a4982e14de2147af8495d3baf3e133c3ae0bcaa87ed71bcfb7d8519e53b9e`。原檔備份、兩頁 authoring 驗證、完整封裝與版面檢查、PowerPoint 44 頁原生預覽留在 `.codex-build/manual-local-coach/`。

人工修改階段請從雲端主檔繼續編輯，不要以舊的 `visual_redesign.mjs` 重建整份簡報覆蓋主檔。

## 原始 45 頁建置紀錄

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
