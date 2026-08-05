# EAGLE reflection: current implementation state

Audit date: 2026-08-05. This document describes the code that executes in the
repository, plus the stored run runs/20260804_152957_480577. Architecture
documents are used as terminology only; when they disagree with executable
code or artifacts, the executable path and artifact win.

## Executive finding

Reflection is implemented as two LLM paths:

~~~text
Strategy Mutation: Reflection -> Strategy Prompt Rewrite -> Java Generation
Code Mutation:     Reflection -> Generation Prompt Rewrite -> Java Generation
~~~

Evaluation currently produces substantially more evidence than the reflection
LLM reliably sees. GameMetrics contains opponent, map, side, match, score
component, and temporal summaries, and the match directories retain raw results
and telemetry. The mutation handoff copies much of that into a
ReflectionContext, but the prompt builders embed large nested dictionaries and
then truncate_prompt hard-limits the final request to 60,000 characters. In
the real generation-19 code-reflection request, the request is exactly 60,000
characters: it contains the prompt and Java sections, the truncation marker,
and the tail of the runtime match list, while the earlier validation,
compilation, compiler-diagnostic, and integration labels have been removed
from the request (runs/20260804_152957_480577/candidates/b806b9be54cf/mutation/reflector_request.txt; eagle/llm_transport.py:9-29).

Therefore the current system is not “only scalar fitness,” but the LLM does not
receive a dependable structured copy of the rich evaluation envelope. Some
opponent and individual-match detail reaches the request as a nested Python
repr; detailed raw telemetry, process output, and early code diagnostics do
not reliably reach it.

## 1. Reflection entrypoints

| Source | Class/function | Caller | Trigger condition | Mutation operator | Reflects | Candidate population state |
| --- | --- | --- | --- | --- | --- | --- |
| eagle/search.py:55-109 | run_search | CLI/search runtime | Run setup; constructs both mutation objects | strategy_mutation, code_mutation through PromptRewriteMutation | Both, depending on selected object | The evaluated parent population is available to offspring creation |
| eagle/resume.py:26-67 | resume_search | Resume CLI/runtime | Resume has a later generation to produce; constructs both mutation objects | strategy_mutation, code_mutation | Both | Surviving evaluated candidates loaded from the generation snapshot |
| eagle/search.py:288-349 | create_offspring | run_search and resume_search | rng.random() < config.mutation_rate | Chooses strategy or code using choose_mutation | One path per child | New child genotype, before the child’s final Java generation/evaluation |
| eagle/search.py:359-389 | choose_mutation | create_offspring | Failed candidate, failed game, warnings/low capability/alignment, or seeded random policy | Returns code for failure-oriented evidence; otherwise strategy/code policy | Neither itself; selects the reflection path | Failed candidates are eligible because the function explicitly routes failures to Code Mutation |
| eagle/search.py:391-468 | mutation_context_from_candidate | create_offspring | Immediately before PromptRewriteMutation.mutate | Shared context construction | Both | Uses the component-provenance-selected feedback_parent, not an error pool |
| eagle/rewrite.py:197-309 | PromptRewriteMutation.mutate | create_offspring | One mutation was selected | strategy or code | Both through one shared abstraction | Calls one reflection, then one prompt-only rewrite; no Java is directly edited |
| eagle/mutation.py:269-388 | ReflectionStage.run | PromptRewriteMutation.mutate | Every selected mutation path | reflection_type="strategy" or "code" | Strategy or code | Retries validation failures, persists raw response, and returns free-form reflection text |
| eagle/mutation.py:391-477 | build_strategy_reflection_prompt, build_code_reflection_prompt | PromptRewriteMutation.mutate | Before ReflectionStage.run | strategy_mutation or code_mutation | Strategy or code | Assembles the final reflection request from Candidate and ReflectionContext |

The shared abstraction is ReflectionContext/MutationContext in
eagle/mutation.py:35-117. MutationContext is only a compatibility alias;
there is no second reflection implementation. Reflection and Rewrite use the
same backend protocol, but the Reflection stage and Rewrite stage have separate
result records and artifact files (eagle/mutation.py:172-176,
eagle/rewrite.py:37-78).

Successful and failed candidates are both supported as reflection sources.
choose_mutation returns code for a failure stage, failed status, failed game
objective, incomplete match matrix, warnings, low Function Capability, or
low Strategy Alignment (eagle/search.py:359-389). NSGA-II combines parents
and offspring without filtering failures (eagle/selection.py:41-61), so a
failed candidate can remain selectable. There is no separate failed-candidate
reflection entrypoint or historical error-pool sampler.

## 2. Complete data-flow trace

### 2.1 Evaluation artifacts to evaluation result objects

1. evaluate_candidate generates and validates Java, compiles once, runs the
   seven-check integration probe, runs the fixed matrix, computes gameplay
   metrics, and computes Code Quality/Strategy Alignment when the evaluation
   completes (eagle/evaluation.py:260-447).

2. evaluate_matches constructs one MatchSpecification for each configured
   opponent x three maps x three rounds x both candidate sides, then calls
   run_microrts_match (eagle/evaluation.py:727-830; evaluation/match_matrix.py:41-90).
   The current configuration names passive, random, randombias, lightrush,
   heavyrush, workerrush, allibot, mayari, coac, and tma with weights 0.5, 0.5,
   0.5, 1, 1, 1, 2, 2, 2, 2
   (configs/experiments/microrts.yaml:22-55).

3. One invocation returns a MatchResult. It contains status, raw result,
   winner, candidate side, opponent identity, map, seed, final resources,
   hashes, failure category/reason, duration, artifact paths, and optional
   MatchTelemetry/GamePerformanceBreakdown
   (evaluation/runtime_evaluation.py:45-90). MatchResult.to_json_dict can
   include full telemetry and process output, but the higher-level compact path
   does not request those fields (evaluation/runtime_evaluation.py:92-181).

4. compute_game_metrics groups successful results by opponent, derives an
   OpponentResult for each configured opponent, calculates opponent scores,
   weights, aggregate objective, W/D/L, resource/material/survival summaries,
   and compact individual match_summaries
   (evaluation/game_metrics.py:240-391). Each OpponentResult can contain 18
   match scores, P0/P1 averages, map averages, weight, weighted contribution,
   and source information (evaluation/game_metrics.py:394-446).

5. GameMetrics.to_json_dict drops raw_metrics, serializes the typed opponent
   records, and aliases match_summaries to match_results
   (evaluation/game_metrics.py:104-112). A compact match summary includes
   opponent/map/round/seed/side, winner/result, final resources, one
   GamePerformanceBreakdown, and replay/telemetry/summary paths
   (evaluation/game_metrics.py:449-474). It does not include the per-tick
   MatchTickTelemetry objects or raw process output.

### 2.2 Evaluation result to candidate result and persisted artifacts

6. evaluate_candidate builds quality_payload, game_payload, compact match
   results, and reflection_evidence (eagle/evaluation.py:467-505). The
   evidence envelope retains objectives, status/failure, generation raw /
   extracted / assembled source and validation, compact compilation and
   integration results. It does not put the full match list into
   reflection_evidence; the match list remains in candidate.game_eval_result
   and is recovered as a fallback by mutation_context_from_candidate
   (eagle/evaluation.py:479-505, eagle/search.py:391-405).

7. Candidate stores the three genotype fields, generated phenotype, lineage,
   objective dictionaries, failure fields, artifacts, timing, and compact
   metadata (eagle/candidate.py:39-66). Its JSON snapshot deliberately omits
   raw match/telemetry and full mutation envelopes from generic metadata
   (eagle/candidate.py:106-142).

8. write_candidate_artifacts writes the genotype, generation, validation,
   compilation, integration, Strategy Alignment, evaluation JSON, match JSON,
   and mutation files (eagle/artifacts.py:56-104, eagle/artifacts.py:107-207).
   The owning match directories retain raw_result.json, stdout/stderr,
   telemetry, and performance breakdowns through run_microrts_match and
   _finish_match (evaluation/runtime_evaluation.py:184-316,
   evaluation/runtime_evaluation.py:407-543).

### 2.3 Candidate to mutation context

9. mutation_context_from_candidate reads the feedback parent’s
   metadata["reflection_evidence"], then falls back to the candidate’s
   game_eval_result and code_quality_result for the full game/quality
   payloads (eagle/search.py:391-400). It converts raw opponent dictionaries
   into OpponentResult objects using _opponent_result_from_payload
   (eagle/search.py:483-499). That conversion retains ID/name/score/W-D-L,
   resource/unit values, status, and failure, but does not copy weight,
   weighted contribution, expected/completed/missing counts, P0/P1 averages,
   map averages, match scores, or source IDs; the dataclass defaults are used.

10. The same function retains game as game_evidence, match_summary, and
    runtime_result. Therefore the full compact game_payload, including its
    match_results list, is still nested in the context even though the typed
    opponent_results copy is lossy (eagle/search.py:419-452). It also maps
    Code Quality fields into scalar convenience fields and compiler error/warning
    message tuples (eagle/search.py:453-468).

11. ReflectionContext has fields for both gameplay and code-stage evidence,
    including raw generation response, validation, compilation, integration,
    runtime, capability/alignment scores, compiler messages, generation/index,
    parent-adjacent Java, and match summaries (eagle/mutation.py:35-104).
    This is an available in-memory envelope, not a guarantee that every field is
    rendered into a request.

### 2.4 Context to prompt, request, and parsed result

12. Strategy prompt construction uses candidate.strategy_prompt,
    candidate.generated_java or candidate.previous_code, typed opponent
    summaries, a canonical summary, W/D/L, aggregate game score, resources,
    material/survival/temporal/behavior summaries, and the raw match_summary
    dictionary (eagle/mutation.py:391-443). It does not pass Code Quality,
    validation, compilation, integration, generation-response, or reflection
    history fields to the template.

13. Code prompt construction uses strategy/generation prompts, parent Java,
    latest Java, raw generation response, validation, compact compilation and
    integration records, compiler messages, and explicit Code Quality/failure
    scalars. It also embeds the entire gameplay runtime_result dictionary
    inside the code prompt (eagle/mutation.py:446-477).

14. render_prompt substitutes values into the TOML templates. There is no
    separate system message: OpenAICompatibleReflectionBackend.generate sends
    one user message containing the rendered prompt (eagle/prompts.py:23-98,
    eagle/mutation.py:216-239). ReflectionStage.run applies truncate_prompt
    immediately before persistence and transport (eagle/mutation.py:290-302).

15. The backend returns raw text. _validate_reflection only requires non-empty
    text and rejects obvious Java output; ReflectionResult.reflection is the
    stripped free-form response (eagle/mutation.py:313-371,
    eagle/mutation.py:480-485). There is no JSON schema or field-level parsing.

16. PromptRewriteMutation feeds that text to the strategy or code Rewrite
    prompt. _validate_rewritten_prompt rejects empty output, fences, Java,
    JSON-looking output, and labelled prefixes; normalize_prompt then caps the
    rewritten component using max_prompt_chars/max_prompt_lines
    (eagle/rewrite.py:268-305, eagle/rewrite.py:406-418,
    eagle/offspring.py:6-24).

17. _result_candidate changes only strategy_prompt for Strategy Mutation or
    only generation_prompt for Code Mutation. It retains the inherited
    previous_code, stores the reflection/rewrite records in mutation metadata,
    and leaves final Java generation to the shared evaluation path
    (eagle/rewrite.py:311-380). The child’s final generated_java is then
    produced by evaluate_candidate, and the next child uses that evaluated
    phenotype as previous_code (eagle/search.py:314-325,
    eagle/evaluation.py:575-608).

## 3. Exact reflection inputs

The statuses below distinguish what the builder/context can contain from what a
60,000-character request can actually preserve. “Used” means inserted into the
rendered prompt, including as a nested dictionary; it does not mean the LLM can
reliably see it after truncation.

| Information category | Strategy Reflection | Code Reflection | Evidence / qualification |
| --- | --- | --- | --- |
| Candidate prompt content | AVAILABLE AND USED | AVAILABLE AND USED | Strategy prompt is explicit; Code prompt includes strategy and generation prompts (eagle/mutation.py:424-477). |
| Candidate Java code | AVAILABLE AND USED | AVAILABLE AND USED | Parent Java is explicit in both; Code also has latest Java and raw generation response (eagle/mutation.py:394-450). |
| Aggregate fitness | AVAILABLE AND USED | AVAILABLE AND USED | game_performance and code_quality are in objectives/canonical code evidence. |
| Per-objective scores | AVAILABLE AND USED | AVAILABLE AND USED | objectives is nested in both canonical summaries. |
| Per-opponent scores | AVAILABLE AND USED, but the typed duplicate is lossy | AVAILABLE AND USED through nested gameplay runtime data | GameMetrics persists scores; _opponent_result_from_payload drops several opponent fields (evaluation/game_metrics.py:394-446, eagle/search.py:483-499). |
| Per-map scores | AVAILABLE AND USED only in raw nested match_summary; not in typed duplicate | AVAILABLE AND USED only in nested runtime data | map_averages exists in artifacts but is not copied by _opponent_result_from_payload. |
| P0/P1 results | AVAILABLE AND USED in raw match summaries; typed duplicate defaults are wrong/incomplete | AVAILABLE AND USED in nested match summaries | Matrix records include candidate_player; opponent summary computes P0/P1 averages (evaluation/match_matrix.py:26-38, evaluation/game_metrics.py:404-442). |
| Individual match results | AVAILABLE AND USED as compact match_results nested in match_summary, subject to truncation | AVAILABLE AND USED as nested runtime_result, subject to truncation | The real code request contains the tail of match rows, not a complete structured matrix. |
| Win/loss/draw result | AVAILABLE AND USED | AVAILABLE AND USED | Aggregate W/D/L and per-match winner/result are rendered. |
| Raw and weighted values | AVAILABLE AND USED in nested game payload; typed opponent duplicate loses weight fields | AVAILABLE AND USED in nested game payload | opponent raw score, weighted contribution, aggregate weighted numerator, and final objective are produced by GameMetrics (evaluation/game_metrics.py:420-443). |
| Opponent weights | AVAILABLE AND USED in nested rows when retained; not in typed duplicate | Same | Match summaries include opponent_weight; _opponent_result_from_payload does not set weight. |
| Generation-dependent EAGLE weight | AVAILABLE BUT NOT RELIABLY USED | AVAILABLE BUT NOT RELIABLY USED | Context/game artifact has eagle_weight and eagle_reference; builder has no dedicated field, and the observed code request contains no eagle_weight token. |
| Match-level unit/resource/survival components | AVAILABLE AND USED as derived performance/resource/survival summaries; raw per-tick unit counts are not forwarded | Same, nested in runtime result | summarize_match includes performance_breakdown; full ticks live in match telemetry (evaluation/game_metrics.py:449-474, evaluation/game_performance.py:109-136). |
| Unit statistics | AVAILABLE AND USED at aggregate level | AVAILABLE BUT NOT USED as a dedicated input; only capability score and nested quality evidence can carry detail | unit_material_statistics is explicit for strategy; code template has no unit-statistics variable (eagle/mutation.py:424-477). |
| Resource statistics | AVAILABLE AND USED | AVAILABLE AND USED through gameplay runtime data, not as a dedicated code field | Strategy explicitly renders final/resource breakdowns; Code only embeds gameplay as runtime_result. |
| Survival statistics | AVAILABLE AND USED | AVAILABLE AND USED through gameplay runtime data | Strategy explicitly renders survival_statistics; per-match survival is inside match breakdowns. |
| Compile output | AVAILABLE BUT NOT USED | AVAILABLE BUT NOT RELIABLY USED | Strategy builder ignores compilation; Code context removes command, stdout, and stderr from compact compilation evidence, retaining structured diagnostics (eagle/evaluation.py:661-668). The real code request loses the compilation label before transport. |
| Compiler errors | AVAILABLE BUT NOT USED | AVAILABLE AND USED as message list and nested compact diagnostics, subject to truncation | compiler_errors is explicit only in Code prompt (eagle/mutation.py:459-477). |
| Compiler warnings | AVAILABLE BUT NOT USED | AVAILABLE AND USED as message list and nested compact diagnostics, subject to truncation | Same path; successful warning count is in Code Quality. |
| Function implementation coverage | AVAILABLE BUT NOT USED | AVAILABLE AND USED as function_capability_score; detailed capability evidence is only nested in Code Quality data | FunctionCapabilityResult has per-capability scores/evidence (evaluation/function_capability.py:21-64); Code prompt names only the aggregate score directly. |
| Missing functions | NOT AVAILABLE AT THIS STAGE as a dedicated field | AVAILABLE BUT NOT USED as a dedicated field | Validation checks external methods, not a missing-function inventory; capability analysis scores behavior rather than named functions (generation/java_agent_generator.py:172-203, evaluation/function_capability.py:67-130). |
| Invalid functions | AVAILABLE BUT NOT USED through general validation/error text only | AVAILABLE BUT NOT RELIABLY USED through validation/error text; no dedicated inventory | No invalid_functions field exists in ValidationResult or the context. |
| Strategy-alignment score | AVAILABLE BUT NOT USED | AVAILABLE AND USED as scalar strategy_alignment_score | Strategy builder has no Code Quality variables; Code template renders the score (eagle/mutation.py:459-477). |
| Strategy-alignment explanation | AVAILABLE BUT NOT USED | AVAILABLE BUT NOT RELIABLY USED | The reason is persisted in Strategy Alignment/Code Quality artifacts, but the Code template passes only the scalar explicitly; nested quality evidence can be truncated (evaluation/strategy_alignment.py:20-37, eagle/mutation.py:451-477). |
| Runtime failures | AVAILABLE AND USED as aggregate failure fields and nested match rows | AVAILABLE AND USED as runtime result/failure fields, subject to truncation | Failure category/reason are explicit in both canonical contexts; per-match runtime diagnostics are compacted. |
| Generation failures | AVAILABLE BUT NOT USED as detailed generation evidence | AVAILABLE AND USED via raw generation response/validation/failure fields | Strategy does not pass generation_evidence; Code does (eagle/mutation.py:459-477). |
| Failed source code | AVAILABLE AND USED only if it is the parent Java/raw generation content | AVAILABLE AND USED through raw_generation_response, parent_java, and latest_java | Empty/unavailable source is represented by empty strings; no separate failed-source field. |
| Extracted code | AVAILABLE BUT NOT USED | AVAILABLE BUT NOT USED as a dedicated field | It is stored in generation_evidence, but Code prompt does not pass extracted_code separately; Java fields may duplicate the assembled source. |
| Assembled code | AVAILABLE AND USED as parent Java/latest Java | AVAILABLE AND USED as parent/latest Java | latest_child_java/candidate.generated_java are mapped into the prompt. |
| Replay or artifact paths | AVAILABLE AND USED as nested compact match summaries | AVAILABLE AND USED as nested runtime match summaries | Paths, not replay contents, are embedded. Full artifacts remain on disk. |
| Previous reflection history | NOT IMPLEMENTED | NOT IMPLEMENTED | No history field, accumulator, or prior-reflection lookup exists in Candidate, ReflectionContext, or mutation selection. |
| Parent information | AVAILABLE AND USED only as parent Java; IDs/provenance not rendered | AVAILABLE AND USED only as parent Java; IDs/provenance not rendered | Lineage fields exist on Candidate (eagle/candidate.py:43-66) but builders do not insert them. |
| Generation index | AVAILABLE BUT NOT USED | AVAILABLE BUT NOT USED | ReflectionContext.generation/index are populated (eagle/search.py:410-415) but absent from both templates. |
| Mutation operator history | NOT AVAILABLE AT THIS STAGE to the prompt | NOT AVAILABLE AT THIS STAGE to the prompt | Candidate.operator/mutation_type exist, but neither builder renders them; there is no history collection. |

## 4. Exact prompt templates

### 4.1 Transport envelope

There is no system prompt. The effective request is one user message:

~~~text
messages = [{"role": "user", "content": <rendered template>}]
~~~

The Reflection backend adds model/temperature/streaming transport fields but no
system role and no response format (eagle/mutation.py:216-239). The final
rendered prompt is persisted as mutation/reflector_request.txt before the
request (eagle/mutation.py:298-302).

### 4.2 Strategy Reflection

The effective template is config/prompt_templates.toml:3-38:

~~~text
EAGLE Strategy Reflection stage.

Analyze the complete strategy using the evidence below. Return reflection text only.
Do not rewrite either prompt. Do not generate Java, a patch, a diff, or a code block.

Current strategy_prompt:
<candidate.strategy_prompt>

Parent generated_java:
<candidate.generated_java or candidate.previous_code>

Opponent identity: <context.opponent>
Complete 180/198-match matrix summary; aggregate game performance and opponent-level
18-match feedback: <canonical summary containing objectives, status/failure,
game_evidence, opponent_results, scores>
Opponent summaries (one 18-match summary for every configured opponent):
<typed opponent-result list>
Wins: <wins>; draws: <draws>; losses: <losses>
Game performance: <game_performance>
The opponent summary includes per-opponent P0/P1 averages, map averages,
Strongest matchup, Weakest matchup, and Score consistency.
Final player resources: <final_player_resources>
Final enemy resources: <final_enemy_resources>
Final resource difference: <final_resource_difference>
Resource evidence: <resource_breakdown>
Unit material statistics: <unit_material_statistics>
Survival statistics: <survival_statistics>
Round-state summary: <round_state_summary>
Temporal summary: <temporal_summary>
Behavior summary: <behavior_summary>

Compare behaviour across opponents ...
Use the strongest and weakest matchups and score variance/consistency as evidence.
Propose one coherent, concise, implementable revised strategy ...
Focus on strategy only ... The output must remain reflection only.
~~~

The template asks for P0/P1 and map averages even though the typed
_opponent_result_from_payload conversion does not populate those fields. The
raw game_evidence/match_summary nested dictionaries may still contain the
original values.

### 4.3 Code Reflection

The effective template is config/prompt_templates.toml:40-80:

~~~text
EAGLE Code Reflection stage.

Analyze the complete-file generation outcome using the evidence below. Return reflection
text only. Do not rewrite either prompt and do not generate replacement Java, a patch, a
diff, JSON, or a code block.

strategy_prompt:
<candidate.strategy_prompt>

current generation_prompt:
<candidate.generation_prompt>

parent generated_java:
<candidate.generated_java or candidate.previous_code>

latest generated child Java, if available:
<context.latest_child_java or candidate.generated_java>

raw generation response:
<context.raw_generation_response>

source validation result: <context.validation_result>
compilation result: {canonical_reflection_context: ..., compilation: ...}
compiler errors: <list of messages>
compiler warnings: <list of messages>
MicroRTS integration result: <context.integration_result>
runtime result: {canonical_reflection_context: ..., runtime: <full game payload>}
completed-match count: <count>
function capability score: <score>
strategy alignment score: <score>
failure stage: <stage>
failure category: <category>
failure reason: <reason>

Analyze complete-file validity, API/constructor compatibility, diagnostics, runtime or
match behavior, missing capabilities, strategy alignment, and constraints for a later
Generation Prompt Rewrite. Keep the output as reflection only.
~~~

The important implementation detail is that runtime result contains the
gameplay payload, so Code Reflection receives gameplay feedback as well as code
feedback (eagle/mutation.py:451-477).

### 4.4 Prompt Rewrite calls after reflection

Strategy Rewrite is assembled by eagle/rewrite.py:383-391 and the template at
config/prompt_templates.toml:82-104:

~~~text
EAGLE Strategy Prompt Rewrite stage.
Return only the revised strategy_prompt. Do not return analysis, Java, JSON, a patch,
or Markdown fences. Preserve effective strategy elements and make concrete changes
supported by the Reflection.
Original strategy_prompt: <original>
strategy_reflection: <free-form ReflectionResult.reflection>
Parent generated_java: <parent Java>
Game evaluation summary: <context.match_summary or performance_breakdown>
Output only the new strategy prompt.
~~~

Code Rewrite is assembled by eagle/rewrite.py:394-403 and the template at
config/prompt_templates.toml:106-131:

~~~text
EAGLE Generation Prompt Rewrite stage.
Return only the revised generation_prompt for full-file regeneration. Do not return
Java, analysis, JSON, a patch, a diff, or Markdown fences. Preserve valid MicroRTS
constraints, address confirmed failures, remove contradictions, and keep historical
error text bounded.
Original generation_prompt: <original>
code_reflection: <free-form ReflectionResult.reflection>
strategy_prompt: <current strategy>
Parent generated_java: <parent Java>
Code-quality summary: <context.compilation_result or context.static_metrics>
Output only the new generation prompt.
~~~

### 4.5 Size and suffix behavior

truncate_prompt preserves approximately two-thirds of the beginning and one
third of the end, inserting a marker. It does not preserve named sections or
JSON/dictionary boundaries (eagle/llm_transport.py:16-29). The real code
reflection artifact demonstrates the consequence: the head ends in the Java
section, the marker appears at character 39,940, and the tail begins in a
later opponent match row (runs/20260804_152957_480577/candidates/b806b9be54cf/mutation/reflector_request.txt).

## 5. Current game-performance feedback

### Evaluation facts

The active configuration uses the ten requested fixed opponents, three maps,
three rounds, both candidate positions, and 18 matches per opponent
(configs/experiments/microrts.yaml:22-55; eagle/config.py:17-38,
eagle/config.py:249-261). Generation 1 onward adds one
eagle_previous_best opponent; its source candidate and generation are recorded
and its weight is assigned by eagle_opponent_weight
(eagle/search.py:145-164; evaluation/opponent_schedule.py:10-27). The
generation-19 artifact has 198 expected/completed matches and
eagle_weight = 0.992188 (runs/20260804_152957_480577/candidates/b806b9be54cf/evaluation/game_performance.json).

### What reaches the reflection builder/request

| Question | Current answer | Evidence |
| --- | --- | --- |
| Only final weighted game_performance? | No. The context also contains compact per-opponent and per-match summaries, derived components, and temporal summaries. | evaluation/game_metrics.py:322-390; eagle/search.py:419-446 |
| One score per opponent? | Yes. opponent_scores and OpponentResult.score are persisted. | evaluation/game_metrics.py:380-386; artifact evaluation/game_performance.json |
| One score per opponent and map? | Yes in artifacts and nested match_summary, via OpponentResult.map_averages; not reliably in the typed context duplicate. | evaluation/game_metrics.py:406-443; eagle/search.py:483-499 |
| One score per individual match? | Yes as compact match_results/match_summaries in the context and artifact. | evaluation/game_metrics.py:449-474; artifact evaluation/game_performance.json |
| P0/P1-separated results? | Yes in artifacts and nested opponent summaries. The reflection prompt’s typed duplicate loses those values because its converter does not copy p0_average/p1_average. | evaluation/game_metrics.py:404-442; eagle/search.py:483-499 |
| Win/loss values? | Yes, aggregate and per-match. | evaluation/game_metrics.py:356-363, evaluation/game_metrics.py:449-470 |
| Raw and weighted values? | Both exist in evaluation artifacts and nested game payload: raw match score, opponent weighted contribution, aggregate weighted numerator, and final objective. | evaluation/game_metrics.py:420-443; artifact evaluation/game_performance.json |
| Opponent weights? | Yes in artifacts and match summaries. The typed converter does not copy the opponent-level weight. | evaluation/game_metrics.py:434-443; evaluation/game_metrics.py:449-462; eagle/search.py:483-499 |
| Generation-dependent EAGLE weight? | Yes in context/artifacts, but no dedicated prompt field; it is vulnerable to nested-data truncation. | eagle/search.py:487-492; evaluation/opponent_schedule.py:13-27 |
| Match-level unit/resource/survival components? | Derived per-match score components and final resources reach compact summaries. Full per-tick unit/resource traces remain in match telemetry files and are not in the reflection context. | evaluation/game_performance.py:109-136; evaluation/game_metrics.py:449-474; eagle/evaluation.py:648-658 |
| Opponent names? | Yes, both display name and ID in compact summaries. | evaluation/game_metrics.py:451-454 |
| Map names? | Yes, map/map_id in compact summaries. | evaluation/game_metrics.py:455-458 |
| Replay/artifact paths? | Paths only, not replay or telemetry contents. | evaluation/game_metrics.py:471-474; evaluation/runtime_evaluation.py:141-164 |

The current game_performance implementation does not discard the rich
evaluation artifact. The loss occurs at the reflection boundary: typed
opponent conversion drops fields, compact summaries omit raw ticks/process
output, and final prompt truncation is character-based.

## 6. Current code-quality feedback

| Code-quality item | Current implementation and reflection availability |
| --- | --- |
| Compilation success/failure | CompileResult.ok becomes compact compilation evidence and compile_success; Code Reflection receives the compact result and failure stage, subject to truncation (evaluation/compiler.py:35-67, eagle/evaluation.py:661-668, eagle/mutation.py:459-477). |
| Compiler errors | The persisted compiler diagnostic has severity/code/message/file/line/column/raw; the convenience prompt field is only a tuple of messages (evaluation/compiler.py:13-32; eagle/search.py:456-458). The full compact diagnostics are nested, but the observed code request loses the compilation section before it reaches the LLM. |
| Compiler warnings | Same as errors; warning messages/count are available, but compiler stdout/stderr is stripped from the context handoff (eagle/evaluation.py:661-668; evaluation/canonical_code_quality.py:68-90). |
| Function implementation coverage | FunctionCapabilityResult computes five capability scores and evidence from source plus match telemetry; Code Reflection receives the aggregate function_capability_score, with detailed evidence only nested in code_quality_evidence (evaluation/function_capability.py:67-130; eagle/mutation.py:451-477). |
| Missing functions | No dedicated missing-function list is produced. Validation checks required external methods; capability analysis scores observable behavior and does not name required missing methods (generation/java_agent_generator.py:172-203; evaluation/function_capability.py:67-130). |
| Invalid functions | No dedicated invalid-function field. General validation checks, compiler diagnostics, and failure reason are the available substitutes. |
| Strategy-alignment score | Code Reflection receives the scalar 0–10 score. The score is computed only after complete evaluation (eagle/evaluation.py:415-433; eagle/mutation.py:471-476). |
| Strategy-alignment explanation | Persisted in Strategy Alignment result and nested Code Quality, but not a direct Code Reflection template variable; it is not reliable after truncation (evaluation/strategy_alignment.py:20-37, evaluation/strategy_alignment.py:116-173). |
| Runtime errors | Failure stage/category/reason and compact failed-match fields are available. Raw process stdout/stderr and exception traces remain in the match artifact and are not copied into the reflection context (evaluation/runtime_evaluation.py:546-577; eagle/evaluation.py:648-658). |
| Generated-code validation errors | ValidationResult contains passed/failed/blocked checks and reasons. Code Reflection has a source validation result field, but the real 60,000-character request dropped that section (generation/java_agent_generator.py:18-40; artifact fe7a998baee9/mutation/reflector_request.txt). |
| Failed source code | Raw generation, extracted, and assembled source are persisted and Code Reflection can receive raw generation plus parent/latest Java. A failed generation may leave these strings empty (eagle/evaluation.py:493-502; eagle/mutation.py:459-465). |
| Extracted code | Persisted under generation/extracted_candidate.java, but not a distinct Code Reflection field; it is only in generation_evidence and can be absent from the actual request (eagle/artifacts.py:233-256; eagle/mutation.py:459-465). |
| Assembled code | Available as parent/latest Java content and is used. |

The detailed compiler representation is therefore reduced in the direct
convenience path to compile_success, counts, and message tuples, although
structured diagnostics remain in the compact compilation dictionary. It is not
safe to infer from the artifact that the LLM saw those diagnostics: the observed
code-reflection request contains no source validation result, compilation
result, compiler errors, or MicroRTS integration result labels after
truncation.

## 7. Failure and error-pool handling

- Failed candidates are represented in their candidate directories, generation
  snapshots, objective values, failure stage/category/reason, and retained
  partial match artifacts (eagle/evaluation.py:362-395,
  eagle/artifacts.py:164-207).
- runs/<run>/errors.jsonl is created with the run manifest, but no active
  evaluation/reflection code appends candidate failures to it
  (eagle/run_artifacts.py:24-28; rg found no error_pool implementation in
  eagle, evaluation, or generation).
- There is no error-pool data structure, capacity, sampling policy, grouping,
  deduplication, or representative-error selector. Repeated compile/runtime
  errors are retained per candidate/match only.
- Failed candidates can become mutation parents because selection operates over
  the combined population and offspring and does not exclude failed status
  (eagle/selection.py:41-61). choose_mutation routes such feedback to Code
  Mutation (eagle/search.py:359-379).
- The next reflection receives one selected feedback parent’s evidence snapshot,
  not a pool of historical failures (eagle/search.py:327-332,
  eagle/search.py:391-468).
- Compile, validation, generation, integration, runtime, timeout, crash, and
  illegal-action conditions have stage/category fields in their respective
  pipeline code, but they are not normalized into an error-pool taxonomy
  (generation/java_agent_generator.py:113-141, eagle/evaluation.py:369-395,
  evaluation/runtime_evaluation.py:546-577).

## 8. Reflection output usage

### Output form and parsing

Reflection returns free-form text only. It is not JSON, not a rewritten
prompt, and not Java. _validate_reflection performs only non-empty and obvious
Java-marker checks (eagle/mutation.py:480-485). The raw response and parsed
text are both retained in ReflectionResult and mutation artifacts
(eagle/mutation.py:133-169, eagle/artifacts.py:210-231).

Rewrite returns free-form text that is expected to be one prompt component. It
is rejected if it looks like JSON, Java, a fenced block, or a labelled wrapper;
then it is normalized and bounded (eagle/rewrite.py:406-418,
eagle/offspring.py:6-24).

### Component transition

| Component | Strategy Mutation | Code Mutation |
| --- | --- | --- |
| strategy description / strategy_prompt | Reflection text informs Strategy Rewrite; successful Rewrite replaces only strategy_prompt. | Preserved exactly from the pre-mutation child. |
| previous/generated code context / previous_code | Preserved through Rewrite and final generation; final generated phenotype becomes the next generation’s inherited code. | Preserved through Rewrite and final generation; final generated phenotype becomes the next generation’s inherited code. |
| code-generation instructions / generation_prompt | Preserved exactly from the pre-mutation child. | Reflection text informs Generation Prompt Rewrite; successful Rewrite replaces only generation_prompt. |

The reflection itself is not a persisted candidate genotype component. It is
stored in the mutation record and consumed by the immediately following Rewrite
(eagle/rewrite.py:325-351). A failed Reflection or Rewrite returns the child
with the original prompt component and applied:false, but the shared final
Java-generation/evaluation path still handles that child
(eagle/rewrite.py:254-305).

There is no output that is deliberately generated and then ignored between the
reflection and rewrite stages. The reflection is used by Rewrite. The raw
reflection is not used directly as candidate state, which is intentional in the
current component transition. No automatic previous-reflection accumulation or
consolidation is implemented.

## 9. Example reconstructed reflection

### Real run: Code Reflection for candidate b806b9be54cf

This is a real generation-19 mutation from
runs/20260804_152957_480577.

Candidate before Reflection. The mutation record identifies feedback parent
805aba080133, operation code_mutation, and original parent objectives
game_performance=-43.773643, code_quality=604.5
(runs/20260804_152957_480577/candidates/b806b9be54cf/mutation/metadata.json).
The child had parent/component provenance 805aba080133 and inherited its
latest Java in genotype/previous_code.java; its original generation prompt is
retained in mutation/original_generation_prompt.txt. The feedback context
contained 198 completed matches, all ten fixed opponents plus
eagle_previous_best, three maps, three rounds, both sides, opponent scores,
match rows, validation, compilation, integration, Function Capability 100.0,
and Strategy Alignment 4.5 (the source parent context is stored in the same
mutation metadata under evidence).

Actual Reflection request.
mutation/reflector_request.txt is exactly 60,000 characters. Its beginning
contains the Code Reflection instructions, the strategy prompt, the rewritten
generation prompt, and parent/latest Java. Its truncation marker is present at
character 39,940. The tail contains later compact match rows followed by:

~~~text
completed-match count: 198
function capability score: 100.0
strategy alignment score: 4.5
failure stage:
failure category:
failure reason:
~~~

The actual request does not contain the labels source validation result,
compilation result, compiler errors, compiler warnings, or MicroRTS
integration result; those sections were between the retained head and tail.
This is directly observable in
runs/20260804_152957_480577/candidates/b806b9be54cf/mutation/reflector_request.txt.

Reflection response. The real raw response begins:

~~~text
The generated CandidateAgent.java file is syntactically valid and compiles
successfully ...

However, the agent exhibits a critical runtime failure: it consistently results
in timeouts or immediate losses across all map sizes ...
~~~

It then gives four prose hypotheses about idle assignment, applyAutoDefense,
resource management, and state synchronization. The complete response is
runs/20260804_152957_480577/candidates/b806b9be54cf/mutation/reflector_response_raw.txt.

Rewrite and resulting child. The following Rewrite response is persisted in
mutation/rewriter_response_raw.txt and becomes the child’s new
generation_prompt. The child is then generated/evaluated as
b806b9be54cf; its final artifact reports game_performance=-44.044462,
code_quality=602.0, compilation success, and 198 completed matches
(runs/20260804_152957_480577/candidates/b806b9be54cf/individual.json,
evaluation/game_performance.json, evaluation/code_quality.json). Its
strategy_prompt and previous_code remain the inherited components; only
generation_prompt changed before the final Java-generation call
(eagle/rewrite.py:293-305).

This example is important because the stored parent evidence is rich, while the
actual LLM request is not a lossless rendering of it.

## 10. Information-loss findings

| Stage | Information available | Information forwarded | Information lost | Impact |
| --- | --- | --- | --- | --- |
| Match execution | Raw result, stdout/stderr, replay, round states, full telemetry, performance breakdown | MatchResult plus artifact paths | Nothing at the owning artifact boundary; raw evidence is persisted | Rich evidence exists but requires another reader (evaluation/runtime_evaluation.py:407-543). |
| MatchResult -> GameMetrics | Every match and telemetry object | Derived aggregate metrics, opponent summaries, compact match summaries, temporal min/max/average | Raw result payload, process output, per-tick unit/resource records are not in GameMetrics.to_json_dict | Reflection can see score components and paths, not the underlying trace/process diagnosis (evaluation/game_metrics.py:104-112). |
| Opponent payload -> ReflectionContext.opponent_results | Weight, contribution, expected/completed/missing counts, P0/P1/map averages, all match scores, source IDs | ID/name/score/W-D-L/resources/units/status/failure | The converter drops those fields; dataclass defaults replace them | The prompt’s advertised 18-match summary can contain expected_match_count=1, zero completed, empty map averages, and no match scores in the typed duplicate (eagle/search.py:483-499). |
| Evaluation -> reflection_evidence | Full game and quality payloads | Objectives, failure, generation evidence, compact compile/integration | Game/quality/match payloads are not nested in this envelope | Recovery depends on candidate-level game_eval_result/code_quality_result fallback (eagle/evaluation.py:479-505, eagle/search.py:391-400). |
| Full compile result -> context | Command, stdout, stderr, structured diagnostics | Compact result without command/stdout/stderr; convenience messages/counts | Compiler process output and command are not forwarded | Raw javac context is available only on disk; diagnostic messages may be enough for simple failures (eagle/evaluation.py:661-668). |
| Full integration result -> context | Commands, stdout/stderr, ordered seven-check results | Ordered result without commands/stdout/stderr | Probe process output/command | Code Reflection sees status/checks when they survive prompt construction, not raw probe output (eagle/evaluation.py:671-678). |
| Prompt builder -> final Reflection request | Large nested strategy/game/code dictionaries | Rendered Python string | Character-based truncation can remove whole named sections and split dictionaries | The real code request loses validation/compile/integration labels and retains an unstructured match-list tail (eagle/llm_transport.py:16-29; real artifact cited above). |
| Strategy prompt -> Strategy Reflection | Candidate strategy, Java, game summaries | These plus duplicate opponent/game dictionaries | Code-quality and generation-stage detail | Strategy reflection cannot directly distinguish code failure from gameplay weakness. |
| Code prompt -> Code Reflection | Code diagnostics plus gameplay payload | Both are embedded | Section ordering and truncation make early code diagnostics unreliable | Code Reflection can receive gameplay detail while missing the code-stage labels intended to explain it. |
| ReflectionContext -> mutation artifacts in real run | Full mutation_record, including evidence | Direct stage files and full metadata.json | Separate reflection_context.json is not present in the observed production candidate because the direct mutation writer created metadata.json before write_candidate_artifacts could copy the compact record (eagle/rewrite.py:360-371, artifact file listing) | The exact evidence is recoverable from metadata.json, but the documented standalone context file is not guaranteed by this path. |

## 11. Main limitations

1. The 60,000-character truncation is not section-aware. In the real code
   reflection request it removed source validation, compilation, compiler error/
   warning, and integration labels while retaining later gameplay rows. This is
   the strongest evidence that available context is insufficient
   (eagle/llm_transport.py:16-29; real artifact in section 9).

2. Rich match telemetry is artifact-only. Reflection receives derived
   per-match scores, final resources, survival/material components, and temporal
   extrema, but not the raw per-tick unit/resource traces, scoreboard details,
   stdout/stderr, or replay content (evaluation/game_performance.py:109-136,
   evaluation/game_metrics.py:449-474).

3. Opponent detail is duplicated through two paths with different fidelity.
   The persisted OpponentResult is rich, while _opponent_result_from_payload
   drops weights, P0/P1 averages, map averages, match scores, and completion
   counts. The raw nested game payload can preserve them, but it is large and
   unstructured (eagle/search.py:483-499).

4. Code Reflection is gameplay-contaminated and strategy Reflection is code-
   diagnostic-blind. Code Reflection embeds the entire gameplay result under
   runtime_result; Strategy Reflection does not render Code Quality or stage
   diagnostics (eagle/mutation.py:391-477).

5. Compiler and integration diagnostics are compacted before reflection.
   Structured diagnostics remain in artifacts and compact JSON, but command,
   stdout, stderr, and raw probe output are explicitly removed from the context
   (eagle/evaluation.py:648-678).

6. There is no explicit parent/evolution comparison. Parent Java is passed,
   but parent objective values, generation index, previous champion comparison,
   and component-level mutation history are not dedicated prompt fields
   (eagle/search.py:410-468; eagle/mutation.py:424-477).

7. There is no error pool. A failed candidate contributes only its own
   selected evidence to the next mutation; repeated errors are not grouped,
   deduplicated, or sampled (eagle/search.py:359-468).

8. Dynamic opponent weighting is not presented as a stable top-level input. It
   exists in evaluation artifacts and nested payloads, but the prompt has no
   dedicated field and the observed code request retained no eagle_weight
   token.

9. Previous reflection advice is not modeled as history. There is no
   consolidation mechanism or reflection-history field. The current generation
   prompt may contain text returned by an earlier Rewrite because that text is
   now part of the genotype, but that is model-produced prompt content, not a
   structured reflection history (eagle/candidate.py:39-66,
   eagle/rewrite.py:293-305).

The repository does not support the stronger claim that reflection receives
only final weighted game_performance; the current limitation is that rich
data is inconsistently normalized, nested, and truncated before transport.

## 12. Recommended reflection context schema

This is a proposal only; no behavior is changed here. It reuses existing
evaluation ownership and keeps the envelope bounded.

| Group | Minimal proposed fields | Availability |
| --- | --- | --- |
| candidate_summary | candidate_id, generation, status, failure_stage/category/reason, strategy_prompt, generation_prompt, parent_ids, operator, mutation_type, previous_code_sha256, generated_java_sha256 | Already available except hashes must be selected from existing source/class hash helpers; prompt fields and lineage are on Candidate (eagle/candidate.py:39-66). |
| aggregate_objectives | game_performance, code_quality, completed_match_count, expected_match_count, wins, draws, losses, win_rate, objective_formula_version | Already available in GameMetrics, Code Quality, and objectives (eagle/evaluation.py:443-475). |
| opponent_results | One row per opponent: opponent_id/name, weight, raw_score, weighted_contribution, score, W/D/L, p0_average, p1_average, map_averages, completed/missing, source_candidate_id/generation | Already available in GameMetrics/artifacts; requires minor plumbing to pass the original dictionaries instead of the lossy converter (evaluation/game_metrics.py:394-446). |
| match_results | Bounded rows: opponent, map, round, seed, candidate side, winner/result, final tick, performance components, final resources, artifact paths; optionally top/bottom rows rather than all 198 | Already available as compact match_summaries; requires minor plumbing for deterministic selection/budgeting (evaluation/game_metrics.py:449-474). |
| gameplay_diagnostics | Aggregate material/resource/survival stats, temporal extrema, capability runtime evidence, and explicit failed-match categories; no raw telemetry by default | Already available in derived metrics and capability result; requires minor plumbing to select compact fields (evaluation/game_metrics.py:341-379, evaluation/function_capability.py:133-168). |
| code_diagnostics | Validation checks, compile status/counts, structured compiler diagnostics, integration checks, runtime failure category/reason, Function Capability breakdown, Strategy Alignment score/reason | Already available in stage artifacts and quality payloads; requires minor plumbing to select and format them (eagle/artifacts.py:63-92, evaluation/canonical_code_quality.py:34-65). |
| evolution_context | Feedback-parent ID/objectives, parent-vs-child objective delta when known, generation index, eagle_previous_best ID/score/weight, component provenance | Already available in lineage, context, and GameMetrics.eagle_reference; requires minor plumbing to expose it to prompts (eagle/search.py:410-468, eagle/evaluation.py:487-492). |
| reflection_history | Bounded prior reflection/rewrite summaries with stage/status and no raw unbounded accumulation | Not implemented; requires new persistence/plumbing. No new evaluation data is required, but a new history retention rule is required. |

For Strategy Reflection, the minimal view should select candidate_summary,
aggregate_objectives, opponent_results, bounded match_results,
gameplay_diagnostics, and evolution_context, plus parent Java. For Code
Reflection, it should select candidate_summary, aggregate_objectives,
code_diagnostics, a small gameplay diagnostic view, and parent/latest/generated
source. This separation is compatible with the current evaluate_candidate
ownership and does not require recomputing fitness.

## 13. Recommended next refactor

Do not change this task’s implementation. The least-code follow-up is:

1. At the existing evaluate_candidate handoff, build one bounded structured
   reflection envelope from the already-produced GameMetrics, Code Quality,
   generation, compilation, integration, and failure objects. Do not reread or
   reparse match artifacts there.

2. Preserve the current evaluation ownership and Candidate state transition,
   but expose two small views from that envelope: a gameplay-oriented Strategy
   view and a code/failure-oriented Code view. Keep the original full artifact
   writers as the lossless source of detailed evidence.

3. Keep data collection separate from formatting. Have the existing two prompt
   builders render named structured sections with explicit budgets, then apply
   truncation at section/row boundaries rather than on the final arbitrary
   string. The transport abstraction can remain unchanged.

4. Keep ReflectionStage, PromptRewriteStage, and PromptRewriteMutation
   separate. Do not create a giant reflection utility module: evaluation should
   own evidence, a small context mapper should own bounded selection, and each
   builder should own only its prompt shape. Preserve Strategy Mutation’s
   strategy-only state change and Code Mutation’s generation-prompt-only state
   change (eagle/rewrite.py:293-305).

This plan adds plumbing at the existing boundary, avoids duplicate artifact
parsing, separates strategy and code evidence, and leaves fitness/evaluation
behavior unchanged.
