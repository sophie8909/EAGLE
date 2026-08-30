#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

EXPERIMENTS=()
while (( $# > 0 )); do
  case "$1" in
    --model|--experiment)
      [[ $# -ge 2 ]] || { echo "ERROR: $1 requires an experiment name." >&2; exit 2; }
      EXPERIMENTS+=("${2//./_}")
      shift 2
      ;;
    --help|-h)
      echo "Usage: ./benchmark_models.sh [--experiment NAME ...]"
      exit 0
      ;;
    *) EXPERIMENTS+=("${1//./_}"); shift ;;
  esac
done

if (( ${#EXPERIMENTS[@]} == 0 )); then
  EXPERIMENTS=(qwen3_5_9b qwen3_8b ministral3_8b gemma3_12b)
fi

OUTPUT_ROOT="$ROOT_DIR/model_benchmarks/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTPUT_ROOT"
for name in "${EXPERIMENTS[@]}"; do
  config_dir="$ROOT_DIR/configs/experiments/$name"
  [[ -f "$config_dir/experiment.yaml" ]] || {
    echo "ERROR: experiment folder is missing: $config_dir" >&2
    exit 2
  }
  mkdir -p "$OUTPUT_ROOT/$name"
  echo "===== [$name] unified experiment ====="
  "$ROOT_DIR/experiment.sh" "$config_dir" 2>&1 | tee "$OUTPUT_ROOT/$name/experiment.log"
done

echo "All model experiments completed: $OUTPUT_ROOT"
