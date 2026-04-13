# Game Trace Examples

This directory contains example game traces that can be replayed in the MicroRTS GUI.

## What is a Trace?

A trace is a recording of all game states and actions throughout a match. It allows you to replay and analyze games step-by-step.

## Available Traces

| File | Description | Result |
|------|-------------|--------|
| `ollama_vs_random.xml` | llama3.1:8b (LLM) vs RandomBiasedAI | Draw (500 ticks) |

## How to View a Trace

### Prerequisites

1. Compile the project (if not already done):
   ```bash
   find src -name '*.java' > sources.list
   javac -cp "lib/*:bin" -d bin @sources.list
   ```

2. Ensure you have a display environment (X11, etc.) for the GUI.

### View the Trace

```bash
java -cp "lib/*:bin" tests.trace.TraceVisualizationTest examples/traces/ollama_vs_random.xml
```

This opens a GUI window with:
- **Left panel**: Visual game state showing the map, units, and resources
- **Right panel**: List of game ticks with actions taken

Click on different entries in the right panel to jump to that point in the game.

## Recording Your Own Traces

Use the `RecordLLMGame` tool to record new game traces:

```bash
# Basic usage
java -cp "lib/*:bin" tests.trace.RecordLLMGame <AI1_class> <AI2_class> <output_prefix> [max_cycles] [map]

# Example: Record Gemini vs WorkerRush
GEMINI_API_KEY="your_key" java -cp "lib/*:bin" tests.trace.RecordLLMGame \
  ai.abstraction.LLM_Gemini \
  ai.abstraction.WorkerRush \
  my_trace \
  1000

# Example: Record Ollama vs RandomBiasedAI
OLLAMA_MODEL="llama3.1:8b" java -cp "lib/*:bin" tests.trace.RecordLLMGame \
  ai.abstraction.ollama \
  ai.RandomBiasedAI \
  my_trace \
  500
```

This creates:
- `my_trace.xml` - XML format trace (for TraceVisualizationTest)
- `my_trace.json` - JSON format trace (for programmatic analysis)

## Trace File Format

Traces are XML files containing:
- Unit type definitions
- Sequence of game states at each tick where actions occurred
- Player actions for each unit

Example structure:
```xml
<rts.Trace>
  <rts.units.UnitTypeTable>...</rts.units.UnitTypeTable>
  <entries>
    <rts.TraceEntry time="0">
      <PhysicalGameState>...</PhysicalGameState>
      <actions>...</actions>
    </rts.TraceEntry>
    ...
  </entries>
</rts.Trace>
```
