#!/usr/bin/env bash
set -euo pipefail

# Benchmark script for LLM agents vs RandomBiasedAI.
# Uses the currently running llama.cpp OpenAI-compatible server.

GAMES_PER_MODEL=2
RUN_TIME_PER_GAME_SEC="${RUN_TIME_PER_GAME_SEC:-120}"
LLAMA_CPP_BASE_URL="${LLAMA_CPP_BASE_URL:-http://127.0.0.1:8080/v1}"
RESULTS_FILE="benchmark_results_$(date +%Y-%m-%d_%H-%M-%S).txt"

MODELS=("${LLAMA_CPP_MODEL:-local}")

echo "==============================================="
echo "MicroRTS LLM Benchmark"
echo "==============================================="
echo "Models: ${MODELS[*]}"
echo "Games per model: $GAMES_PER_MODEL"
echo "Opponent: RandomBiasedAI"
echo "Map: maps/8x8/basesWorkers8x8.xml"
echo "Results file: $RESULTS_FILE"
echo "==============================================="
echo ""

# Check llama.cpp availability
echo "Checking llama.cpp at $LLAMA_CPP_BASE_URL..."
if ! curl -s --connect-timeout 5 "$LLAMA_CPP_BASE_URL/models" > /dev/null 2>&1; then
    echo "ERROR: llama.cpp is not responding at $LLAMA_CPP_BASE_URL"
    echo ""
    echo "Start it from the repository root with:"
    echo "  LLAMA_CPP_MODEL_PATH=/path/to/model.gguf ./run_llama_cpp.sh"
    exit 1
fi
echo "llama.cpp is running."

# Compile
echo ""
echo "Compiling MicroRTS..."
mkdir -p logs bin
find src -name '*.java' > sources.list
javac -cp "lib/*:bin" -d bin @sources.list
echo "Compilation complete."

# Initialize results file
echo "# MicroRTS LLM Benchmark Results" > "$RESULTS_FILE"
echo "# Date: $(date)" >> "$RESULTS_FILE"
echo "# Map: maps/8x8/basesWorkers8x8.xml" >> "$RESULTS_FILE"
echo "" >> "$RESULTS_FILE"

# Run benchmark
for model in "${MODELS[@]}"; do
    echo ""
    echo "==============================================="
    echo "Testing model: $model"
    echo "==============================================="

    export LLAMA_CPP_MODEL="$model"

    for ((game=1; game<=GAMES_PER_MODEL; game++)); do
        echo ""
        echo "--- Game $game of $GAMES_PER_MODEL for $model ---"
        ts="$(date +%Y-%m-%d_%H-%M-%S)"
        LOGFILE="logs/benchmark_${model//[:.]/_}_game${game}_${ts}.log"

        echo "Starting game at $ts..."

        # Run game with timeout
        timeout_result=0
        java -cp "lib/*:bin" rts.MicroRTS > "$LOGFILE" 2>&1 &
        game_pid=$!

        # Wait for game to complete or timeout
        sleep "$RUN_TIME_PER_GAME_SEC" &
        sleep_pid=$!

        while kill -0 "$game_pid" 2>/dev/null && kill -0 "$sleep_pid" 2>/dev/null; do
            sleep 1
        done

        # Check if game finished naturally
        if kill -0 "$game_pid" 2>/dev/null; then
            echo "Game timed out after ${RUN_TIME_PER_GAME_SEC}s, stopping..."
            kill "$game_pid" 2>/dev/null || true
            sleep 2
            kill -9 "$game_pid" 2>/dev/null || true
            timeout_result=1
        else
            kill "$sleep_pid" 2>/dev/null || true
        fi
        wait "$game_pid" 2>/dev/null || true
        wait "$sleep_pid" 2>/dev/null || true

        # Parse results from log
        winner="unknown"
        ticks="unknown"
        crashed="no"

        if grep -q "Player 0 wins" "$LOGFILE" 2>/dev/null; then
            winner="LLM"
        elif grep -q "Player 1 wins" "$LOGFILE" 2>/dev/null; then
            winner="RandomBiasedAI"
        elif grep -q "Draw" "$LOGFILE" 2>/dev/null; then
            winner="Draw"
        fi

        # Try to find game ticks
        if grep -q "Game Over" "$LOGFILE" 2>/dev/null; then
            ticks=$(grep -oP 'cycle[s]?[:\s]+\K\d+' "$LOGFILE" 2>/dev/null | tail -1 || echo "unknown")
        fi

        if [ "$timeout_result" -eq 1 ]; then
            crashed="timeout"
        elif grep -qi "exception\|error" "$LOGFILE" 2>/dev/null; then
            crashed="error"
        fi

        # Record result
        result="model=$model opponent=RandomBiasedAI map=8x8/basesWorkers8x8 game=$game winner=$winner ticks=$ticks crashed=$crashed"
        echo "$result"
        echo "$result" >> "$RESULTS_FILE"

        echo "Log saved to: $LOGFILE"
    done
done

echo ""
echo "==============================================="
echo "BENCHMARK COMPLETE"
echo "==============================================="
echo ""
echo "Results saved to: $RESULTS_FILE"
echo ""
cat "$RESULTS_FILE"
