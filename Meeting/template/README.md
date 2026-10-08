# EAGLE 研究簡報模板

- `skills/research-report`：依日期區間整理 MD，逐筆變更及受影響實驗，納入必要的區間外基準。
- `skills/reference-matched-presentations`：把 MD 製成可編輯 PPT，檢查完整演算法、結果圖表、實測時間及比較分析。
- `skills/artifact-template-eagle-0917`：視覺契約與頁型；`paper-reading` 的簡報路由同步更新。

上列文字為已安裝於 `C:/Users/cinna/.codex/skills/` 的版本快照。`EAGLE.potx` 保留原有 12 種版型，新增 6 種研究頁型及 6 張可編輯示例。示例圖表數值必須替換，不能當成實驗結果。

重建：用 Codex bundled Node 執行 `build_research_template.mjs`；依賴已安裝 Presentations runtime，以及 personal template assets 中保留的 `EAGLE-0917.potx` 和 `reference-0917.pptx`。輸出與驗證紀錄位於 `.codex-build/`，檢查後再更新正式 POTX。`prepare_template.py` 保留 native 自動頁碼、清除標題繼承項目符號、轉換 POTX 內容類型，包含可直接執行的套件檢查。

已通過 skill 格式、PPTX 套件／版面／native 圖表與表格驗證，以及六頁渲染檢查。未以桌面 PowerPoint 開啟驗證。
