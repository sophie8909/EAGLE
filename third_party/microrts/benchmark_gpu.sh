#!/bin/bash
#SBATCH --job-name=llm-benchmark
#SBATCH --gres=gpu:1
#SBATCH --time=02:00:00
#SBATCH --output=benchmark_slurm_%j.log
#SBATCH --error=benchmark_slurm_%j.err

# MicroRTS LLM Benchmark with GPU Support
# Runs llama3.1:8b and qwen3:14b (2 games each) vs RandomBiasedAI

set -euo pipefail

cd /home/liuc/gitwork/MicroRTS

echo "==============================================="
echo "MicroRTS LLM Benchmark (GPU)"
echo "==============================================="
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $(hostname)"
echo "Date: $(date)"
echo "==============================================="

# Verify GPU access
echo ""
echo "Checking GPU access..."
if nvidia-smi > /dev/null 2>&1; then
    nvidia-smi --query-gpu=name,memory.total --format=csv
    echo "GPU access confirmed."
else
    echo "ERROR: No GPU access. Job may not have been allocated GPUs."
    exit 1
fi

# Configuration
GAMES_PER_MODEL=2
RUN_TIME_PER_GAME_SEC="${RUN_TIME_PER_GAME_SEC:-300}"
OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
RESULTS_FILE="benchmark_results_$(date +%Y-%m-%d_%H-%M-%S).txt"
MODELS=("llama3.1:8b" "qwen3:14b")

echo ""
echo "Configuration:"
echo "  Models: ${MODELS[*]}"
echo "  Games per model: $GAMES_PER_MODEL"
echo "  Timeout per game: ${RUN_TIME_PER_GAME_SEC}s"
echo "  Results file: $RESULTS_FILE"
echo "==============================================="

# Start Ollama server
echo ""
echo "Starting Ollama server..."
pkill -f "ollama serve" 2>/dev/null || true
sleep 2

nohup ollama serve > /tmp/ollama_benchmark.log 2>&1 &
OLLAMA_PID=$!
echo "Ollama PID: $OLLAMA_PID"

# Wait for Ollama to be ready
echo "Waiting for Ollama to start..."
for i in {1..30}; do
    if curl -s --connect-timeout 2 "$OLLAMA_HOST/api/tags" > /dev/null 2>&1; then
        echo "Ollama is ready."
        break
    fi
    sleep 1
done

# Verify Ollama sees GPU
echo ""
echo "Verifying Ollama GPU detection..."
sleep 5
if grep -q "GPU" /tmp/ollama_benchmark.log 2>/dev/null; then
    echo "Ollama detected GPU."
else
    echo "WARNING: Ollama may not be using GPU. Check /tmp/ollama_benchmark.log"
fi

# Check models are available
echo ""
echo "Checking models..."
for model in "${MODELS[@]}"; do
    if curl -s "$OLLAMA_HOST/api/tags" | grep -q "\"name\":\"$model\""; then
        echo "  $model: available"
    else
        echo "  $model: pulling..."
        ollama pull "$model"
    fi
done

# Compile MicroRTS
echo ""
echo "Compiling MicroRTS..."
mkdir -p logs bin
find src -name '*.java' > sources.list
javac -cp "lib/*:bin" -d bin @sources.list
echo "Compilation complete."

# Initialize results file
echo "# MicroRTS LLM Benchmark Results" > "$RESULTS_FILE"
echo "# Date: $(date)" >> "$RESULTS_FILE"
echo "# SLURM Job ID: $SLURM_JOB_ID" >> "$RESULTS_FILE"
echo "# Node: $(hostname)" >> "$RESULTS_FILE"
echo "# GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)" >> "$RESULTS_FILE"
echo "# Map: maps/8x8/basesWorkers8x8.xml" >> "$RESULTS_FILE"
echo "# Timeout: ${RUN_TIME_PER_GAME_SEC}s per game" >> "$RESULTS_FILE"
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
        echo "Log: $LOGFILE"

        # Run game with timeout
        timeout_result=0
        timeout "$RUN_TIME_PER_GAME_SEC" java -cp "lib/*:bin" rts.MicroRTS > "$LOGFILE" 2>&1 || timeout_result=$?

        # Parse results
        winner="unknown"
        ticks="unknown"
        crashed="no"

        if [ "$timeout_result" -eq 124 ]; then
            crashed="timeout"
            echo "Game timed out after ${RUN_TIME_PER_GAME_SEC}s"
        elif [ "$timeout_result" -ne 0 ]; then
            crashed="error"
            echo "Game exited with code $timeout_result"
        fi

        if grep -q "Player 0 wins" "$LOGFILE" 2>/dev/null; then
            winner="LLM"
        elif grep -q "Player 1 wins" "$LOGFILE" 2>/dev/null; then
            winner="RandomBiasedAI"
        elif grep -q -i "draw" "$LOGFILE" 2>/dev/null; then
            winner="Draw"
        fi

        # Extract tick count if game completed
        if grep -q "Game Over" "$LOGFILE" 2>/dev/null; then
            ticks=$(grep -oP 'cycle[s]?[:\s]+\K\d+' "$LOGFILE" 2>/dev/null | tail -1 || echo "unknown")
        fi

        # Record result
        result="model=$model opponent=RandomBiasedAI map=8x8/basesWorkers8x8 game=$game winner=$winner ticks=$ticks crashed=$crashed"
        echo "$result"
        echo "$result" >> "$RESULTS_FILE"
    done
done

# Cleanup
echo ""
echo "Stopping Ollama..."
kill $OLLAMA_PID 2>/dev/null || true

echo ""
echo "==============================================="
echo "BENCHMARK COMPLETE"
echo "==============================================="
echo ""
echo "Results:"
cat "$RESULTS_FILE"
echo ""
echo "Results saved to: $RESULTS_FILE"
