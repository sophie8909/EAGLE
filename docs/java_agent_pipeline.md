# Java Agent Pipeline

Each candidate is one complete strategy genome with three candidate-level components: the overall strategy description, the complete behavior-function collection, and generation guidance. The six required behavior functions are never crossed over, mutated, or requested independently.

## Generation boundary

The generation backend receives one prompt describing every fixed function slot and the previous complete function set. It must return exactly one JSON object:

```json
{"functions":{"controller":"...","economy":"...","combat":"...","expansion":"...","target_selection":"...","path_selection":"..."}}
```

Values are method bodies only. Parsing rejects missing or unknown keys. Each body is then validated independently for emptiness, Markdown fences, package/import/type declarations, nested method declarations, and attempts to escape the predefined method scope.

## Java sources

`generation/agent_template.py` renders two sources:

- `GeneratedAgent_<id>.java` is the fixed MicroRTS wrapper. It owns `AI` lifecycle methods, `GameState` context collection, action assembly, fallback handling, and framework parameters. No LLM output is inserted into this file.
- `GeneratedAgent_<id>Behaviors.java` is the only generated/evolved Java source. All six predefined methods are rendered together from the validated bodies.

`evaluation/compiler.py` compiles both sources in one `javac` invocation. Successful candidates proceed through existing Java validation and MicroRTS evaluation. Generation, JSON parsing, body validation, or compilation failures retain the `-1000` game-performance score; completed matches retain their real score.

## Evolution

Strategy reflection updates the overall intended MicroRTS strategy. Code-generation reflection updates the complete generation guidance using compilation/validation/runtime errors, alignment feedback, and the previous complete function set. The next generation request always regenerates all bodies together.

Crossover selects candidate components. The behavior-function dictionary is selected whole from one parent; there is no per-function crossover.

## Candidate artifacts

Each candidate directory includes:

```text
prompt.json
CandidateAgent.java
CandidateBehaviors.java
compile.log
result.json
```

The Java filenames are stable artifact labels; their declared generated class names remain candidate-specific. Existing detailed metrics and debug artifacts are also retained.
