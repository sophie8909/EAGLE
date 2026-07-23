# EAGLE Architecture Smells

Reviewed after the repository inventory and canonical evaluator consolidation.

| Rank | Issue | Evidence | Status |
|---|---|---|---|
| Critical | None found in the reviewed active paths. | Framework operators and MicroRTS evaluation remain separated. | No active Critical issue identified. |
| High | Historical artifact readers and the LLM endpoint-to-role fallback still preserve transitional formats. | `scripts/analyze_run.py`, `eagle/llm_profiles.py`, and implementation gap G-18. | Deferred until explicit artifact/config migration fixtures are available. |
| Medium | Analysis CLI and shared analysis readers overlap on historical read behavior. | `scripts/analyze_run.py` and `eagle/analysis/records.py`. | Deferred; consolidate behind schema-versioned readers. |
| Medium | GUI execution still owns process orchestration through controllers. | `eagle_ui/controllers/run_controller.py`. | Deferred; direct cause is not smoke/patch accumulation. |
| Low | Vendored MicroRTS contains upstream debug/TODO markers and duplicate benchmark helpers. | `third_party/microrts/**`. | Out of scope; application/vendor boundary preserved. |

The duplicate gameplay evaluator implementations were directly caused by
transitional accumulation and were consolidated in the canonical runtime-path
commit. No new fallback or compatibility layer was introduced.
