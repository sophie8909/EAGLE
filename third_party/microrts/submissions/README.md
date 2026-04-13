# MicroRTS LLM Competition - Agent Submissions

## How to Submit Your Agent

### 1. Fork this repository

Fork [MicroRTS](https://github.com/drchangliu/MicroRTS/) to your own GitHub account.

### 2. Create your team folder

```bash
cp -r submissions/_template submissions/your-team-name
```

Use a URL-safe team name (lowercase, hyphens, no spaces): `my-team`, `deepblue-ai`, etc.

### 3. Edit `metadata.json`

```json
{
  "team_name": "your-team-name",
  "display_name": "Your Team Display Name",
  "agent_class": "YourAgent",
  "agent_file": "YourAgent.java",
  "model_provider": "ollama",
  "model_name": "llama3.1:8b",
  "description": "Brief description of your agent's strategy"
}
```

**Fields:**
| Field | Required | Description |
|-------|----------|-------------|
| `team_name` | Yes | Must match folder name (lowercase, hyphens only) |
| `display_name` | Yes | Shown on leaderboard |
| `agent_class` | Yes | Java class name (must match filename) |
| `agent_file` | Yes | Java source filename |
| `model_provider` | Yes | `ollama`, `gemini`, `openai`, `deepseek`, or `none` |
| `model_name` | Yes | Model identifier (e.g., `llama3.1:8b`, `gemini-2.5-flash`) |
| `description` | No | Strategy description |

### 4. Implement your agent

Your Java agent must:
- Have a constructor that takes `UnitTypeTable` as its only parameter
- Not use forbidden APIs (see Security below)

**Two agent types are supported:**

| Type | Base Class | Package | Template |
|------|-----------|---------|----------|
| Abstraction | `AbstractionLayerAI` | `ai.abstraction.submissions.<team_name>` | `_template/Agent.java` |
| MCTS | `NaiveMCTS` (or any `AI` subclass) | `ai.mcts.submissions.<team_name>` | `_template/MCTSAgent.java` |

Replace `<team_name>` with your folder name (hyphens replaced by underscores).

See `_template/Agent.java` or `_template/MCTSAgent.java` for starting points, and `example-team/` for a working example.

### 5. Test locally

```bash
# Build
ant build

# Set your agent in config.properties
# AI1=ai.abstraction.submissions.your_team_name.YourAgent

# Run a game
java -cp "lib/*:bin" rts.MicroRTS -f resources/config.properties
```

### 6. Submit a Pull Request

Push your changes and open a PR against the `master` branch. Your PR should only add files inside `submissions/your-team-name/`.

The CI will automatically validate your submission.

## Security Restrictions

The following Java APIs are **forbidden** in submissions:

- `Runtime.exec` / `ProcessBuilder` - No spawning processes
- `ServerSocket` / `Socket` (except HTTP to LLM APIs) - No network servers
- `System.exit` - No terminating the JVM
- `java.io.File.delete` / `Files.delete` - No deleting files
- `ClassLoader` / `Reflection` (beyond standard use) - No dynamic class loading
- `Thread` (creating new threads) - No multithreading

Submissions that attempt to circumvent these restrictions will be rejected.

## Directory Structure

```
submissions/
  _template/           # Starting point for new agents
    metadata.json      # Team info schema
    Agent.java         # AbstractionLayerAI template
    MCTSAgent.java     # NaiveMCTS template
  example-team/        # Working example submission
    metadata.json
    WorkerRushLLMAgent.java
  your-team-name/      # Your submission
    metadata.json
    YourAgent.java
```
