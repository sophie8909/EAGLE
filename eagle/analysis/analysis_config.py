"""Configuration for surrogate-validation analysis plots."""

from __future__ import annotations

from pathlib import Path


ANALYSIS_ROOT = Path(__file__).resolve().parent
RESULT_ROOT = ANALYSIS_ROOT / "result"

# Optional default input. Keep None when you prefer passing CSV path via CLI.
DEFAULT_ALIGNMENT_CSV: str | None = None

# Plot appearance.
FIGURE_DPI = 180
BAR_FIGSIZE = (10, 5)
HEATMAP_MIN_WIDTH = 8
HEATMAP_MIN_HEIGHT = 5
HEATMAP_WIDTH_PER_OPPONENT = 1.2
HEATMAP_HEIGHT_PER_INDIVIDUAL = 0.45

# Colors.
MEAN_GAP_BAR_COLOR = "#3A6EA5"
SAME_RESULT_BAR_COLOR = "#6BA368"
HEATMAP_CMAP = "viridis"

# Output artifact names.
MEAN_GAP_FILENAME = "mean_gap_by_opponent.png"
SAME_RESULT_FILENAME = "same_result_rate_by_opponent.png"
HEATMAP_FILENAME = "alignment_heatmap.png"
CONFIG_SNAPSHOT_FILENAME = "analysis_config_snapshot.json"
