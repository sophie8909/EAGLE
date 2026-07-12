# Java Agent Pipeline

Each candidate evolves one complete strategy: the overall strategy description, the complete six-function behavior collection, and generation guidance. EAGLE requests and replaces all behavior bodies together.

## Repository-owned Java sources

The source structure lives in `eagle/java_templates/`:

- `CandidateAgent.java` is the fixed, manually editable MicroRTS wrapper. It owns AI lifecycle methods, context creation, calls to every predefined behavior method, action assembly, fallback handling, clone/reset, and framework parameters. Candidate creation copies this file without changing it.
- `CandidateBehaviors.java` is the evolvable behavior template. It owns the fixed class, imports, signatures, and one unique `/* EAGLE_BODY:<function_name> */` marker for each required behavior.

Python does not own either Java class skeleton. It validates the checked-in templates, validates the backend's JSON function set and bodies, replaces the markers, rejects unresolved markers, and writes the rendered behavior source. The unrendered behavior template is never compiled.

Changing a behavior signature requires coordinated edits to both Java templates and `eagle/module_contract.py` (plus `MODULE_NAMES` in `eagle/candidate.py` when a function is added or removed).

## Generation boundary

The backend returns only one JSON object containing every fixed function body:

```json
{"functions":{"controller":"...","economy":"...","combat":"...","expansion":"...","target_selection":"...","path_selection":"..."}}
```

Missing, duplicate-template, unknown, empty, fenced, or scope-escaping functions fail before compilation.

## Runtime and artifacts

Both rendered sources compile together in one `javac` invocation. Candidate class output directories isolate the stable `ai.generated.CandidateAgent` class name. Successful candidates proceed to MicroRTS evaluation.

Each candidate artifact directory contains at least:

```text
candidate/
  CandidateAgent.java
  CandidateBehaviors.java
  prompt.json
  compile.log
  result.json
```

Detailed metrics and debug artifacts are retained alongside these files.

## Code-quality objective

NSGA-II maximizes `game_performance` and `code_quality`. Code quality is the sum of the actual `javac` compilation score, the proportional predefined-function validity score, and the 0�V10 strategy-consistency judge score. Each component, compiler warning/error counts, per-function validation, unknown generated names, judge reasoning, and judge infrastructure errors are stored separately in candidate artifacts and reflection feedback. A compilation failure prevents the MicroRTS match but does not overwrite function or strategy-consistency scores.
