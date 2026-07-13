# Java Agent Pipeline

Each candidate evolves one complete strategy: an overall strategy description, six Java behavior functions, and generation guidance.

## Single repository-owned Java source

The complete source structure lives in `eagle/java_templates/CandidateAgent.java`. It owns:

- the `AbstractionLayerAI` lifecycle and `UnitTypeTable` setup;
- all six evolvable strategy methods;
- the fixed `AgentContext` and path choice types;
- action translation through `translateActions`;
- six typed action helpers: `commandMove`, `commandHarvest`, `commandTrain`, `commandBuild`, `commandAttack`, and `commandIdle`;
- safe lookup helpers and adjacent-enemy auto-defense.

There is no separate behavior class or second Java source.

## Complete Java generation contract

The generation prompt includes the current complete known-good `CandidateAgent.java` and requires the backend to return the entire revised Java file, from `package ai.generated;` through the final class brace.

The response may be raw Java or one enclosing `java` code fence. Explanation text, JSON wrappers, omitted sections, placeholders, ellipses, missing strategy methods, missing action helpers, changed class identity, and forbidden runtime I/O or LLM APIs fail validation before compilation.

After validating the complete file, Python extracts the bodies of the six exact strategy method signatures. Those bodies continue to drive function scoring, mutation, crossover, and candidate persistence. The complete LLM-produced Java source is the source passed to `javac`; Python does not re-render a different file after generation.

Changing a strategy signature requires coordinated edits to `CandidateAgent.java` and `eagle/module_contract.py` (plus `MODULE_NAMES` in `eagle/candidate.py` when a function is added or removed).

## Generated layout

For candidate `<id>`, successful generation writes:

```text
generated_agents/
  <id>/
    CandidateAgent.java
```

Candidate artifacts save the same complete generated source as `CandidateAgent.java` and `generated_java_source.java` for inspection.

## Deterministic code-quality fitness

Code quality no longer uses an LLM judge. The objective is the sum of compilation score, required-function score, and a deterministic static-quality score from 0 to 100.

Static quality analyzes only the six generated strategy method bodies, not the fixed repository template:

- 20 points for coverage of the six command helpers;
- 10 points for connections among strategy functions;
- 15 points for reading distinct game-state signals;
- up to 15 smooth points for branches and loops;
- up to 15 smooth points for executable statement count and effective code length;
- up to 25 maintainability points, reduced by excessive complexity, nesting, duplicate lines, oversized bodies, and very long lines.

Comments, whitespace, and string contents are removed before measurement, so formatting changes do not manufacture fitness differences. Effective executable length changes the score continuously, while code above 12,000 effective characters receives an oversize penalty. Every raw metric and component score is persisted under code_quality_breakdown.static_metrics for audit and mutation feedback.
