#!/usr/bin/env python3
"""
Phase 1: Benchmark local Ollama models (no API keys needed).
Tests each model with Hybrid and Search+LLM agent types only (PureLLM is useless on CPU).
"""
import os
import sys

# Must run from MicroRTS directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.')

import benchmark_arena as ba

MODELS_TO_TEST = [
    "deepseek-r1:8b",
    "gemma3",
    "llama3.2",
]

for model in MODELS_TO_TEST:
    print(f"\n{'='*70}")
    print(f"  BENCHMARKING: {model}")
    print(f"{'='*70}\n")

    # Set env var
    os.environ["OLLAMA_MODEL"] = model

    # Configure LLMS to only Hybrid + Search+LLM (skip PureLLM)
    ba.LLMS = {
        "ai.abstraction.HybridLLMRush": {
            "name": "hybrid",
            "display": f"{model} (Hybrid)",
            "agent_type": "Hybrid",
            "env": {"OLLAMA_MODEL": model}
        },
        "ai.mcts.llmguided.LLMInformedMCTS": {
            "name": "mcts",
            "display": f"{model} (Search+LLM)",
            "agent_type": "Search+LLM",
            "env": {"OLLAMA_MODEL": model}
        },
    }

    try:
        ba.run_tournament(games_per_pair=1)
    except Exception as e:
        print(f"ERROR benchmarking {model}: {e}")
        import traceback
        traceback.print_exc()

print("\n\nAll Phase 1 benchmarks complete!")
print("Run: python3 generate_leaderboard.py")
