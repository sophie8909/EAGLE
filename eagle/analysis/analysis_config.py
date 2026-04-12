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

# Consistency analysis defaults.
DEFAULT_PROMPT_RESULTS_CSV: str | None = None
DEFAULT_JAVA_RESULTS_CSV: str | None = None
DEFAULT_BEHAVIOR_PROMPT_CSV: str | None = None
DEFAULT_BEHAVIOR_JAVA_CSV: str | None = None

TOP_K_VALUES = (5, 10, 20)
FIGURES_DIRNAME = "figures"
SUMMARY_METRICS_FILENAME = "summary_metrics.csv"
BEHAVIOR_SIMILARITY_FILENAME = "behavior_similarity.csv"
REPORT_FILENAME = "analysis_report.md"
MERGED_RESULTS_FILENAME = "merged_results.csv"
MERGED_BEHAVIOR_FILENAME = "merged_behavior.csv"

SCATTER_FILENAME = "scatter_consistency.png"
BLAND_ALTMAN_FILENAME = "bland_altman.png"
ERROR_HISTOGRAM_FILENAME = "error_histogram.png"
TOPK_OVERLAP_FILENAME = "topk_overlap.png"
BEHAVIOR_COMPARISON_FILENAME = "behavior_comparison.png"

# Rule-based interpretation thresholds.
SPEARMAN_HIGH_THRESHOLD = 0.7
SPEARMAN_MEDIUM_THRESHOLD = 0.4
TOPK_HIGH_THRESHOLD = 0.7
HIGH_BIAS_THRESHOLD = 0.1
HIGH_BEHAVIOR_GAP_THRESHOLD = 0.15
