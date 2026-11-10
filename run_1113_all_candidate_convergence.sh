#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

GENERATIONS=(0 5 10 15 20 25 30 35 40 45 50)
EVALUATION_DIR="fixed_evaluation_all_1113"

run_fixed_evaluation() {
  local run_dir="$1"
  echo "=== Evaluating ${run_dir} ==="
  python -m eagle.fixed_evaluation \
    --run-dir "$run_dir" \
    --generations "${GENERATIONS[@]}" \
    --all-candidates \
    --output-dir "${run_dir}/${EVALUATION_DIR}"
}

run_fixed_evaluation runs/20261108_144319_755348
run_fixed_evaluation runs/20261109_000650_966551
run_fixed_evaluation runs/20261109_072720_479146
run_fixed_evaluation runs/20261109_150205_472817

python scripts/plot_all_candidate_fixed_convergence.py \
  --evaluation-dir-name "$EVALUATION_DIR" \
  --output-dir 1113/all_candidate_fixed_convergence \
  --report-path 1113/report.md

echo "完成：1113/report.md"
