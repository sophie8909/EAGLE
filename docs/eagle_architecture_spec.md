# EAGLE Architecture Specification

> **EAGLE = Evolutionary Algorithm for Game-playing with LLM-Enabled Agents**

## 1. Scope

EAGLE evolves prompt components that generate complete MicroRTS Java agents.

EAGLE does not evolve:

- fixed Java functions
- isolated method bodies
- Java patches
- diffs
- runtime LLM-controlled agents

Each candidate contains a three-component genotype.

An LLM converts that genotype into a complete:

```text
CandidateAgent.java
```

The generated Java agent is compiled once and evaluated across a fixed 10-opponent MicroRTS roster without regenerating the program.

The optimizer uses two objectives:

```text
game_performance
code_quality
```

------

# 2. Core Model

## 2.1 Genotype

Each candidate genotype contains:

```text
Candidate
├── strategy_prompt
├── previous_code
└── generation_prompt
```

Notation:

```text
A = strategy_prompt
B = previous_code
C = generation_prompt
```

A candidate genotype is represented as:

```text
A1 + B1 + C1
```

------

## 2.2 Phenotype

The phenotype is the complete Java agent generated from the genotype:

```text
A + B + C
    │
    ▼
Generation LLM
    │
    ▼
CandidateAgent.java
```

The generated Java source is the executable phenotype.

------

## 2.3 Parent Generated Java

`previous_code` for a child must be the Java source most recently generated for and evaluated as its parent.

It must not be the older Java source that was originally included in the parent generation prompt.

Example:

```text
Parent input genotype:
A1 + B1 + C1

Parent generation output:
B2
```

After generation and evaluation, the parent state available for inheritance is:

```text
A1 + B2 + C1
```

not:

```text
A1 + B1 + C1
```

`B2` is the source that was actually:

- validated
- compiled
- integrated with MicroRTS
- executed
- evaluated

------

# 3. Candidate Data Contract

Each candidate should contain at least:

```text
candidate_id
generation
parent_ids

strategy_prompt
previous_code
generation_prompt

generated_java
generated_java_path

operator
mutation_type

strategy_parent_id
previous_code_parent_id
generation_prompt_parent_id

status
failure_stage
failure_reason

game_performance
code_quality

artifacts
timing
```

Recommended conceptual separation:

```text
CandidateGenotype
├── strategy_prompt
├── previous_code
└── generation_prompt

CandidatePhenotype
└── generated_java

CandidateEvaluation
├── game_performance
├── code_quality
├── match_results
└── failure information
```

------

# 4. End-to-End Pipeline

```text
Evaluated Population
        │
        ▼
Parent Selection
        │
        ▼
Uniform Crossover
        │
        ▼
Optional Mutation
        │
        ├── Strategy Mutation
        │   ├── Reflection LLM
        │   └── Strategy Rewrite LLM
        │
        └── Code Mutation
            ├── Reflection LLM
            └── Generation Prompt Rewrite LLM
        │
        ▼
Complete Child Genotype
        │
        ▼
Java Generation LLM
        │
        ▼
Complete CandidateAgent.java
        │
        ▼
Source Validation
        │
        ▼
Compilation
        │
        ▼
MicroRTS Integration
        │
        ▼
10 Matches vs Evaluation Roster
        │
        ▼
Game Performance
        │
        ▼
Code Quality
        │
        ▼
NSGA-II Survivor Selection
        │
        ▼
Next Generation
```

Crossover and mutation modify genotype components.

They do not directly produce the final child Java.

Every offspring must pass through the Java Generation LLM after crossover and optional mutation.

------

# 5. Parent Selection

Use NSGA-II rank and crowding distance.

Recommended parent selection:

```text
Binary Tournament Selection
```

Comparison order:

1. lower Pareto rank
2. higher crowding distance
3. random tie-break

Parent selection does not modify genotype or phenotype.

------

# 6. Uniform Crossover

Uniform crossover operates independently over the three genotype components.

Parent A:

```text
A_strategy
A_generated_java
A_generation_prompt
```

Parent B:

```text
B_strategy
B_generated_java
B_generation_prompt
```

Possible child genotype:

```text
A_strategy
B_generated_java
A_generation_prompt
```

Each component must independently come from Parent A or Parent B.

------

## 6.1 Crossover Inputs

The crossover components are:

```text
strategy_prompt
parent.generated_java
generation_prompt
```

The previous-code crossover source must be:

```text
parent.generated_java
```

It must not use:

```text
parent.previous_code
```

unless that field has already been explicitly updated to the parent’s latest generated Java.

------

## 6.2 Provenance

Crossover must persist component-level provenance:

```json
{
  "strategy_parent_id": "parent_a",
  "previous_code_parent_id": "parent_b",
  "generation_prompt_parent_id": "parent_a"
}
```

This provenance must later be available to:

- mutation feedback selection
- artifact inspection
- lineage reconstruction
- debugging

------

## 6.3 Crossover Output

Crossover produces only a new genotype:

```text
crossed_strategy_prompt
crossed_previous_code
crossed_generation_prompt
```

The selected previous code is not the final child phenotype.

The crossed genotype must be sent to the Generation LLM:

```text
crossed A + crossed B + crossed C
                │
                ▼
        Java Generation LLM
                │
                ▼
      new CandidateAgent.java
```

------

# 7. Mutation Overview

Mutation has two types:

```text
strategy_mutation
code_mutation
```

Each mutation uses two LLM stages:

```text
Phase 1: Reflection
Phase 2: Prompt Rewrite
```

After the mutation completes, a third LLM call generates the child Java.

Therefore, a mutated offspring normally requires:

```text
1 reflection call
1 rewrite call
1 Java generation call
```

Total:

```text
3 LLM calls
```

Mutation never directly edits Java source.

------

# 8. Strategy Mutation

Strategy Mutation modifies only:

```text
strategy_prompt
```

It preserves:

```text
previous_code
generation_prompt
```

------

## 8.1 Strategy Mutation Phase 1: Reflection

### Inputs

```text
current strategy_prompt
parent generated_java
10-match game_performance summary
per-match result
wins
draws
losses
final player resources
final enemy resources
final resource difference
unit material statistics
survival statistics
round-state summary
behavior summary
opponent identity
```

Opponent:

```text
fixed evaluation roster
```

### Output

```text
strategy_reflection
```

The reflection should analyze:

- which strategic ideas worked
- which strategic ideas failed
- whether the generated Java implemented the intended strategy
- resource allocation quality
- production timing
- attack timing
- defense across the fixed evaluation roster
- target selection
- unit composition
- behavior that should be preserved
- behavior that should be changed
- concrete requirements for the next strategy prompt

The reflection stage must not:

- generate Java
- rewrite the strategy prompt
- rewrite the generation prompt

------

## 8.2 Strategy Mutation Phase 2: Rewrite

### Inputs

```text
original strategy_prompt
strategy_reflection
parent generated_java
game evaluation summary
```

### Output

```text
new strategy_prompt
```

Output requirements:

- output only the rewritten strategy prompt
- do not output Java
- do not output analysis
- do not rewrite the generation prompt
- preserve strategy elements judged effective
- directly address issues identified by the reflection
- avoid generic or non-actionable wording

------

## 8.3 Strategy Mutation State Transition

Before mutation:

```text
A1 + B2 + C1
```

After Strategy Rewrite:

```text
A2 + B2 + C1
```

After Java Generation:

```text
A2 + B3 + C1
```

The child’s inherited state for the next generation becomes:

```text
A2 + B3 + C1
```

------

# 9. Code Mutation

Code Mutation modifies only:

```text
generation_prompt
```

It preserves:

```text
strategy_prompt
previous_code
```

------

## 9.1 Code Mutation Phase 1: Reflection

### Inputs

```text
strategy_prompt
current generation_prompt
parent generated_java
latest generated child Java, if available
raw generation response
source validation result
compiler result
compiler errors
compiler warnings
MicroRTS integration result
runtime failure
completed match count
function capability score
strategy alignment score
failure stage
failure category
failure reason
```

### Output

```text
code_reflection
```

The reflection should analyze:

- whether the LLM returned a complete Java source
- package correctness
- class correctness
- superclass correctness
- constructor compatibility
- required MicroRTS method compatibility
- `getAction` compatibility
- compiler failures
- compiler warnings
- invalid API usage
- class loading problems
- initialization problems
- runtime exceptions
- illegal actions
- deadlocks or timeouts
- unreachable or duplicate code
- missing gameplay capabilities
- mismatch between strategy and implementation
- constraints that should be added
- obsolete constraints that should be removed

The reflection stage must not directly generate a replacement Java file.

------

## 9.2 Code Mutation Phase 2: Rewrite

### Inputs

```text
original generation_prompt
code_reflection
strategy_prompt
parent generated_java
code-quality summary
```

### Output

```text
new generation_prompt
```

Output requirements:

- output only the rewritten generation prompt
- do not output Java
- do not rewrite the strategy prompt
- explicitly address confirmed generation failures
- preserve valid MicroRTS constraints
- remove obsolete or contradictory instructions
- avoid accumulating unbounded historical error text
- keep the prompt usable for full-file regeneration

------

## 9.3 Code Mutation State Transition

Before mutation:

```text
A1 + B2 + C1
```

After Generation Prompt Rewrite:

```text
A1 + B2 + C2
```

After Java Generation:

```text
A1 + B3 + C2
```

The child’s inherited state for the next generation becomes:

```text
A1 + B3 + C2
```

------

# 10. Mutation Selection

Use Strategy Mutation when valid gameplay evidence exists.

Typical Strategy Mutation inputs:

```text
completed matches
game_performance
wins / draws / losses
resource statistics
unit statistics
behavior summary
```

Prefer Code Mutation when the candidate has:

```text
generation failure
validation failure
compilation failure
MicroRTS integration failure
runtime failure
low function score
low strategy alignment
excessive warnings
```

Candidates without reliable gameplay results should not use Strategy Mutation as the primary operator.

------

# 11. Java Generation

All offspring must pass through Java Generation after crossover and optional mutation.

### Inputs

```text
strategy_prompt
previous_code
generation_prompt
```

### Output

```text
complete CandidateAgent.java
```

The Generation LLM must return:

- one complete Java source file
- no patch
- no diff
- no JSON
- no isolated method body
- no partial function set
- no prose outside the Java source

The raw response must be saved before extraction.

------

# 12. Java Runtime Contract

The local LLM is not required to preserve a fixed function structure.

Do not require:

```text
fixed method names
fixed six-function architecture
fixed helper method count
fixed internal class structure
fixed strategy region
fixed code layout
```

The complete source must satisfy this exact external identity contract:

```text
package: ai.generated
public class: CandidateAgent
superclass: AbstractionLayerAI
```

Required constructors:

```java
CandidateAgent(UnitTypeTable utt)
CandidateAgent(UnitTypeTable utt, AStarPathFinding pathFinding)
```

Required callable methods:

```java
PlayerAction getAction(int player, GameState gs)
void reset()
AI clone()
```

Validation must require both constructors and all three callable methods. It must not require fixed helper names, helper counts, a strategy region, or any other internal layout.

Security and execution restrictions:

```text
no network access
no external process creation
no unauthorized file I/O
no runtime modification
no unavailable third-party dependencies
```

Validation should enforce the external runtime contract, not an internal coding style.

## 12.1 MicroRTS Integration Contract

After compilation and before match execution, run these seven checks in order:

1. Load `ai.generated.CandidateAgent` from the candidate classpath.
2. Verify that the loaded class is a valid MicroRTS `AI` and extends `AbstractionLayerAI`.
3. Locate and successfully invoke both required constructors.
4. Call `reset()` successfully.
5. Call `clone()` and verify that it returns a non-null valid `AI` instance.
6. Call `getAction(int player, GameState gs)` with a minimal valid `GameState`.
7. Verify that `getAction()` returns a non-null valid `PlayerAction`.

Persist one result for each check with `passed`, `failed`, or `blocked` status and a failure reason. If an earlier failure prevents a later check, the later check is `blocked` and does not count as passed.

The integration stage does not start any of the 10 evaluation matches. Match execution begins only after all seven checks pass.

------

# 13. Evaluation Protocol

Each generated Java candidate is:

1. validated
2. compiled once
3. integrated with MicroRTS
4. evaluated in 10 matches against the fixed Evolution Evaluation roster

The Java source must not be regenerated between the 10 matches.

Configuration:

```text
matches_per_candidate = 10
evaluation_opponents =
  tma
  mayari
  coac
  random
  random_biased
  passive
  light_rush
  heavy_rush
  historical_self_1
  historical_self_2
```

The first eight opponents are fixed pinned agents: TMA, Mayari, COAC, RandomAI, RandomBiasedAI, PassiveAI, LightRush, and HeavyRush. TMA, Mayari, and COAC are external Java agents and must be prepared from the pinned manifest before any real evolution run. The two historical-self opponents are compiled from prior evaluated candidate Java when available; generation zero may use the current candidate source as the historical-self bootstrap. An unavailable external opponent is an experiment setup failure, not a candidate runtime failure and not a signal to substitute another baseline.

Across the 10 matches:

- use the same generated Java
- use the same compiled classes
- do not call the generation LLM again
- do not mutate the candidate
- write separate artifacts per match
- use distinct game seeds where supported
- persist the resolved opponent identity and any external classpath artifact per match

------

## 13.1 Evaluation Stages

```text
Java Generation
    │
    ▼
Source Validation
    │
    ▼
Compilation
    │
    ▼
MicroRTS Integration Check
    │
    ▼
10 Matches
    │
    ▼
Game Performance
    │
    ▼
Code Quality
```

------

# 14. Objective 1: Game Performance

`game_performance` evaluates gameplay across 10 matches.

Higher is better.

------

## 14.1 Evaluation Failure

If the candidate cannot complete a valid evaluation because of:

```text
generation failure
source validation failure
compilation failure
MicroRTS integration failure
runtime failure
invalid result
unparseable result
zero valid matches
partial match completion
```

then:

```text
game_performance = -1000
```

Failure-stage differences are represented by `code_quality`.

------

## 14.2 Match Result Score

Per-match base score:

```text
Win  = +100
Draw =    0
Loss = -100
```

------

## 14.3 Bounded Shaping Score

Additional gameplay signals may adjust the result score.

The total shaping contribution must be bounded:

```text
-10 <= shaping_score <= +10
```

This guarantees:

```text
Win > Draw > Loss > Failure
```

Expected per-match score ranges:

```text
Win:   +90 to +110
Draw:  -10 to  +10
Loss: -110 to  -90
```

------

## 14.4 Unit Material Score

For each recorded tick:

```text
material_difference_t =
    player_material_t - enemy_material_t
```

Compute:

```text
mean_material_difference =
    mean(material_difference_t)
```

Normalize:

```text
unit_material_score =
    5 * tanh(mean_material_difference / material_scale)
```

Range:

```text
-5 to +5
```

Unit material values must be configured centrally for:

```text
Worker
Light
Heavy
Ranged
Base
Barracks
other supported unit types
```

------

## 14.5 Final Resource Score

Compute:

```text
final_resource_difference =
    player_final_resources - enemy_final_resources
```

Normalize:

```text
final_resource_score =
    3 * tanh(final_resource_difference / resource_scale)
```

Range:

```text
-3 to +3
```

------

## 14.6 Survival Score

Survival must remain a small shaping term.

```text
survival_ratio =
    final_tick / max_cycles
```

Suggested formula:

```text
if result == loss:
    survival_score = 2 * survival_ratio

if result == win:
    survival_score = 2 * (1 - survival_ratio)

if result == draw:
    survival_score = 0
```

Range:

```text
0 to +2
```

Interpretation:

- surviving longer during a loss receives a small reward
- winning faster receives a small reward
- survival cannot convert a loss into a positive score

------

## 14.7 Per-Match Score

```text
match_score =
    result_score
  + unit_material_score
  + final_resource_score
  + survival_score
```

After calculation, clamp non-result contributions if necessary:

```text
-10 <=
    unit_material_score
  + final_resource_score
  + survival_score
<= +10
```

------

## 14.8 Candidate Aggregation

Final objective:

```text
game_performance =
    mean(match_score_1 ... match_score_10)
```

Also persist:

```text
wins
draws
losses
win_rate
mean_result_score
mean_material_score
mean_final_resource_score
mean_survival_score
score_stddev
minimum_match_score
maximum_match_score
completed_match_count
```

If fewer than 10 matches complete successfully:

```text
game_performance = -1000
```

Completed match evidence must still be retained.

------

# 15. Objective 2: Code Quality

`code_quality` serves two purposes:

1. distinguish different failure stages
2. evaluate successful Java agents

Higher is better.

------

# 16. Failure Hierarchy

Failure stages must have distinct fitness values.

Required ordering:

```text
Generation / Validation Failure
    <
Compilation Failure
    <
MicroRTS Integration Failure
    <
Runtime Failure
    <
Successful Execution
```

A candidate that reaches a later pipeline stage must receive a better `code_quality` score than one that fails earlier.

------

## 16.1 Failure Base Ranges

Recommended ranges:

| Failure stage                                       | Code quality range          |
| --------------------------------------------------- | --------------------------- |
| Backend failure / empty output / extraction failure | `-1000`                     |
| Source validation failure                           | `-950`                      |
| Compilation failure                                 | `-900` to `-800`            |
| MicroRTS integration failure                        | `-600` to `-500`            |
| Runtime failure                                     | `-400` to `-201`            |
| Successful 10-match execution                       | normal code-quality formula |

------

## 16.2 Generation Failure

Examples:

```text
backend unavailable
HTTP failure
empty response
invalid response format
no extractable Java source
```

Score:

```text
code_quality = -1000
```

------

## 16.3 Validation Failure

Examples:

```text
wrong package
wrong public class
invalid superclass
missing required runtime contract
forbidden API usage
invalid source contract
```

Score:

```text
code_quality = -950
```

------

## 16.4 Compilation Failure

Base:

```text
-800
```

Suggested formula:

```text
compile_failure_score =
    -800 - min(error_count * 5, 100)
```

Range:

```text
-900 to -800
```

Fewer compiler errors produce a better score.

Compilation failures must not fall below generation or validation failure ranges.

------

## 16.5 MicroRTS Integration Failure

This stage means Java compiled successfully but could not be used by MicroRTS.

Examples:

```text
class not found
invalid constructor
invalid superclass
missing required AI method
wrong method signature
class loading error
initialization failure
getAction not callable
```

Compute the pass ratio from the seven ordered checks in section 12.1:

```text
integration_pass_ratio =
    passed_check_count / 7
```

Blocked or unattempted checks do not count as passed.

Formula:

```text
integration_failure_score =
    -600 + round(integration_pass_ratio * 100)
```

Range:

```text
-600 to -500
```

------

## 16.6 Runtime Failure

The Java agent:

- generated successfully
- passed validation
- compiled
- loaded into MicroRTS
- started execution

but then failed during one or more matches.

Examples:

```text
runtime exception
NullPointerException
illegal action
deadlock
process timeout
match crash
invalid result
missing result
partial match completion
```

Compute:

```text
runtime_progress =
    completed_matches / 10
```

Suggested score:

```text
runtime_failure_score =
    -400 + round(runtime_progress * 199)
```

Range:

```text
-400 to -201
```

Examples:

```text
0 completed matches  -> -400
5 completed matches  -> approximately -300
9 completed matches  -> approximately -221
```

Runtime failures must remain below the successful execution range.

------

# 17. Successful Code Quality

A candidate that completes all 10 matches uses:

```text
code_quality =
    500
  + compilation_score
  + function_score
  + strategy_alignment_score
```

------

## 17.1 Compilation Score

Successful compile baseline:

```text
0
```

Warning penalty:

```text
-50 per compiler warning
```

Formula:

```text
compilation_score =
    -50 * warning_count
```

Requirements:

- invoke `javac` with explicit warning flags such as `-Xlint`
- count compiler diagnostics, not raw stderr lines
- deduplicate repeated diagnostics
- persist every warning
- cap the penalty

Recommended lower bound:

```text
compilation_score >= -500
```

------

## 17.2 Function Capability Score

Maximum:

```text
100
```

This score evaluates gameplay capabilities, not fixed method names.

Recommended capabilities:

| Capability                     | Maximum |
| ------------------------------ | ------- |
| Economy and resource gathering | 20      |
| Unit production                | 20      |
| Combat execution               | 20      |
| Target selection               | 20      |
| State-aware decision-making    | 20      |

Formula:

```text
function_score =
    economy_score
  + production_score
  + combat_score
  + targeting_score
  + state_aware_decision_score
```

Recommended per-capability levels:

```text
0  = absent or unusable
10 = partially present
20 = clearly present and reachable
```

Evaluation should use:

```text
deterministic static analysis
runtime evidence
match telemetry
```

Do not require specific function names.

------

## 17.3 Strategy Alignment Score

Use an independent LLM evaluator.

Range:

```text
0 to 10
```

Inputs:

```text
strategy_prompt
generated CandidateAgent.java
optional match behavior summary
```

Evaluation criteria:

- implementation matches the intended strategy
- production behavior matches the strategy
- resource behavior matches the strategy
- attack and defense behavior match the strategy
- important requirements are implemented
- no major behavior contradicts the strategy
- relevant code is reachable and behaviorally meaningful

Required structured response:

```json
{
  "score": 0,
  "reason": "..."
}
```

Validation:

```text
0 <= score <= 10
```

Persist both:

```text
score
reason
```

Only the numeric score contributes to the objective.

------

## 17.4 Successful Score Range

Component ranges:

```text
compilation_score:      -500 to 0
function_score:            0 to 100
strategy_alignment_score:  0 to 10
successful_base:         500
```

Therefore:

```text
successful code_quality range:
0 to 610
```

This selected `+500` base guarantees:

```text
successful execution > runtime failure
```

No additional successful-execution clamp or hidden offset is permitted. Persist the selected formula through `objective_formula_version`.

------

# 18. Objective Examples

| Candidate | State                             | Game performance | Code quality       |
| --------- | --------------------------------- | ---------------- | ------------------ |
| A         | backend returned empty output     | -1000            | -1000              |
| B         | invalid Java contract             | -1000            | -950               |
| C         | compilation failed                | -1000            | -830               |
| D         | compiled but failed integration   | -1000            | -550               |
| E         | completed 8 matches, then crashed | -1000            | approximately -241 |
| F         | completed 10 matches              | aggregated score | successful formula |

This prevents all failure candidates from collapsing to the same objective vector.

------

# 19. NSGA-II Behavior

All candidates remain in the evaluated population, including failures.

Failure candidates use:

```text
game_performance = -1000
```

Their `code_quality` differentiates pipeline progress.

The optimizer can therefore distinguish:

```text
invalid source
compiled source
MicroRTS-loadable source
partially executable source
fully executable source
```

------

# 20. LLM Call Accounting

## 20.1 Crossover-Only Offspring

```text
Uniform Crossover
        │
        ▼
Java Generation LLM
```

Calls:

```text
1
```

------

## 20.2 Strategy Mutation Offspring

```text
Strategy Reflection LLM
        │
        ▼
Strategy Rewrite LLM
        │
        ▼
Java Generation LLM
```

Calls:

```text
3
```

------

## 20.3 Code Mutation Offspring

```text
Code Reflection LLM
        │
        ▼
Generation Prompt Rewrite LLM
        │
        ▼
Java Generation LLM
```

Calls:

```text
3
```

------

## 20.4 Strategy Alignment Evaluation

After successful Java generation and execution:

```text
Strategy Alignment LLM
```

This call belongs to evaluation, not variation.

------

# 21. Artifact Requirements

Each candidate must persist enough information to fully reconstruct:

- lineage
- genotype
- crossover
- mutation
- generation
- validation
- compilation
- integration
- matches
- objectives
- timing

Recommended structure:

```text
runs/<run_id>/
├── config.yaml
├── resolved_config.json
├── run_summary.json
├── generations/
│   └── generation_<n>/
│       ├── population.json
│       └── candidates/
│           └── <candidate_id>/
│               ├── lineage.json
│               ├── genotype/
│               │   ├── strategy_prompt.txt
│               │   ├── previous_code.java
│               │   └── generation_prompt.txt
│               ├── crossover/
│               │   └── provenance.json
│               ├── mutation/
│               │   ├── metadata.json
│               │   ├── reflector_request.txt
│               │   ├── reflector_response_raw.txt
│               │   ├── rewriter_request.txt
│               │   └── rewriter_response_raw.txt
│               ├── generation/
│               │   ├── request.txt
│               │   ├── response_raw.txt
│               │   ├── extracted_candidate.java
│               │   └── normalized_candidate.java
│               ├── validation/
│               │   └── result.json
│               ├── compilation/
│               │   ├── command.txt
│               │   ├── stdout.txt
│               │   ├── stderr.txt
│               │   └── result.json
│               ├── integration/
│               │   └── result.json
│               ├── strategy_alignment/
│               │   ├── request.txt
│               │   ├── response_raw.txt
│               │   └── result.json
│               ├── matches/
│               │   ├── match_00/
│               │   ├── match_01/
│               │   ├── ...
│               │   └── match_09/
│               ├── evaluation/
│               │   ├── game_performance.json
│               │   ├── code_quality.json
│               │   └── objectives.json
│               ├── timing.json
│               └── candidate_result.json
```

------

# 22. Mutation Artifact Contract

For every mutated candidate, persist both mutation LLM interactions.

Required files:

```text
reflector_request.txt
reflector_response_raw.txt
rewriter_request.txt
rewriter_response_raw.txt
```

Required metadata:

```json
{
  "applied": true,
  "type": "strategy",
  "reflection_model": "",
  "rewrite_model": "",
  "reflection_attempts": 1,
  "rewrite_attempts": 1
}
```

For Code Mutation:

```json
{
  "type": "code"
}
```

For candidates without mutation:

```json
{
  "applied": false,
  "type": null
}
```

Reflection responses must be retained even when rewriting fails.

Rewrite responses must be retained even when Java generation later fails.

------

# 23. Generation Artifact Contract

Every offspring must persist:

```text
generation request
raw LLM response
extracted Java
normalized Java
generation error
retry history
```

Required files:

```text
generation/request.txt
generation/response_raw.txt
generation/extracted_candidate.java
generation/normalized_candidate.java
```

Do not discard the raw generation response after Java extraction.

------

# 24. Lineage Contract

Recommended `lineage.json`:

```json
{
  "candidate_id": "",
  "generation": 0,
  "parent_ids": [],
  "operator": "seed",
  "mutation_type": null,
  "strategy_parent_id": null,
  "previous_code_parent_id": null,
  "generation_prompt_parent_id": null,
  "source_candidate_ids": []
}
```

For crossover:

```json
{
  "operator": "crossover",
  "parent_ids": ["parent_a", "parent_b"],
  "strategy_parent_id": "parent_a",
  "previous_code_parent_id": "parent_b",
  "generation_prompt_parent_id": "parent_a"
}
```

For crossover plus mutation:

```json
{
  "operator": "crossover+mutation",
  "mutation_type": "strategy"
}
```

------

# 25. Timing Contract

Each candidate must persist timestamps and durations for every pipeline stage.

Recommended `timing.json`:

```json
{
  "candidate_started_at": "",
  "candidate_finished_at": "",
  "total_duration_seconds": 0.0,

  "selection_duration_seconds": 0.0,
  "crossover_duration_seconds": 0.0,

  "reflection_llm": {
    "started_at": null,
    "finished_at": null,
    "duration_seconds": null,
    "attempts": []
  },

  "rewrite_llm": {
    "started_at": null,
    "finished_at": null,
    "duration_seconds": null,
    "attempts": []
  },

  "generation_llm": {
    "started_at": "",
    "finished_at": "",
    "duration_seconds": 0.0,
    "attempts": []
  },

  "validation_duration_seconds": 0.0,
  "compilation_duration_seconds": 0.0,
  "integration_duration_seconds": 0.0,

  "strategy_alignment_llm": {
    "started_at": null,
    "finished_at": null,
    "duration_seconds": null,
    "attempts": []
  },

  "matches_total_duration_seconds": 0.0,
  "match_durations_seconds": []
}
```

Each LLM attempt should record:

```json
{
  "attempt": 1,
  "started_at": "",
  "finished_at": "",
  "duration_seconds": 0.0,
  "status": "success",
  "error": null
}
```

Use UTC timestamps.

------

# 26. Match Artifact Contract

Each match must use a separate directory:

```text
matches/match_<index>/
```

Required contents:

```text
result.json
replay.xml
round_states/
stdout.txt
stderr.txt
telemetry.json
performance_breakdown.json
timing.json
```

Required match metadata:

```text
candidate_id
match_index
candidate_player
opponent
map
seed
max_cycles
final_tick
winner
player_final_resources
enemy_final_resources
unit_material_trace
return_code
duration_seconds
status
failure_reason
```

------

# 27. Reproducibility Contract

Each run must persist a resolved configuration.

Required fields:

```text
population_size
generation_count
crossover_rate
mutation_rate
mutation selection policy
matches_per_candidate
opponent
map
max_cycles
EA random seed
MicroRTS match seeds
LLM backend
LLM model
LLM temperature
retry policy
prompt version
objective formula version
artifact schema version
Git commit hash
```

Required values:

```text
matches_per_candidate = 10
evaluation_opponents = fixed 10-opponent roster
```

The resolved configuration must reflect actual runtime behavior.

Do not silently override configuration without writing the resolved value.

------

# 28. Required State Transition Examples

## 28.1 Parent Generation

```text
Input:
A1 + B1 + C1

Generated Java:
B2

Evaluated parent state:
A1 + B2 + C1
```

------

## 28.2 Strategy Mutation

```text
Parent:
A1 + B2 + C1

Reflection:
R_strategy

Rewrite:
A2

Child generation input:
A2 + B2 + C1

Generated child Java:
B3

Final child:
A2 + B3 + C1
```

------

## 28.3 Code Mutation

```text
Parent:
A1 + B2 + C1

Reflection:
R_code

Rewrite:
C2

Child generation input:
A1 + B2 + C2

Generated child Java:
B3

Final child:
A1 + B3 + C2
```

------

## 28.4 Crossover

```text
Parent 1:
A1 + B1 + C1

Parent 2:
A2 + B2 + C2

Uniform crossover result:
A1 + B2 + C1

Generated child Java:
B3

Final child:
A1 + B3 + C1
```

------

# 29. Implementation Invariants

The implementation must always satisfy:

1. EAGLE evolves a three-component genotype.
2. The genotype contains strategy prompt, previous generated Java, and generation prompt.
3. The LLM generates a complete `CandidateAgent.java`.
4. The local LLM is not required to preserve a fixed internal function architecture.
5. Uniform crossover selects all three components independently.
6. Crossover uses the parent’s latest generated and evaluated Java.
7. Strategy Mutation uses Reflection followed by Strategy Prompt Rewrite.
8. Code Mutation uses Reflection followed by Generation Prompt Rewrite.
9. Mutation never directly edits Java.
10. Every offspring passes through Java Generation after crossover and optional mutation.
11. The generated Java is compiled once.
12. The same compiled Java is evaluated for 10 matches.
13. The Java is not regenerated between matches.
14. The opponents are the fixed 10-opponent Evolution Evaluation roster.
15. The optimizer uses exactly two objectives: `game_performance` and `code_quality`.
16. All failed evaluations receive `game_performance = -1000`.
17. `code_quality` distinguishes failure stages.
18. Compilation failure must score below integration failure.
19. Integration failure must score below runtime failure.
20. Runtime failure must score below successful execution.
21. Function Score evaluates capabilities, not fixed method names.
22. Strategy Alignment is evaluated on a 0–10 scale.
23. Both Mutation LLM responses are persisted.
24. The final child-generation LLM response is persisted.
25. All LLM retries and stage timings are persisted.
26. Component-level crossover provenance is persisted.
27. The child’s next-generation `previous_code` is its newly generated Java.
28. Resolved runtime configuration must match actual execution.
29. Historical compatibility code must not override this contract.
30. Artifact schemas and objective formulas must be explicitly versioned.
31. Generated agents use package `ai.generated`, public class `CandidateAgent`, superclass `AbstractionLayerAI`, both required constructors, and the required `getAction`, `reset`, and `clone` methods.
32. MicroRTS integration executes the seven ordered checks in section 12.1 and starts no evaluation match.
33. Successful `code_quality` uses the selected `+500` base and has range `0` to `610`.

------

# 30. Implementation Priority

Implement in this order:

```text
1. Candidate data model and state transitions
2. Parent generated-Java inheritance
3. Component-level crossover provenance
4. Real two-stage Strategy Mutation
5. Real two-stage Code Mutation
6. Final full-file Java generation
7. Runtime-contract validation
8. Compilation and warning diagnostics
9. MicroRTS integration classification
10. 10-match fixed-roster evaluation
11. Game Performance formula
12. Failure-aware Code Quality
13. Function Capability Score
14. Strategy Alignment evaluator
15. Artifact schema
16. Timing schema
17. Tests
18. Legacy cleanup
```

Do not refactor unrelated modules before these contracts are implemented and tested.
# 31. Post-Evolution Champion Final Test

EAGLE has exactly two evaluation contexts. Evolution Evaluation is the ten-match fitness protocol against the fixed roster: pinned TMA, Mayari, COAC, five vendored basic agents, and two historical-self agents. Final Test is a post-run, gameplay-only comparison over selected completed-run candidates; it never changes an evolutionary objective.

Final-test candidate selection uses completed-run evolution artifacts before matches begin. It reuses canonical generated Java without LLM, regeneration, repair, Reflection, Rewrite, mutation, crossover, or NSGA-II calls; compiles each source once; tests deterministic vendored maps/seeds on both player sides; never substitutes an unavailable champion; and writes a separate versioned `final_tests/<final_test_id>/` tree.

There is no training/validation/test split and no validation selection stage. Compilation, integration, and champion class-load checks are operational prerequisites only. Final-test results cannot flow back to selection, variation, fitness, or survivor selection. A formal final test succeeds only when every configured match completes validly.

Final-test competition score is distinct from evolution `game_performance`. The detailed opponent pins, selectors, schedule, artifacts, formulas, licensing status, and reproduction commands are owned by [`evaluation/final_test.md`](evaluation/final_test.md).
