# Java Agent Pipeline

Each candidate evolves one complete strategy: an overall strategy description, six Java behavior-function bodies, and generation guidance. EAGLE requests and replaces all six bodies together.

## Single repository-owned Java source

The complete source structure lives in `eagle/java_templates/CandidateAgent.java`. It owns:

- the `AbstractionLayerAI` lifecycle and `UnitTypeTable` setup;
- all six evolvable `/* EAGLE_BODY:<function_name> */` slots;
- the fixed `AgentContext` and path choice types;
- action translation through `translateActions`;
- six typed action helpers: `commandMove`, `commandHarvest`, `commandTrain`, `commandBuild`, `commandAttack`, and `commandIdle`;
- safe lookup helpers and adjacent-enemy auto-defense.

Python validates this checked-in template, validates the backend JSON function set and bodies, replaces the six markers, rejects unresolved markers, and writes exactly one rendered `CandidateAgent.java`. There is no separate behavior class or second Java source.

Changing a behavior signature requires coordinated edits to `CandidateAgent.java` and `eagle/module_contract.py` (plus `MODULE_NAMES` in `eagle/candidate.py` when a function is added or removed).

## Generation boundary

The backend returns one JSON object containing every fixed function body:

```json
{"functions":{"controller":"...","economy":"...","combat":"...","expansion":"...","target_selection":"...","path_selection":"..."}}
```

Each value must be a Java method body string. Complete method declarations, nested `{ "body": ... }` objects, extra function keys, empty bodies, package/import/type declarations, helper method declarations, markdown inside function bodies, text outside the outer JSON fence, and unbalanced scopes fail validation before compilation. One `json` fence enclosing the entire response is removed before strict JSON parsing.

The generation prompt lists the exact six fixed action helper signatures and the available `AgentContext`, unit-type, and lookup fields. Generated bodies issue high-level actions through these helpers; they do not construct `PlayerAction` or access runtime LLM/network/file APIs.

## Generated layout

For candidate `<id>`, successful generation writes:

```text
generated_agents/
  <id>/
    CandidateAgent.java
```

Only that source is passed to `javac`. Candidate artifacts also save the same rendered source as `CandidateAgent.java` and `generated_java_source.java` for inspection.