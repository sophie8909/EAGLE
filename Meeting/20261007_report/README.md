# EAGLE 2026-10-07 研究簡報

- 簡報：`deliverables/20261007.pptx`，14 頁，繁體中文。
- 內容來源：`reports/20261007_experiment_and_changes_report.md`。
- 版型來源：`J:/我的雲端硬碟/Lab/Meeting/20261001_0930_self_play.pptx`。
- 沿用原始 1672 × 941 px 尺寸、Source Han Serif TW、EAGLE master artwork 與玫瑰色表格。
- 表格與文字保持可編輯；13 張內容頁使用 native PowerPoint tables。

## 內容範圍

10/1–10/7 的實驗紀錄、4×10 deterministic mock 結果、seed propagation、runtime contract、程式變更、後續初始化修正、可重現性適用範圍與下一步。

4×10 結果屬 EA/mock pipeline 驗證。實際 LLM 生成層尚待在 5080 host 補測。報告所列 518 tests passed、1 skipped 為原報告驗證結果，本次簡報製作沒有重新執行 EAGLE 測試或實驗。

## 本次簡報驗證

- PPTX package integrity、slide geometry、reference font policy、14 頁與 native tables 檢查通過。
- Artifact Tool export 後重新 import 成功，逐頁 render 並檢視全部 14 頁。
- 未在原生 PowerPoint 中開啟檢查。私有 validation receipt 與 rendered previews 位於 `.codex-build/`。

## 重建

以 bundled Node.js 執行 `build.mjs`，需要既有 Codex presentation runtime 及上述 reference deck。可用 `EAGLE_REFERENCE` 指定 reference，`EAGLE_OUTPUT` 指定新的輸出檔名；finalizer 不覆寫既有輸出。

Rebuild 之前，依 presentations skill 的 workflow 單獨執行 operation marker。
