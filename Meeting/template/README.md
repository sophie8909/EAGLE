# EAGLE 研究簡報模板

- `skills/research-report`：依日期區間整理 MD，逐筆變更及受影響實驗，納入必要的區間外基準。
- `skills/reference-matched-presentations`：把 MD 製成可編輯 PPT，檢查完整演算法、結果圖表、實測時間及比較分析。
- `skills/artifact-template-eagle-0917`：視覺契約與頁型；`paper-reading` 的簡報路由同步更新。

上列文字與 `C:/Users/cinna/.codex/skills/` 的安裝版本同步。`EAGLE.potx` 保留原有 12 種版型，修正 6 種研究頁型，並提供 8 張目前風格的可編輯示例：完整流程、slot 選項、Opponent Pool、評估矩陣、分數、正式測試、多樣性與時間證據。`reference.pptx` 是相同頁面的可編輯參考；`preview.png` 用於模板庫。

背景沿用原始 EAGLE artwork，以母片／版型／投影片的原生背景填滿保存，避免匯出後遺失。保留象牙白、酒紅、玫瑰粉、藕粉與淡金配色，以及 Source Han Serif TW；標題、節點、連線、表格和圖表仍為原生物件。母片右下角保留單一原生動態頁碼欄位，新增頁也會直接顯示頁碼。六種修正版型採目前左上標題與圖解內容區，標題／副標明確停用繼承的項目符號。

示例保留 2026-10-21 來源簡報的內容與數值，來源及用途記於備註。它們是版面範例，不是所有 EAGLE 實驗都適用的事實；新簡報必須依新來源替換。個人 skill 中的歷史 `reference-0917.pptx` 與 `EAGLE-0917.potx` 不變。

重建：用 Codex bundled Node 執行 `build_research_template.mjs`。輸入為 `../20261021_current_workflow/deliverables/EAGLE_20261021_opponent_pool_template_restored.pptx`；輸出及驗證紀錄位於 `.codex-build/infographic-template/`。重建前將既有 `checked/reference.pptx` 與 `template.validation.json` 移至私人備份，finalizer 不覆寫成果。確認後將建置的 `EAGLE.potx` 複製至本目錄；腳本會更新本目錄的 reference 與 preview。`prepare_template.py` 修復匯入時遺失的原始 Excel 工作簿、轉換 POTX，並檢查背景、頁碼、版型及原生圖表；不虛構圖表公式。可用 `prepare_template.py verify EAGLE.potx` 重查。

已通過 skill 格式、PPTX 套件／版面／原生圖表與表格驗證、八頁渲染及新投影片繼承檢查。PPTX 與 POTX 均已用 Microsoft PowerPoint 16 正常開啟；另檢查代表頁與新增頁的原生渲染。未測試 Google Slides 或 LibreOffice。
