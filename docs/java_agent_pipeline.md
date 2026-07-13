# Java Agent Pipeline

Each candidate evolves one overall strategy, one complete CandidateAgent.java source file, and generation guidance. There is no JSON function map and no six-body fill-in protocol.

## Single complete Java source

The repository reference source is eagle/java_templates/CandidateAgent.java. It contains:

- the AbstractionLayerAI lifecycle and UnitTypeTable setup;
- one strategy region marked by EAGLE_AGENT_STRATEGY_START and EAGLE_AGENT_STRATEGY_END comments;
- one fixed action API region marked by EAGLE_ACTION_HELPERS_START and EAGLE_ACTION_HELPERS_END comments;
- six typed action helpers: commandMove, commandHarvest, commandTrain, commandBuild, commandAttack, and commandIdle;
- AgentContext, lookup helpers, action translation, and adjacent-enemy auto-defense.

The strategy region is not divided into predefined bodies. The model may add, remove, rename, or reorganize strategy helper methods inside that region. It operates units through the six fixed action helpers.

## Complete Java generation contract

Every generation request includes the previous complete CandidateAgent.java, or the repository template for a new candidate. The final prompt instructions require one complete Java file from package ai.generated; through the final class brace.

The model response content must be Java source, not JSON, a functions object, a patch, individual method bodies, an explanation, or Markdown fences. The OpenAI-compatible HTTP transport still uses JSON around the chat message because that is the API protocol; only the message content is treated as generated Java.

Python validates the complete class identity, lifecycle entry point, strategy markers, fixed action-helper markers, six action-helper declarations, and forbidden runtime I/O. It extracts only the single marked strategy region for objective static analysis. The exact complete source returned by the model is written to CandidateAgent.java and passed to javac without re-rendering.

## Generated layout

For candidate ID, successful generation writes one file under:

    generated_agents/<id>/CandidateAgent.java

Candidate artifacts also save that same complete source as CandidateAgent.java and generated_java_source.java. Candidate results expose strategy_region for score auditing; they do not store six generated body entries.

## Deterministic code-quality fitness

Code quality uses compilation status, complete-Java strategy-region validity, and deterministic static metrics. No evaluator LLM is used.

Static quality analyzes only the single marked strategy region:

- 20 points for coverage of the six command helpers;
- up to 10 points for calls among strategy methods declared by that candidate;
- 15 points for reading distinct game-state signals;
- up to 15 smooth points for branches and loops;
- up to 15 smooth points for executable statement count and effective code length;
- up to 25 maintainability points, reduced by excessive complexity, nesting, duplicate lines, oversized regions, and very long lines.

Comments, whitespace, and string contents are removed before measurement. Effective executable length changes the score continuously, while code above 12,000 effective characters receives an oversize penalty. Raw metrics and component scores are saved under code_quality_breakdown.static_metrics.
