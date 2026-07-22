"""Lazy run browser and candidate artifact inspector."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from nicegui import ui

from eagle_ui.components.run_selector import create_run_selector
from eagle_ui.controllers.artifact_controller import ArtifactController
from eagle_ui.theme import BUTTON_CLASS, CARD_CLASS, INPUT_CLASS, TEXTAREA_CLASS


def build_candidate_view(controller: ArtifactController) -> None:
    selected_run: Path | None = None
    run_select = create_run_selector()
    candidate_select = ui.select({}, label="Candidate").classes(f"{INPUT_CLASS} w-full")
    run_summary = ui.label("Select a run")
    candidate_summary = ui.label("Select a candidate")
    details = ui.tabs()
    with details:
        prompt_tab = ui.tab("Prompts")
        java_tab = ui.tab("Java")
        diagnostics_tab = ui.tab("Diagnostics")
        matches_tab = ui.tab("Matches")
        final_tests_tab = ui.tab("Final Tests")
        timing_tab = ui.tab("Timing & paths")
    with ui.tab_panels(details, value=prompt_tab).classes("w-full"):
        with ui.tab_panel(prompt_tab):
            strategy = _viewer("Strategy prompt")
            rewritten = _viewer("Rewritten / generation prompt")
            raw = _viewer("Raw LLM response")
        with ui.tab_panel(java_tab):
            extracted = _viewer("Extracted code", 320)
            assembled = _viewer("Assembled code", 420)
        with ui.tab_panel(diagnostics_tab):
            diagnostics = _viewer("Compilation, validation, integration, and failure", 520)
        with ui.tab_panel(matches_tab):
            matches = _viewer("Match results", 520)
        with ui.tab_panel(final_tests_tab):
            final_tests = _viewer("Saved final-test summaries", 520)
        with ui.tab_panel(timing_tab):
            timing = _viewer("Timing and artifact paths", 520)

    async def refresh_runs() -> None:
        try:
            runs = await asyncio.to_thread(controller.runs)
        except (OSError, ValueError) as exc:
            ui.notify(f"Cannot scan {controller.runs_dir}: {exc}", type="negative")
            return
        run_select.options = {str(item.path): f"{item.run_id} · {item.status} · {item.candidate_count} candidates" for item in runs}
        run_select.update()

    async def select_run() -> None:
        nonlocal selected_run
        selected_run = Path(str(run_select.value)) if run_select.value else None
        if selected_run is None:
            return
        try:
            records = await asyncio.to_thread(controller.candidates, selected_run)
            summary = next((item for item in await asyncio.to_thread(controller.runs) if item.path == selected_run), None)
        except (OSError, ValueError) as exc:
            ui.notify(f"Cannot open run {selected_run}: {exc}", type="negative")
            return
        candidate_select.options = {
            record.candidate_id: f"g{record.generation} · {record.candidate_id} · {record.status} · {record.operator}"
            for record in records
        }
        candidate_select.update()
        if summary:
            run_summary.set_text(
                f"{summary.run_id} | {summary.status} | generations={summary.generation_count} | "
                f"success={summary.success_count} failure={summary.failure_count} | "
                f"final_tests={summary.final_test_count} tested={summary.final_test_candidate_ids} | config={summary.config_summary}"
            )

    async def select_candidate() -> None:
        if selected_run is None or not candidate_select.value:
            return
        try:
            item = await asyncio.to_thread(controller.candidate, selected_run, str(candidate_select.value))
        except (OSError, ValueError) as exc:
            ui.notify(f"Cannot open candidate {candidate_select.value} in {selected_run}: {exc}", type="negative")
            return
        record = item.record
        candidate_summary.set_text(
            f"generation={record.generation} id={record.candidate_id} parents={record.parent_ids} "
            f"operator={record.operator} status={record.status} objectives={record.objectives}"
        )
        strategy.value = record.strategy_prompt
        rewritten.value = item.rewritten_prompt
        raw.value = item.raw_llm_response
        extracted.value = item.extracted_code
        assembled.value = item.assembled_code or record.generated_java
        diagnostics.value = json.dumps({
            "compilation": item.compilation,
            "validation": item.validation,
            "integration": item.integration,
            "failure": item.failure,
        }, ensure_ascii=False, indent=2)
        matches.value = json.dumps(item.match_results, ensure_ascii=False, indent=2)
        final_tests.value = json.dumps([
            {
                "final_test_id": summary.final_test_id,
                "status": summary.status,
                "formal": summary.formal,
                "selector": summary.selector,
                "completed_matches": summary.completed_matches,
                "expected_matches": summary.expected_matches,
                "candidate": summary.for_candidate(record.candidate_id),
                "artifact_paths": {
                    name: str(path) for name, path in summary.artifact_paths.items()
                },
            }
            for summary in item.final_tests
        ], ensure_ascii=False, indent=2)
        timing.value = json.dumps({
            "timing": item.timing,
            "artifact_paths": {name: str(path) for name, path in item.artifact_paths.items()},
        }, ensure_ascii=False, indent=2)
        for control in (strategy, rewritten, raw, extracted, assembled, diagnostics, matches, final_tests, timing):
            control.update()

    with ui.row().classes("gap-2"):
        ui.button("Refresh runs", on_click=refresh_runs).classes(BUTTON_CLASS)
    run_select.on_value_change(lambda _: select_run())
    candidate_select.on_value_change(lambda _: select_candidate())
    ui.timer(0.1, refresh_runs, once=True)


def _viewer(label: str, height: int = 220):
    return ui.textarea(label).props("readonly").classes(f"{TEXTAREA_CLASS} font-mono w-full h-[{height}px]")
