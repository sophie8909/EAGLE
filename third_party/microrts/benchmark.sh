#!/usr/bin/env bash
set -euo pipefail

# Benchmark script for LLM agents vs RandomBiasedAI
# Tests: llama3.1:8b and qwen3:14b (2 games each)

GAMES_PER_MODEL=2
RUN_TIME_PER_GAME_SEC="${RUN_TIME_PER_GAME_SEC:-120}"
OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
RESULTS_FILE="benchmark_results_$(date +%Y-%m-%d_%H-%M-%S).txt"

MODELS=("llama3.1:8b" "qwen3:14b")

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

# Check Ollama availability
echo "Checking Ollama at $OLLAMA_HOST..."
if ! curl -s --connect-timeout 5 "$OLLAMA_HOST/api/tags" > /dev/null 2>&1; then
    echo "ERROR: Ollama is not responding at $OLLAMA_HOST"
    echo ""
    echo "Please start Ollama with:"
    echo "  ollama serve"
    echo ""
    echo "And ensure models are available:"
    echo "  ollama pull llama3.1:8b"
    echo "  ollama pull qwen3:14b"
    exit 1
fi
echo "Ollama is running."

# Check models
echo "Checking required models..."
for model in "${MODELS[@]}"; do
    if ! curl -s "$OLLAMA_HOST/api/tags" | grep -q "\"$model\""; then
        echo "WARNING: Model $model may not be available. Attempting to pull..."
        ollama pull "$model" || echo "Could not pull $model"
    fi
done

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

    export OLLAMA_MODEL="$model"

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
