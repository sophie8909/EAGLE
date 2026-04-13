#!/usr/bin/env bash
set -euo pipefail

TOTAL_RUNS="${TOTAL_RUNS:-1}"                    # Set to 1000 for one thousand runs
RUN_TIME_PER_GAME_SEC="${RUN_TIME_PER_GAME_SEC:-5000}"  # Max seconds per run

mkdir -p logs bin

echo "[INFO] compiling sources..."
find src -name '*.java' > sources.list
javac -cp "lib/*:bin" -d bin @sources.list

for ((i=1; i<=TOTAL_RUNS; i++)); do
  echo "========== RUN $i / $TOTAL_RUNS =========="
  ts="$(date +%Y-%m-%d_%H-%M-%S)"
  LOGFILE="logs/run_${ts}.log"

  echo "[INFO] starting game (max ${RUN_TIME_PER_GAME_SEC}s, exits early if game finishes)..."

  set +e
  timeout --signal=TERM --kill-after=2s "${RUN_TIME_PER_GAME_SEC}s" \
    java -cp "lib/*:bin" rts.MicroRTS >"$LOGFILE" 2>&1
  exit_code=$?
  set -e

  case "$exit_code" in
    0)
      echo "[INFO] run $i finished normally before timeout."
      ;;
    124)
      echo "[INFO] run $i reached timeout (${RUN_TIME_PER_GAME_SEC}s) and was terminated."
      ;;
    *)
      echo "[WARN] run $i exited with code $exit_code."
      ;;
  esac

  echo "[INFO] log saved to $LOGFILE"
  echo
done

echo "ALL $TOTAL_RUNS RUNS DONE 🎉"