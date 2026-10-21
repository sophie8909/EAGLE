# EAGLE 完整流程簡報

- 來源截點：2026-10-21，程式版本 `fcc8b7705571023499dde2f0c756294f78c861a7`。
- `deliverables/EAGLE_20261021_complete_workflow.pptx`：44 頁，原生可編輯文字、表格、流程節點與連接線，每頁備註附詳細解說與來源。
- `workflow_explained.md`：逐頁文字稿與來源，和簡報共用內容檔。
- `content.mjs`：內容資料；`build.mjs`：使用 Artifact Tool 與 EAGLE POTX 建置。

## 重建

使用 Codex bundled Node 執行 `build.mjs`。預設依賴目前安裝的 Presentations 26.1020.11127 runtime 與個人 EAGLE 模板；可用 `EAGLE_PRESENTATIONS_SKILL`、`EAGLE_ARTIFACT_RUNTIME`、`EAGLE_TEMPLATE`、`EAGLE_FONT_REFERENCE` 覆寫本機位置。`EAGLE_DECK_NAME` 可指定新的輸出名稱，finalizer 不覆寫既有交付。原生頁碼欄位沿用 `Meeting/20261013_current_workflow/native_numbers.py`。

建置會檢查來源檔、頁數與備註，匯出後執行 package、版面、字型、原生表格與第一方重新匯入檢查，將所有頁面渲染至 `.codex-build/render/`。該資料夾的檢查記錄與暫存檔不交付。

## 證據邊界

本次為現行方法流程說明，未啟動實驗或重跑 repository test suite。沒有將歷史測試紀錄當作本次驗證，也沒有引用缺少原始 run 的歷史分數作現行效果證據。串流排程沒有已量測的多主機加速比。

初始化細節以 `eagle/operators/initialization.py` 與 `eagle/config.py` 為準：`llm_generated_policies` 在 inherited 模式因單一 seed 限制保留一個設定策略，在 deterministic DSL 模式可保留多個設定 seed 並補足剩餘名額；較舊概覽只描述前一種情況。

圖表、文字與模板以 Artifact Tool 渲染檢視；未在原生 Microsoft PowerPoint 開啟驗證。使用模板指定的 Source Han Serif TW，目的端未安裝該字型時可能替換字型。
