# Opponent Pool slide image

Created: 2026-10-19
Tool: built-in image_gen
Deliverable: opponent_pool.png (raster image; not an editable PowerPoint)

## Verified sources

- `docs/eagle_architecture_spec.md`, section 9; `eagle/opponent_pool.py`; `eagle/self_play.py`.
- `eagle/evolution/search.py`: generation zero offers `evaluated_population` to the pool.
- `eagle/evolution/generation.py`: later generations offer `evaluated_offspring` to the pool.
- Eligible entrants must be runnable, fully evaluated, and unique. Admission does not require winning survivor selection.
- The pool retains admitted strategies across generations, subject to tournament replacement. The ten-opponent evaluation-roster size is independent of population and offspring count.

## Initial generation prompt

Use case: infographic-diagram.
Asset type: ONE finished landscape 16:9 research presentation image, 3840x2160 if possible, entirely in Traditional Chinese except proper names and short technical labels.
Primary request: Explain the CURRENT EAGLE self-play opponent pool, its maintenance, and how evaluation opponents are selected. This is a polished academic slide, with a clear visual hierarchy and accurate directed arrows.
Style: EAGLE research palette: warm ivory #FCF8F5 background, burgundy #47171C title and key numbers, charcoal #423C3B body, dusty blush #DEB4BA and rose #CF8792 diagram accents, pale gold #FAEDC6 to distinguish permanently protected opponents. Flat precise diagram artwork, elegant Traditional Chinese serif headings, very readable Traditional Chinese body text, generous spacing, thin connectors. No photos, mascots, mock slide frame, 3D, gradients, decorative clutter, watermark or dashboard cards.
Composition: title at top. Main upper flow across 3 stages: INITIAL SOURCES on left -> LARGE POOL in center -> EVALUATION SNAPSHOT on right. Lower band explains admission and tournament replacement feeding upward into the pool. Clearly distinguish the big pool from the smaller frozen roster. Fit all text with balanced whitespace and legibility.

Exact title: "Opponent Pool｜對手如何累積與抽樣？"
Small subtitle: "EAGLE Self-play · tournament-v1"

Upper left stage "① 初始化：10 個內建對手"
Visually group four protected names in pale gold:
"永久保留 4 個"
"AllInBot · Mayari · COAC · TMA"
And six initial replaceable baselines in dusty rose:
"可替換基準 6 個"
"PassiveAI · RandomAI · RandomBiasedAI"
"LightRush · HeavyRush · WorkerRush"
Arrow from initialization into central pool.

Upper center stage "② 維護 Opponent Pool"
Use one large bounded container with clearly distinct protected band and variable-member region:
"容量預設 50｜包含保護成員｜至少 10"
"固定 4 個：永久保護"
"其餘成員：基準對手＋已入池策略"
Show some small abstract strategy tiles in variable region, with ellipsis, do not imply exactly 50 already occupied.
Arrow from protected band and sampled variable region into right stage, label on variable arrow "以 seed 可重現地抽樣 6 個".

Upper right stage "③ 凍結評估名單"
Prominent composition "固定 4 ＋ 抽樣 6 ＝ 10 個對手"
"第 0 代：使用全部 10 個內建對手"
"預設於第 1、6、11…代刷新"
"兩次刷新之間，名單保持不變"
Bold equation below:
"10 對手 × 3 地圖 × 3 回合 × 2 邊"
"＝ 每個候選策略 180 場"
Small line "各對手等權重 → Game Performance"
Do not draw any connection suggesting the pool members are breeding parents.

Lower band, heading "新策略如何入池？"
Left-to-right compact branching flow starting with:
"完成評估的新策略" -> "可執行＋去重"
Tiny supporting line under deduplication "ID／原始碼／語意表型"
Then branch into two distinct paths:
Path A "池未滿" -> "直接加入"
Path B "池已滿" -> "抽 1 個非保護成員" -> "18 場挑戰賽" -> "勝場 > 敗場才替換"
Under tournament: "3 地圖 × 3 回合 × 2 邊"
Under outcome: "平手、失敗或未完成：保留原成員"
Connect both successful admission outcomes back to the central pool with clear subtle arrows; do not connect challenges to the frozen snapshot directly. Only nonprotected members are tournament eligible.

Bottom small footer:
"評估名單刷新時，父代先重新評估，確保選擇時使用相同對手情境。"
Tiny source line: "依據：eagle/opponent_pool.py · eagle/self_play.py · docs/eagle_architecture_spec.md §9"
Accuracy constraints: capacity includes protected four; initial pool ten; frozen roster always ten; pool can update without changing frozen roster; no FIFO, top-K, champion-only, fitness-weighted sampling, random resampling every candidate, or automatic replacement on draw. Display ONLY the specified text, spell Chinese accurately, no fabricated numerical performance data.

## Clarification edit prompt

Edit the attached EAGLE opponent-pool slide with ONLY two text clarifications, preserving the entire 16:9 layout, every existing diagram arrow, colors, typography, all other text, and source footer. Do not introduce new artwork or change numbers.
1. Under the lower-band heading "新策略如何入池？", in its available whitespace above the flow nodes, add one highly readable dark charcoal line:
"來源：第 0 代初始族群 ＋ 後續每代完成評估的子代"
This line must clearly belong to the new-strategy source and not the initial built-in opponents. Keep all original flow nodes, especially "完成評估的新策略" -> "可執行＋去重".
2. In the center pool variable-member region, replace "其餘成員：基準對手＋已入池策略" with these two compact lines, keeping the strategy tiles:
"其餘成員：可替換基準＋歷代入池策略"
"跨代累積，滿額後以挑戰賽替換"
Adjust just the text size and tile vertical placement within that existing variable-member region if needed for legibility; no text overlap.
Meaning to preserve exactly: newly evaluated candidates come from generation-zero initial population and evaluated offspring from successive generations; the pool retains admitted historical strategies subject to replacement, whereas ten is the evaluation-opponent roster size. The pool is not limited to current-generation candidates or winners. All Traditional Chinese must render accurately.
