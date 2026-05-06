"""Native desktop GUI for configuring, launching, and monitoring EAGLE runs."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox, simpledialog
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from eagle.eval.microrts.state_generator import StateGenerator
from eagle.utils.component_pool import ComponentPool


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "configs" / "evolution"
EXPERIMENT_DIR = ROOT / "configs" / "experiments"
LOG_DIR = ROOT / "logs" / "eagle"
DEFAULT_CONFIG = CONFIG_DIR / "default.json"
APPLICATION_CHOICES = ("microrts",)
ALGORITHM_CHOICES = ("round_ga", "round_nsga2")
EVALUATOR_CHOICES = ("round",)
ROUND_ALGORITHMS = {"round_ga", "round_nsga2"}
GA_ALGORITHMS = {"round_ga"}
SURROGATE_PATH_LINES = (
    "eaglePolicy.java: reusable fixed policy template -> ai.abstraction.eaglePolicy",
    "eagleJava.java: generated Java with the same policy behavior -> ai.abstraction.eagleJava",
)


class EagleDesktopApp:
    """Tkinter application for the native EAGLE desktop workflow."""

    def __init__(self, root: Tk) -> None:
        """Create the desktop window and bind periodic refreshes."""
        self.root = root
        self.root.title("EAGLE Desktop")
        self.root.geometry("1220x820")
        self.root.minsize(1020, 680)

        self.process: subprocess.Popen | None = None
        self.process_log_path: Path | None = None
        self.generated_config_path: Path | None = None

        self.base_config_path = StringVar(value=str(DEFAULT_CONFIG))
        self.config_name = StringVar(value="gui_evolution")
        self.component_source_path = StringVar(value="")
        self.component_runtime_path = StringVar(value="")
        self.loaded_component_path: Path | None = None
        self.component_payload: dict[str, Any] = {}
        self.component_prompt_selection: dict[str, int] = {}
        self.static_component_keys: set[str] = set(ComponentPool.DEFAULT_NON_EVOLVING_COMPONENT_KEYS)
        self.component_category = StringVar(value="")
        self.component_candidate = StringVar(value="0")
        self.component_status = StringVar(value="No component loaded")
        self.training_example_unit = StringVar(value="")
        self.training_example_command = StringVar(value="harvest")
        self.training_example_current_move = StringVar(value="Select a coordinate and command to assemble one move.")
        self.training_example_sample_count = StringVar(value="random 0-4")
        self.training_example_units: list[dict[str, Any]] = []
        self.selected_run = StringVar(value="")
        self.status = StringVar(value="Ready")

        self.application = StringVar(value="microrts")
        self.algorithm = StringVar(value="round_nsga2")
        self.evaluator = StringVar(value="round")
        self.population_size = StringVar(value="10")
        self.num_generations = StringVar(value="50")
        self.run_time_per_game_sec = StringVar(value="500")
        self.real_eval_rate = StringVar(value="0.25")
        self.final_test_max_front = StringVar(value="1")
        self.selection_method = StringVar(value="random")
        self.tournament_size = StringVar(value="3")
        self.crossover = StringVar(value="uniform")
        self.crossover_repair_enabled = BooleanVar(value=True)
        self.enable_reflection_operator = BooleanVar(value=True)
        self.skip_final_test = BooleanVar(value=False)
        self.quick_run = BooleanVar(value=False)
        self.opponents_text = StringVar(value="ai.abstraction.LightRush, ai.abstraction.HeavyRush")
        self.objective_targets: list[str] = ["ai.abstraction.LightRush", "ai.abstraction.HeavyRush"]
        self.single_objective_target = StringVar(value="ai.abstraction.LightRush")
        self.objective_detail = StringVar(value="Select an objective target to inspect its calculation.")

        self.operator_weights = {
            "crossover": StringVar(value="0.7"),
            "mutation": StringVar(value="0.2"),
            "reflection": StringVar(value="0.1"),
        }
        self.mutation_weights = {
            "pool_replacement": StringVar(value="0.4"),
            "identity_preserving_rewrite": StringVar(value="0.35"),
            "identity_shift_rewrite": StringVar(value="0.25"),
            "bitmask_flip": StringVar(value="0.0"),
        }

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self._build_component_tab()
        self._build_flow_tab()
        self._build_run_tab()
        self._build_analysis_tab()
        self._build_prompt_tab()

        self.load_base_config_into_form()
        self.refresh_runs()
        self._schedule_refresh()

    def _build_component_tab(self) -> None:
        """Build controls for selecting, editing, and rendering component JSON files."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Components")
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(5, weight=1)

        ttk.Label(tab, text="Base config").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(tab, textvariable=self.base_config_path).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Button(tab, text="Browse", command=self.browse_base_config).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(tab, text="Load", command=self.load_base_config_into_form).grid(row=0, column=3, padx=(8, 0))

        ttk.Label(tab, text="Initial component.json").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(tab, textvariable=self.component_source_path).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(tab, text="Browse", command=self.browse_component).grid(row=1, column=2, padx=(8, 0))
        ttk.Button(tab, text="Import", command=self.import_component).grid(row=1, column=3, padx=(8, 0))

        ttk.Label(tab, text="Runtime component path").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(tab, textvariable=self.component_runtime_path).grid(row=2, column=1, columnspan=3, sticky="ew")

        ttk.Label(tab, textvariable=self.component_status).grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))

        workspace = ttk.PanedWindow(tab, orient="horizontal")
        workspace.grid(row=5, column=0, columnspan=4, sticky="nsew", pady=(12, 0))

        editor = ttk.LabelFrame(workspace, text="Component Editor", padding=8)
        editor.columnconfigure(1, weight=1)
        editor.rowconfigure(4, weight=1)
        workspace.add(editor, weight=1)

        ttk.Label(editor, text="Component").grid(row=0, column=0, sticky="w", pady=4)
        self.component_category_combo = ttk.Combobox(
            editor,
            textvariable=self.component_category,
            state="readonly",
            values=(),
        )
        self.component_category_combo.grid(row=0, column=1, sticky="ew", pady=4)
        self.component_category_combo.bind("<<ComboboxSelected>>", self.on_component_category_selected)

        ttk.Label(editor, text="Candidate").grid(row=1, column=0, sticky="w", pady=4)
        self.component_candidate_combo = ttk.Combobox(
            editor,
            textvariable=self.component_candidate,
            state="readonly",
            values=(),
            width=12,
        )
        self.component_candidate_combo.grid(row=1, column=1, sticky="w", pady=4)
        self.component_candidate_combo.bind("<<ComboboxSelected>>", self.on_component_candidate_selected)

        actions = ttk.Frame(editor)
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        ttk.Button(actions, text="Use in prompt", command=self.use_component_in_prompt).pack(side="left")
        ttk.Button(actions, text="Apply edit", command=self.apply_component_edit).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Add component", command=self.add_component_category).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Delete component", command=self.delete_component_category).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Add candidate", command=self.add_component_candidate).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Delete candidate", command=self.delete_component_candidate).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Save JSON", command=self.save_component_json).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Save as experiment", command=self.save_component_json_as).pack(side="left", padx=(8, 0))

        move_builder = ttk.LabelFrame(editor, text="Move Builder", padding=8)
        move_builder.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        move_builder.columnconfigure(1, weight=0)
        move_builder.columnconfigure(3, weight=0)
        move_builder.columnconfigure(4, weight=1)

        ttk.Button(move_builder, text="Random state", command=self.generate_training_example_state).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(move_builder, text="Refresh units", command=self.refresh_training_example_units).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        ttk.Label(move_builder, text="Unit").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.training_example_unit_combo = ttk.Combobox(
            move_builder,
            textvariable=self.training_example_unit,
            state="readonly",
            values=(),
            width=10,
        )
        self.training_example_unit_combo.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
        self.training_example_unit_combo.bind("<<ComboboxSelected>>", self.update_training_example_move_preview)

        ttk.Label(move_builder, text="Command").grid(row=1, column=2, sticky="w", padx=(16, 0), pady=(8, 0))
        self.training_example_command_combo = ttk.Combobox(
            move_builder,
            textvariable=self.training_example_command,
            state="readonly",
            values=(),
            width=18,
        )
        self.training_example_command_combo.grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(8, 0))
        self.training_example_command_combo.bind("<<ComboboxSelected>>", self.update_training_example_move_preview)

        ttk.Button(move_builder, text="Append move", command=self.append_training_example_move).grid(
            row=1, column=4, sticky="w", padx=(12, 0), pady=(8, 0)
        )
        ttk.Label(
            move_builder,
            textvariable=self.training_example_current_move,
            wraplength=640,
            justify="left",
        ).grid(row=2, column=0, columnspan=5, sticky="ew", pady=(8, 0))

        self.component_editor = ScrolledText(editor, wrap="word", height=18)
        self.component_editor.grid(row=4, column=0, columnspan=2, sticky="nsew")

        preview = ttk.LabelFrame(workspace, text="Prompt Builder", padding=8)
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)
        preview.rowconfigure(3, weight=1)
        workspace.add(preview, weight=1)

        self.component_selection_table = ttk.Treeview(
            preview,
            columns=("component", "static", "candidate", "lines"),
            show="headings",
            selectmode="browse",
            height=9,
        )
        self.component_selection_table.heading("component", text="Component")
        self.component_selection_table.heading("static", text="Static")
        self.component_selection_table.heading("candidate", text="Candidate")
        self.component_selection_table.heading("lines", text="Lines")
        self.component_selection_table.column("component", width=190, anchor="w")
        self.component_selection_table.column("static", width=70, anchor="center")
        self.component_selection_table.column("candidate", width=90, anchor="center")
        self.component_selection_table.column("lines", width=70, anchor="center")
        self.component_selection_table.grid(row=0, column=0, sticky="nsew")
        self.component_selection_table.bind("<<TreeviewSelect>>", self.on_component_prompt_row_selected)

        builder_actions = ttk.Frame(preview)
        builder_actions.grid(row=1, column=0, sticky="ew", pady=8)
        ttk.Button(builder_actions, text="Render selected prompt", command=self.render_selected_component_prompt).pack(
            side="left"
        )
        ttk.Button(builder_actions, text="Reset to candidate 0", command=self.reset_component_prompt_selection).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(builder_actions, text="Toggle static", command=self.toggle_selected_static_component).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(builder_actions, text="Examples").pack(side="left", padx=(16, 4))
        self.training_example_sample_count_combo = ttk.Combobox(
            builder_actions,
            textvariable=self.training_example_sample_count,
            state="readonly",
            values=("random 0-4", "0", "1", "2", "3", "4"),
            width=12,
        )
        self.training_example_sample_count_combo.pack(side="left")
        self.training_example_sample_count_combo.bind("<<ComboboxSelected>>", self.on_training_example_sample_count_selected)

        ttk.Label(preview, text="Rendered prompt").grid(row=2, column=0, sticky="w")
        self.component_prompt_output = ScrolledText(preview, wrap="word", height=14)
        self.component_prompt_output.grid(row=3, column=0, sticky="nsew", pady=(4, 0))

    def _build_flow_tab(self) -> None:
        """Build algorithm, operator, and flow controls."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Algorithm")
        for column in (1, 3):
            tab.columnconfigure(column, weight=1)

        self._labeled_combo(tab, "Application", self.application, APPLICATION_CHOICES, 0, 0)
        self._labeled_combo(tab, "Evaluator", self.evaluator, EVALUATOR_CHOICES, 0, 2)
        algorithm_combo = self._labeled_combo(tab, "Algorithm", self.algorithm, ALGORITHM_CHOICES, 1, 0)
        algorithm_combo.bind("<<ComboboxSelected>>", self.on_algorithm_selected)
        self._labeled_entry(tab, "Config name", self.config_name, 1, 2)
        self._labeled_entry(tab, "Population size", self.population_size, 2, 0)
        self._labeled_entry(tab, "Generations", self.num_generations, 2, 2)
        self._labeled_entry(tab, "Game seconds", self.run_time_per_game_sec, 3, 0)
        self._labeled_entry(tab, "Real eval rate", self.real_eval_rate, 3, 2)
        self._labeled_entry(tab, "Final-test max front", self.final_test_max_front, 4, 0)
        self._labeled_combo(tab, "Parent selection", self.selection_method, ("random", "tournament"), 5, 0)
        self._labeled_entry(tab, "Tournament size", self.tournament_size, 5, 2)
        self._labeled_combo(tab, "Crossover", self.crossover, ("uniform",), 6, 0)
        ttk.Checkbutton(tab, text="Crossover repair", variable=self.crossover_repair_enabled).grid(
            row=6, column=2, sticky="w", pady=4
        )
        ttk.Checkbutton(tab, text="Enable reflection operator", variable=self.enable_reflection_operator).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=4
        )
        ttk.Checkbutton(tab, text="Quick run override", variable=self.quick_run).grid(
            row=7, column=2, sticky="w", pady=4
        )
        ttk.Checkbutton(tab, text="Skip final test", variable=self.skip_final_test).grid(
            row=7, column=3, sticky="w", pady=4
        )

        ttk.Label(tab, text="Operator probabilities").grid(row=8, column=0, sticky="w", pady=(14, 4))
        self._labeled_entry(tab, "crossover", self.operator_weights["crossover"], 9, 0)
        self._labeled_entry(tab, "mutation", self.operator_weights["mutation"], 9, 2)
        self._labeled_entry(tab, "reflection", self.operator_weights["reflection"], 10, 0)

        ttk.Label(tab, text="Mutation mode weights").grid(row=11, column=0, sticky="w", pady=(14, 4))
        self._labeled_entry(tab, "pool replacement", self.mutation_weights["pool_replacement"], 12, 0)
        self._labeled_entry(tab, "identity preserving", self.mutation_weights["identity_preserving_rewrite"], 12, 2)
        self._labeled_entry(tab, "identity shift", self.mutation_weights["identity_shift_rewrite"], 13, 0)
        self._labeled_entry(tab, "bitmask flip", self.mutation_weights["bitmask_flip"], 13, 2)

        objective_frame = ttk.LabelFrame(tab, text="Objectives", padding=8)
        objective_frame.grid(row=14, column=0, columnspan=4, sticky="nsew", pady=(14, 4))
        objective_frame.columnconfigure(0, weight=1)
        objective_frame.columnconfigure(1, weight=1)
        objective_frame.rowconfigure(0, weight=1)

        self.objective_table = ttk.Treeview(
            objective_frame,
            columns=("target", "objective", "calculation"),
            show="headings",
            selectmode="browse",
            height=5,
        )
        self.objective_table.heading("target", text="Target opponent")
        self.objective_table.heading("objective", text="Objective key")
        self.objective_table.heading("calculation", text="Calculation")
        self.objective_table.column("target", width=240, anchor="w")
        self.objective_table.column("objective", width=130, anchor="w")
        self.objective_table.column("calculation", width=420, anchor="w")
        self.objective_table.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.objective_table.bind("<<TreeviewSelect>>", self.on_objective_selected)

        objective_actions = ttk.Frame(objective_frame)
        objective_actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(objective_actions, text="Add target", command=self.add_objective_target).pack(side="left")
        ttk.Button(objective_actions, text="Delete target", command=self.delete_objective_target).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(objective_actions, text="Use selected for single objective", command=self.use_selected_single_objective).pack(
            side="left", padx=(8, 0)
        )

        ttk.Label(objective_frame, textvariable=self.objective_detail, wraplength=760, justify="left").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )

        surrogate_frame = ttk.LabelFrame(tab, text="Surrogate Paths", padding=8)
        surrogate_frame.grid(row=15, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        for index, line in enumerate(SURROGATE_PATH_LINES):
            ttk.Label(surrogate_frame, text=line).grid(row=index, column=0, sticky="w")

        actions = ttk.Frame(tab)
        actions.grid(row=16, column=0, columnspan=4, sticky="ew", pady=(16, 0))
        ttk.Button(actions, text="Validate settings", command=self.validate_settings).pack(side="left")
        ttk.Button(actions, text="Save generated config", command=self.save_generated_config).pack(side="left", padx=(8, 0))

    def _build_run_tab(self) -> None:
        """Build process launch and log controls."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Run")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(tab)
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Button(toolbar, text="Start experiment", command=self.start_experiment).pack(side="left")
        ttk.Button(toolbar, text="Stop process", command=self.stop_process).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="Refresh", command=self.refresh_all_views).pack(side="left", padx=(8, 0))
        ttk.Label(toolbar, textvariable=self.status).pack(side="left", padx=(16, 0))

        self.generated_config_label = StringVar(value="Generated config: none")
        ttk.Label(tab, textvariable=self.generated_config_label).grid(row=1, column=0, sticky="w", pady=(8, 0))

        self.process_output = ScrolledText(tab, wrap="word")
        self.process_output.grid(row=2, column=0, sticky="nsew", pady=(8, 0))

    def _build_analysis_tab(self) -> None:
        """Build live GA/MO analysis controls."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Live Analysis")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(tab)
        toolbar.grid(row=0, column=0, sticky="ew")
        self.run_selector = ttk.Combobox(toolbar, textvariable=self.selected_run, state="readonly", width=100)
        self.run_selector.pack(side="left", fill="x", expand=True)
        ttk.Button(toolbar, text="Refresh", command=self.refresh_all_views).pack(side="left", padx=(8, 0))

        self.analysis_summary = StringVar(value="No run selected")
        ttk.Label(tab, textvariable=self.analysis_summary).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.analysis_output = ScrolledText(tab, wrap="word")
        self.analysis_output.grid(row=2, column=0, sticky="nsew", pady=(8, 0))

    def _build_prompt_tab(self) -> None:
        """Build prompt inspection controls."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Prompts")
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)

        self.prompt_table = ttk.Treeview(tab, columns=("prompt_id",), show="headings")
        self.prompt_table.heading("prompt_id", text="Prompt")
        self.prompt_table.column("prompt_id", width=280, anchor="w")
        self.prompt_table.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        self.prompt_table.bind("<<TreeviewSelect>>", self.show_selected_prompt)

        self.prompt_output = ScrolledText(tab, wrap="word")
        self.prompt_output.grid(row=0, column=1, sticky="nsew")
        self.loaded_prompts: dict[str, str] = {}

    def _labeled_entry(self, parent: ttk.Frame, label: str, variable: StringVar, row: int, column: int) -> None:
        """Create a label and entry pair."""
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=column + 1, sticky="ew", padx=(8, 16), pady=4)

    def _labeled_combo(
        self,
        parent: ttk.Frame,
        label: str,
        variable: StringVar,
        values: tuple[str, ...],
        row: int,
        column: int,
    ) -> ttk.Combobox:
        """Create a label and readonly combobox pair."""
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", pady=4)
        combo = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly")
        combo.grid(
            row=row, column=column + 1, sticky="ew", padx=(8, 16), pady=4
        )
        return combo

    def on_algorithm_selected(self, _event: object | None = None) -> None:
        """Keep evaluator defaults consistent with the selected algorithm family."""
        if self.algorithm.get() in ROUND_ALGORITHMS:
            self.evaluator.set("round")
            self.final_test_max_front.set("0")
        self.refresh_objective_table()

    def add_objective_target(self) -> None:
        """Add a target opponent objective to the GUI list."""
        target = simpledialog.askstring("Add objective target", "Target opponent class:", parent=self.root)
        if target is None:
            return
        target = target.strip()
        if not target:
            messagebox.showerror("Invalid objective target", "Target opponent class cannot be empty.")
            return
        if target in self.objective_targets:
            messagebox.showerror("Duplicate objective target", f"{target} already exists.")
            return
        self.objective_targets.append(target)
        if not self.single_objective_target.get():
            self.single_objective_target.set(target)
        self.refresh_objective_table(select_target=target)

    def delete_objective_target(self) -> None:
        """Delete the selected target opponent objective."""
        target = self.selected_objective_target()
        if target is None:
            messagebox.showerror("No objective selected", "Select an objective target first.")
            return
        if len(self.objective_targets) == 1:
            messagebox.showerror("Cannot delete objective", "Keep at least one objective target.")
            return
        if not messagebox.askyesno("Delete objective", f"Delete objective target?\n{target}"):
            return
        self.objective_targets = [item for item in self.objective_targets if item != target]
        if self.single_objective_target.get() == target:
            self.single_objective_target.set(self.objective_targets[0])
        self.refresh_objective_table(select_target=self.single_objective_target.get())

    def use_selected_single_objective(self) -> None:
        """Use the selected objective as the single-objective GA target."""
        target = self.selected_objective_target()
        if target is None:
            messagebox.showerror("No objective selected", "Select an objective target first.")
            return
        self.single_objective_target.set(target)
        self.refresh_objective_table(select_target=target)

    def selected_objective_target(self) -> str | None:
        """Return the target selected in the objective table."""
        selection = self.objective_table.selection()
        if not selection:
            return None
        return selection[0]

    def refresh_objective_table(self, *, select_target: str | None = None) -> None:
        """Refresh objective rows and show their calculation details."""
        if not hasattr(self, "objective_table"):
            return
        previous = select_target or self.selected_objective_target() or self.single_objective_target.get()
        self.objective_table.delete(*self.objective_table.get_children())
        for index, target in enumerate(self.objective_targets):
            objective_key = objective_key_for_target(target, index)
            prefix = "[single] " if self.algorithm.get() in GA_ALGORITHMS and target == self.single_objective_target.get() else ""
            self.objective_table.insert(
                "",
                "end",
                iid=target,
                values=(
                    f"{prefix}{target}",
                    objective_key,
                    "raw_resource_advantage_score + win_bonus * win_score",
                ),
            )
        if previous in self.objective_targets:
            self.objective_table.selection_set(previous)
        elif self.objective_targets:
            self.objective_table.selection_set(self.objective_targets[0])
        self.update_objective_detail()

    def on_objective_selected(self, _event: object | None = None) -> None:
        """Show the calculation details for the selected objective."""
        self.update_objective_detail()

    def update_objective_detail(self) -> None:
        """Show how the selected objective is calculated."""
        target = self.selected_objective_target()
        if target is None:
            self.objective_detail.set("Select an objective target to inspect its calculation.")
            return
        try:
            index = self.objective_targets.index(target)
        except ValueError:
            index = 0
        objective_key = objective_key_for_target(target, index)
        mode = "single-objective GA uses only this selected target" if self.algorithm.get() in GA_ALGORITHMS else "multi-objective NSGA-II uses every listed target as one objective"
        self.objective_detail.set(
            f"{objective_key} against {target}: "
            "match_score = calculate_match_score(log, resource_advantage_weights); "
            "raw_resource_advantage_score = weighted ally material/resources - weighted enemy material/resources; "
            "win_score = 1 for win, -1 for loss, 0 for draw/unknown; "
            "objective = raw_resource_advantage_score + win_bonus * win_score. "
            f"Current mode: {mode}."
        )

    def browse_base_config(self) -> None:
        """Choose a base evolution JSON config."""
        path = filedialog.askopenfilename(
            initialdir=str(CONFIG_DIR),
            title="Select base config",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if path:
            self.base_config_path.set(path)

    def browse_component(self) -> None:
        """Choose an initial component pool JSON file."""
        path = filedialog.askopenfilename(
            initialdir=str(ROOT),
            title="Select component.json",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if path:
            self.component_source_path.set(path)
            self.preview_component(Path(path))

    def import_component(self) -> None:
        """Copy the selected component JSON into configs/experiments and use it for the next run."""
        source = Path(self.component_source_path.get())
        if not source.exists():
            messagebox.showerror("Missing component file", "Select an existing component JSON file first.")
            return
        try:
            json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            messagebox.showerror("Invalid component JSON", str(exc))
            return
        EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
        destination = EXPERIMENT_DIR / f"components_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        shutil.copyfile(source, destination)
        self.component_runtime_path.set(relative_or_absolute(destination))
        self.preview_component(destination)

    def preview_component(self, path: Path) -> None:
        """Load a component JSON file into the editor and prompt builder."""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.component_status.set(f"Could not read component JSON: {exc}")
            self._set_text(self.component_editor, "")
            self._set_text(self.component_prompt_output, "")
            return
        if not isinstance(payload, dict):
            self.component_status.set(f"Component JSON must be an object, got {type(payload).__name__}.")
            self._set_text(self.component_editor, "")
            self._set_text(self.component_prompt_output, "")
            return
        try:
            pool = ComponentPool(payload)
        except (TypeError, ValueError) as exc:
            self.component_status.set(f"Invalid component payload: {exc}")
            self._set_text(self.component_editor, "")
            self._set_text(self.component_prompt_output, "")
            return

        self.loaded_component_path = path
        self.component_payload = pool.to_component_dict()
        self.component_prompt_selection = {key: 0 for key in pool.component_keys}
        if not self.static_component_keys:
            self.static_component_keys = set(pool.non_evolving_component_keys)
        self.static_component_keys = self.valid_static_component_keys()
        self.refresh_component_controls()
        self.render_selected_component_prompt()
        self.component_status.set(f"Loaded {len(pool.component_keys)} components from {path}")

    def refresh_component_controls(self) -> None:
        """Refresh component comboboxes, selected-candidate table, and editor text."""
        keys = self.component_keys()
        self.component_category_combo.configure(values=keys)
        if keys and self.component_category.get() not in keys:
            self.component_category.set(keys[0])
        elif not keys:
            self.component_category.set("")
        self.refresh_component_candidate_choices()
        self.refresh_component_selection_table()
        self.load_component_editor()

    def component_keys(self) -> list[str]:
        """Return editable component keys from the loaded payload."""
        return [
            key for key in self.component_payload
            if key != "metadata"
        ]

    def static_toggle_component_keys(self) -> list[str]:
        """Return component keys that can be toggled as static in the GUI."""
        return [
            key for key in self.component_keys()
            if not self.is_training_examples_category(key)
        ]

    def valid_static_component_keys(self) -> set[str]:
        """Return static keys valid for the current component pool plus json_schema."""
        allowed = set(self.static_toggle_component_keys())
        if "json_schema" in self.static_component_keys or not self.component_payload:
            allowed.add("json_schema")
        return {key for key in self.static_component_keys if key in allowed}

    def config_static_component_keys(self) -> list[str]:
        """Return static component keys for config serialization."""
        keys = self.valid_static_component_keys()
        return sorted(keys)

    def refresh_component_candidate_choices(self) -> None:
        """Refresh candidate choices for the current component category."""
        category = self.component_category.get()
        count = self.component_candidate_count(category)
        if self.is_training_examples_category(category):
            values = tuple(
                f"{index}:{self.training_example_name(index)}"
                for index in range(count)
            )
        else:
            values = tuple(str(index) for index in range(count))
        self.component_candidate_combo.configure(values=values)
        if values and self.component_candidate.get() not in values:
            self.component_candidate.set(values[0])
        elif not values:
            self.component_candidate.set("0")

    def is_training_examples_category(self, category: str) -> bool:
        """Return whether a component category is the merged training examples bucket."""
        return category == ComponentPool.TRAINING_EXAMPLES_KEY

    def training_examples(self) -> list[dict[str, Any]]:
        """Return the editable training examples list."""
        examples = self.component_payload.get(ComponentPool.TRAINING_EXAMPLES_KEY, [])
        return examples if isinstance(examples, list) else []

    def training_example_name(self, index: int) -> str:
        """Return one training example display name."""
        examples = self.training_examples()
        if index < 0 or index >= len(examples):
            return f"example_{index}"
        item = examples[index]
        if isinstance(item, dict):
            return str(item.get("name", f"example_{index}"))
        return f"example_{index}"

    def selected_component_candidate_index(self) -> int:
        """Return the numeric candidate index from the candidate combobox."""
        raw_value = self.component_candidate.get().split(":", 1)[0]
        try:
            return int(raw_value)
        except ValueError:
            return 0

    def component_candidate_count(self, category: str) -> int:
        """Return candidate count for one component category."""
        if self.is_training_examples_category(category):
            return len(self.training_examples())
        candidates = self.component_payload.get(category, [])
        return len(candidates) if isinstance(candidates, list) else 0

    def component_candidate_lines(self, category: str, index: int) -> list[str]:
        """Return one component candidate as editable lines."""
        if self.is_training_examples_category(category):
            examples = self.training_examples()
            if index < 0 or index >= len(examples):
                return []
            item = examples[index]
            if isinstance(item, dict):
                content = item.get("content", [])
                return [str(line) for line in content] if isinstance(content, list) else [str(content)]
            return [str(item)]
        candidates = self.component_payload.get(category, [])
        if not isinstance(candidates, list) or index < 0 or index >= len(candidates):
            return []
        candidate = candidates[index]
        if isinstance(candidate, list):
            return [str(line) for line in candidate]
        return [str(candidate)]

    def on_component_category_selected(self, _event: object | None = None) -> None:
        """Load candidate choices after selecting a component category."""
        self.refresh_component_candidate_choices()
        self.load_component_editor()

    def on_component_candidate_selected(self, _event: object | None = None) -> None:
        """Load the selected candidate into the editor."""
        self.load_component_editor()

    def on_component_prompt_row_selected(self, _event: object | None = None) -> None:
        """Mirror a prompt-builder row into the component editor controls."""
        selection = self.component_selection_table.selection()
        if not selection:
            return
        category = selection[0]
        if category not in self.component_keys():
            return
        self.component_category.set(category)
        self.refresh_component_candidate_choices()
        selected_index = self.component_prompt_selection.get(category, 0)
        if self.is_training_examples_category(category):
            self.component_candidate.set(f"0:{self.training_example_name(0)}")
        else:
            self.component_candidate.set("0" if category in self.static_component_keys else str(selected_index))
        self.load_component_editor()

    def load_component_editor(self) -> None:
        """Show the currently selected candidate text in the editor."""
        category = self.component_category.get()
        index = self.selected_component_candidate_index()
        self._set_text(self.component_editor, "\n".join(self.component_candidate_lines(category, index)))
        if self.is_training_examples_category(category):
            self.refresh_training_example_units()

    def apply_component_edit(self) -> None:
        """Apply the editor text to the loaded in-memory component payload."""
        category = self.component_category.get()
        if category not in self.component_keys():
            messagebox.showerror("No component selected", "Load a component JSON and select a component first.")
            return
        index = self.selected_component_candidate_index()
        if index < 0 or index >= self.component_candidate_count(category):
            messagebox.showerror("Invalid candidate", f"Candidate index out of range for {category}.")
            return
        text = self.component_editor.get("1.0", "end").rstrip("\n")
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        if not lines:
            messagebox.showerror("Empty component", "Component content must contain at least one non-empty line.")
            return
        if self.is_training_examples_category(category):
            examples = self.training_examples()
            item = examples[index]
            if isinstance(item, dict):
                item["content"] = lines
            else:
                examples[index] = {"name": f"example_{index}", "content": lines}
            self.refresh_component_selection_table()
            self.render_selected_component_prompt()
            self.component_status.set(f"Applied edit to training_examples[{index}]")
            return
        candidates = self.component_payload[category]
        if not isinstance(candidates, list):
            messagebox.showerror("Invalid component", f"{category} is not a candidate list.")
            return
        candidates[index] = lines
        self.refresh_component_selection_table()
        self.render_selected_component_prompt()
        self.component_status.set(f"Applied edit to {category}[{index}]")

    def add_component_category(self) -> None:
        """Add a new component category with one candidate."""
        if not self.component_payload:
            self.component_payload = {"metadata": {}}
        name = simpledialog.askstring("Add component", "New component key:", parent=self.root)
        if name is None:
            return
        name = name.strip()
        if not name:
            messagebox.showerror("Invalid component key", "Component key cannot be empty.")
            return
        if name == "metadata":
            messagebox.showerror("Invalid component key", f"`{name}` is reserved.")
            return
        if name in self.component_payload:
            messagebox.showerror("Duplicate component key", f"{name} already exists.")
            return
        self.component_payload[name] = [self.editor_lines_or_default()]
        self.component_prompt_selection[name] = 0
        self.component_category.set(name)
        self.component_candidate.set("0")
        self.refresh_component_controls()
        self.render_selected_component_prompt()
        self.component_status.set(f"Added component {name}")

    def delete_component_category(self) -> None:
        """Delete the selected component category."""
        category = self.component_category.get()
        if category not in self.component_keys():
            messagebox.showerror("No component selected", "Select a component before deleting.")
            return
        if not messagebox.askyesno("Delete component", f"Delete component `{category}` and all its candidates?"):
            return
        self.component_payload.pop(category, None)
        self.component_prompt_selection.pop(category, None)
        self.remove_component_key_from_metadata(category)
        keys = self.component_keys()
        self.component_category.set(keys[0] if keys else "")
        self.component_candidate.set("0")
        self.refresh_component_controls()
        self.render_selected_component_prompt()
        self.component_status.set(f"Deleted component {category}")

    def add_component_candidate(self) -> None:
        """Append a candidate to the selected component category."""
        category = self.component_category.get()
        if category not in self.component_keys():
            messagebox.showerror("No component selected", "Select a component before adding a candidate.")
            return
        if self.is_training_examples_category(category):
            name = simpledialog.askstring("Add training example", "Example name:", parent=self.root)
            if name is None:
                return
            name = name.strip() or f"example_{len(self.training_examples())}"
            examples = self.training_examples()
            examples.append({"name": name, "content": self.editor_lines_or_default()})
            new_index = len(examples) - 1
            self.component_candidate.set(f"{new_index}:{name}")
            self.refresh_component_controls()
            self.render_selected_component_prompt()
            self.component_status.set(f"Added training example {name}")
            return
        candidates = self.component_payload.get(category)
        if not isinstance(candidates, list):
            messagebox.showerror("Invalid component", f"{category} is not a candidate list.")
            return
        candidates.append(self.editor_lines_or_default())
        new_index = len(candidates) - 1
        self.component_candidate.set(str(new_index))
        self.component_prompt_selection[category] = new_index
        self.refresh_component_controls()
        self.render_selected_component_prompt()
        self.component_status.set(f"Added candidate {category}[{new_index}]")

    def delete_component_candidate(self) -> None:
        """Delete the selected candidate from the selected component category."""
        category = self.component_category.get()
        if category not in self.component_keys():
            messagebox.showerror("No component selected", "Select a component before deleting a candidate.")
            return
        candidates = self.component_payload.get(category)
        if self.is_training_examples_category(category):
            candidates = self.training_examples()
        if not isinstance(candidates, list) or not candidates:
            messagebox.showerror("No candidate", f"{category} has no candidates to delete.")
            return
        index = self.selected_component_candidate_index()
        if index < 0 or index >= len(candidates):
            messagebox.showerror("Invalid candidate", f"Candidate index out of range for {category}.")
            return
        if len(candidates) == 1:
            messagebox.showerror("Cannot delete candidate", "A component must keep at least one candidate.")
            return
        if not messagebox.askyesno("Delete candidate", f"Delete candidate {category}[{index}]?"):
            return
        candidates.pop(index)
        next_index = min(index, len(candidates) - 1)
        self.component_candidate.set(str(next_index))
        selected_index = self.component_prompt_selection.get(category, 0)
        if selected_index == index or selected_index >= len(candidates):
            self.component_prompt_selection[category] = next_index
        elif selected_index > index:
            self.component_prompt_selection[category] = selected_index - 1
        self.refresh_component_controls()
        self.render_selected_component_prompt()
        self.component_status.set(f"Deleted candidate {category}[{index}]")

    def editor_lines_or_default(self) -> list[str]:
        """Return editor text as component lines, or a default candidate body."""
        text = self.component_editor.get("1.0", "end").rstrip("\n")
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        return lines or ["New component candidate."]

    def remove_component_key_from_metadata(self, key: str) -> None:
        """Remove a deleted component key from metadata references."""
        self.static_component_keys.discard(key)
        metadata = self.component_payload.get("metadata")
        if not isinstance(metadata, dict):
            return
        for field in ("non_evolving_component_keys", "reflection_format_keys", "reflection_alignment_keys"):
            value = metadata.get(field)
            if isinstance(value, list):
                metadata[field] = [item for item in value if str(item) != key]
        if metadata.get("identity_component_key") == key:
            metadata["identity_component_key"] = None

    def generate_training_example_state(self) -> None:
        """Replace the selected training example INPUT block with a random state."""
        if not self.is_training_examples_category(self.component_category.get()):
            messagebox.showerror("Training examples only", "Select training_examples before generating state text.")
            return
        state_lines = ["INPUT:", *StateGenerator().generate_text().splitlines()]
        current_lines = self.component_editor.get("1.0", "end").rstrip("\n").splitlines()
        output_index = first_output_line_index(current_lines)
        if output_index is None:
            new_lines = [
                *state_lines,
                "",
                "OUTPUT:",
                "{",
                f'  "thinking": "{build_thinking_prefix(parse_feature_units(state_lines))}; reason=...",',
                '  "moves": [',
                "  ]",
                "}",
            ]
        else:
            new_lines = [*state_lines, "", *current_lines[output_index:]]
        self._set_text(self.component_editor, "\n".join(new_lines))
        self.apply_component_edit()
        self.refresh_training_example_units()

    def refresh_training_example_units(self) -> None:
        """Refresh unit choices parsed from the selected training example state."""
        lines = self.component_editor.get("1.0", "end").splitlines()
        self.training_example_units = parse_feature_units(lines)
        values = tuple(unit_coordinate(unit) for unit in self.training_example_units)
        self.training_example_unit_combo.configure(values=values)
        if values and self.training_example_unit.get() not in values:
            self.training_example_unit.set(values[0])
        elif not values:
            self.training_example_unit.set("")
        self.refresh_training_example_commands()

    def refresh_training_example_commands(self) -> None:
        """Refresh command choices to only show legal actions for the selected unit."""
        unit = self.selected_training_example_unit()
        commands = legal_training_example_commands(unit, self.training_example_units)
        self.training_example_command_combo.configure(values=commands)
        if commands and self.training_example_command.get() not in commands:
            self.training_example_command.set(commands[0])
        elif not commands:
            self.training_example_command.set("")
        self.update_training_example_move_preview()

    def assembled_training_example_move(self) -> dict[str, Any] | None:
        """Return the currently assembled move, if valid."""
        unit = self.selected_training_example_unit()
        if unit is None:
            return None
        return build_training_example_move(
            self.training_example_command.get(),
            unit,
            self.training_example_units,
        )

    def update_training_example_move_preview(self, _event: object | None = None) -> None:
        """Refresh the single move preview in the move builder."""
        if not self.is_training_examples_category(self.component_category.get()):
            self.training_example_current_move.set("Move builder is active when training_examples is selected.")
            return
        unit = self.selected_training_example_unit()
        if unit is None:
            self.training_example_current_move.set("No coordinate selected.")
            return
        self.refresh_training_example_commands_if_needed(unit)
        move = self.assembled_training_example_move()
        if move is None:
            self.training_example_current_move.set(
                f"{self.training_example_command.get()} is not valid for "
                f"{unit_coordinate(unit)} {unit['owner']} {unit['kind']}."
            )
            return
        self.training_example_current_move.set(json.dumps(move, ensure_ascii=False))

    def append_training_example_move(self) -> None:
        """Append the currently assembled legal-format move object."""
        if not self.is_training_examples_category(self.component_category.get()):
            messagebox.showerror("Training examples only", "Select training_examples before adding example moves.")
            return
        self.refresh_training_example_units()
        move = self.assembled_training_example_move()
        if move is None:
            messagebox.showerror("Invalid move", self.training_example_current_move.get())
            return
        lines = self.component_editor.get("1.0", "end").rstrip("\n").splitlines()
        new_lines = apply_thinking_prefix(lines)
        new_lines = append_move_to_example_lines(new_lines, move)
        self._set_text(self.component_editor, "\n".join(new_lines))
        self.apply_component_edit()
        self.update_training_example_move_preview()

    def selected_training_example_unit(self) -> dict[str, Any] | None:
        """Return the unit selected in the training example unit combobox."""
        selected = self.training_example_unit.get()
        for unit in self.training_example_units:
            if unit_coordinate(unit) == selected:
                return unit
        return self.training_example_units[0] if self.training_example_units else None

    def refresh_training_example_commands_if_needed(self, unit: dict[str, Any]) -> None:
        """Keep the selected command inside the legal command set."""
        commands = legal_training_example_commands(unit, self.training_example_units)
        self.training_example_command_combo.configure(values=commands)
        if commands and self.training_example_command.get() not in commands:
            self.training_example_command.set(commands[0])
        elif not commands:
            self.training_example_command.set("")

    def save_component_json(self) -> Path | None:
        """Write the edited component payload back to the currently loaded JSON path."""
        if self.loaded_component_path is None:
            messagebox.showerror("No component loaded", "Load a component JSON before saving.")
            return None
        return self.write_component_payload(self.loaded_component_path)

    def save_component_json_as(self) -> Path | None:
        """Write the edited component payload as a runtime experiment component file."""
        if not self.component_payload:
            messagebox.showerror("No component loaded", "Load a component JSON before saving.")
            return None
        EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
        destination = EXPERIMENT_DIR / f"components_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        saved = self.write_component_payload(destination)
        if saved:
            self.loaded_component_path = saved
            self.component_runtime_path.set(relative_or_absolute(saved))
            self.component_source_path.set(str(saved))
        return saved

    def write_component_payload(self, path: Path) -> Path | None:
        """Persist the current component payload to disk."""
        try:
            pool = ComponentPool(self.component_payload)
            payload = pool.to_component_dict()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except (OSError, TypeError, ValueError) as exc:
            messagebox.showerror("Could not save component JSON", str(exc))
            return None
        self.component_payload = payload
        self.loaded_component_path = path
        self.component_status.set(f"Saved component JSON to {path}")
        return path

    def use_component_in_prompt(self) -> None:
        """Use the selected candidate for the selected component in prompt rendering."""
        category = self.component_category.get()
        if category not in self.component_keys():
            messagebox.showerror("No component selected", "Load a component JSON and select a component first.")
            return
        if self.is_training_examples_category(category):
            self.render_selected_component_prompt()
            self.component_status.set("training_examples are sampled randomly at prompt render time")
            return
        if category in self.static_component_keys:
            self.component_prompt_selection[category] = 0
            self.refresh_component_selection_table()
            self.render_selected_component_prompt()
            self.component_status.set(f"{category} is static; prompt rendering uses candidate 0")
            return
        index = self.selected_component_candidate_index()
        if index < 0 or index >= self.component_candidate_count(category):
            messagebox.showerror("Invalid candidate", f"Candidate index out of range for {category}.")
            return
        self.component_prompt_selection[category] = index
        self.refresh_component_selection_table()
        self.render_selected_component_prompt()

    def toggle_selected_static_component(self) -> None:
        """Toggle whether the selected component is static during evolution."""
        selection = self.component_selection_table.selection()
        category = selection[0] if selection else self.component_category.get()
        if category not in self.static_toggle_component_keys():
            messagebox.showerror("Cannot toggle static", "Select a normal component row first.")
            return
        if category in self.static_component_keys:
            self.static_component_keys.remove(category)
            self.component_status.set(f"{category} will evolve")
        else:
            self.static_component_keys.add(category)
            self.component_prompt_selection[category] = 0
            self.component_status.set(f"{category} is static and will use candidate 0")
        self.static_component_keys = self.valid_static_component_keys()
        self.refresh_component_selection_table()
        self.render_selected_component_prompt()

    def on_training_example_sample_count_selected(self, _event: object | None = None) -> None:
        """Refresh prompt preview after changing training-example sample count."""
        self.refresh_component_selection_table()
        self.render_selected_component_prompt()

    def training_example_selection_value(self) -> str | int:
        """Return random or fixed training-example sample-count selection."""
        raw_value = self.training_example_sample_count.get().strip()
        if raw_value == "random 0-4":
            return "random_0_4"
        try:
            return int(raw_value)
        except ValueError:
            return "random_0_4"

    def reset_component_prompt_selection(self) -> None:
        """Select candidate zero for every loaded component."""
        self.component_prompt_selection = {
            key: 0 for key in self.component_keys()
            if not self.is_training_examples_category(key)
        }
        self.refresh_component_selection_table()
        self.render_selected_component_prompt()

    def refresh_component_selection_table(self) -> None:
        """Refresh the prompt-builder component selection table."""
        self.component_selection_table.delete(*self.component_selection_table.get_children())
        for key in self.component_keys():
            if self.is_training_examples_category(key):
                examples = self.training_examples()
                line_count = sum(len(self.component_candidate_lines(key, index)) for index in range(len(examples)))
                self.component_selection_table.insert(
                    "",
                    "end",
                    iid=key,
                    values=(key, "-", self.training_example_sample_count.get(), line_count),
                )
                continue
            selected_index = self.component_prompt_selection.get(key, 0)
            candidate_count = self.component_candidate_count(key)
            static_label = "yes" if key in self.static_component_keys else ""
            if candidate_count <= 0:
                selected_index = 0
            elif selected_index >= candidate_count:
                selected_index = 0
                self.component_prompt_selection[key] = 0
            if key in self.static_component_keys:
                selected_index = 0
                self.component_prompt_selection[key] = 0
            line_count = len(self.component_candidate_lines(key, selected_index))
            self.component_selection_table.insert(
                "",
                "end",
                iid=key,
                values=(key, static_label, selected_index, line_count),
            )

    def render_selected_component_prompt(self) -> None:
        """Render a prompt from the currently selected component candidates."""
        if not self.component_payload:
            self._set_text(self.component_prompt_output, "")
            return
        try:
            pool = ComponentPool(self.component_payload)
            pool.configure_non_evolving_keys(self.config_static_component_keys())
            selected = {
                key: self.component_prompt_selection.get(key, 0)
                for key in pool.component_keys
            }
            selected[ComponentPool.TRAINING_EXAMPLES_KEY] = {
                "sample_count": self.training_example_selection_value(),
            }
            rendered_lines = pool.render_prompt_lines(
                selected,
                include_identity_component=self.include_identity_component_in_preview(),
            )
        except (TypeError, ValueError) as exc:
            self._set_text(self.component_prompt_output, f"Could not render prompt:\n{exc}")
            return
        self._set_text(self.component_prompt_output, "\n".join(rendered_lines))

    def include_identity_component_in_preview(self) -> bool:
        """Return whether preview rendering should include the identity component."""
        try:
            payload = load_json_file(resolve_repo_path(self.base_config_path.get()))
        except (OSError, json.JSONDecodeError):
            return True
        return bool(payload.get("include_strategy_identity_in_prompt", True))

    def load_base_config_into_form(self) -> None:
        """Load config fields into the GUI form."""
        path = Path(self.base_config_path.get())
        if not path.exists():
            messagebox.showerror("Missing config", f"Config file does not exist:\n{path}")
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            messagebox.showerror("Invalid config JSON", str(exc))
            return
        self.algorithm.set(str(payload.get("algorithm", self.algorithm.get())))
        if self.algorithm.get() not in ALGORITHM_CHOICES:
            self.algorithm.set("round_nsga2")
        self.application.set(str(payload.get("application", self.application.get())))
        if self.application.get() not in APPLICATION_CHOICES:
            self.application.set("microrts")
        self.evaluator.set(str(payload.get("evaluator", self.evaluator.get())))
        if self.evaluator.get() not in EVALUATOR_CHOICES:
            self.evaluator.set("round")
        self.population_size.set(str(payload.get("population_size", self.population_size.get())))
        self.num_generations.set(str(payload.get("num_generations", self.num_generations.get())))
        self.run_time_per_game_sec.set(str(payload.get("run_time_per_game_sec", self.run_time_per_game_sec.get())))
        self.real_eval_rate.set(str(payload.get("real_eval_rate", self.real_eval_rate.get())))
        self.final_test_max_front.set(str(payload.get("final_test_max_front", self.final_test_max_front.get())))
        self.selection_method.set(str(payload.get("selection_method", self.selection_method.get())))
        self.tournament_size.set(str(payload.get("tournament_size", self.tournament_size.get())))
        self.crossover.set(str(payload.get("crossover", self.crossover.get())))
        self.crossover_repair_enabled.set(bool(payload.get("crossover_repair_enabled", True)))
        self.enable_reflection_operator.set(bool(payload.get("enable_reflection_operator", True)))
        self.component_runtime_path.set(str(payload.get("component_pool_path", self.component_runtime_path.get())))
        self.static_component_keys = set(
            str(key)
            for key in payload.get(
                "non_evolving_prompt_components",
                payload.get("non_evolving_component_keys", list(ComponentPool.DEFAULT_NON_EVOLVING_COMPONENT_KEYS)),
            )
        )
        loaded_opponents = parse_target_list(payload.get("real_eval_opponents", []))
        if loaded_opponents:
            self.objective_targets = loaded_opponents
            if self.single_objective_target.get() not in self.objective_targets:
                self.single_objective_target.set(self.objective_targets[0])
        self.opponents_text.set(", ".join(self.objective_targets))
        for key, variable in self.operator_weights.items():
            variable.set(str((payload.get("reproduction_operator_probs") or {}).get(key, variable.get())))
        for key, variable in self.mutation_weights.items():
            variable.set(str((payload.get("strategy_mutation") or {}).get(key, variable.get())))
        component_path = resolve_repo_path(self.component_runtime_path.get())
        if component_path.exists():
            self.preview_component(component_path)
        self.on_algorithm_selected()
        self.status.set(f"Loaded {path}")

    def validate_settings(self) -> None:
        """Validate form values by building a config payload."""
        try:
            self.build_config_payload()
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return
        messagebox.showinfo("Settings valid", "Generated config settings are valid.")

    def save_generated_config(self) -> Path | None:
        """Write the current GUI settings to a JSON config file."""
        try:
            payload = self.build_config_payload()
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return None
        EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
        path = EXPERIMENT_DIR / self.config_filename()
        if path.exists() and not messagebox.askyesno("Overwrite config", f"Overwrite existing config?\n{path}"):
            return None
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.generated_config_path = path
        self.generated_config_label.set(f"Generated config: {path}")
        self.status.set(f"Saved {path.name}")
        return path

    def build_config_payload(self) -> dict[str, Any]:
        """Build one EAGLE config payload from the GUI controls."""
        base_path = Path(self.base_config_path.get())
        payload = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else {}
        component_path = self.component_runtime_path.get().strip()
        if not component_path:
            raise ValueError("Runtime component path is required.")
        if not resolve_repo_path(component_path).exists():
            raise ValueError(f"Runtime component path does not exist: {component_path}")
        if self.application.get() != "microrts":
            raise ValueError(f"Unsupported application: {self.application.get()}.")
        if self.algorithm.get() in ROUND_ALGORITHMS and self.evaluator.get() != "round":
            raise ValueError("round_ga and round_nsga2 must use the round evaluator.")
        objective_targets = self.config_objective_targets()

        payload.update(
            {
                "application": self.application.get(),
                "evaluator": self.evaluator.get(),
                "algorithm": self.algorithm.get(),
                "population_size": parse_int(self.population_size.get(), "population_size"),
                "num_generations": parse_int(self.num_generations.get(), "num_generations"),
                "run_time_per_game_sec": parse_int(self.run_time_per_game_sec.get(), "run_time_per_game_sec"),
                "real_eval_rate": parse_float(self.real_eval_rate.get(), "real_eval_rate"),
                "final_test_max_front": parse_optional_nonnegative_int(
                    self.final_test_max_front.get(),
                    "final_test_max_front",
                ),
                "selection_method": self.selection_method.get(),
                "tournament_size": parse_int(self.tournament_size.get(), "tournament_size"),
                "crossover": self.crossover.get(),
                "crossover_repair_enabled": bool(self.crossover_repair_enabled.get()),
                "enable_reflection_operator": bool(self.enable_reflection_operator.get()),
                "component_pool_path": component_path,
                "non_evolving_prompt_components": self.config_static_component_keys(),
                "real_eval_opponents": objective_targets,
                "reproduction_operator_probs": {
                    key: parse_float(variable.get(), key)
                    for key, variable in self.operator_weights.items()
                },
                "strategy_mutation": {
                    key: parse_float(variable.get(), key)
                    for key, variable in self.mutation_weights.items()
                },
            }
        )
        normalize_probability_map(payload["reproduction_operator_probs"], "reproduction_operator_probs")
        normalize_probability_map(payload["strategy_mutation"], "strategy_mutation")
        return payload

    def config_objective_targets(self) -> list[str]:
        """Return objective targets according to the selected algorithm mode."""
        targets = [target.strip() for target in self.objective_targets if target.strip()]
        if not targets:
            raise ValueError("At least one objective target is required.")
        if self.algorithm.get() in GA_ALGORITHMS:
            target = self.single_objective_target.get().strip()
            if not target:
                target = targets[0]
                self.single_objective_target.set(target)
            if target not in targets:
                targets.insert(0, target)
            return [target]
        return targets

    def config_filename(self) -> str:
        """Return a safe config filename from the user-provided config name."""
        raw_name = self.config_name.get().strip()
        if not raw_name:
            raw_name = f"gui_evolution_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in raw_name)
        if not safe.endswith(".json"):
            safe = f"{safe}.json"
        return safe

    def start_experiment(self) -> None:
        """Save current settings and start EAGLE in a background process."""
        if self.process and self.process.poll() is None:
            messagebox.showwarning("Process already running", "Stop the current process before starting another run.")
            return
        config_path = self.save_generated_config()
        if config_path is None:
            return
        command = [
            sys.executable,
            "-m",
            "eagle.main",
            "--config",
            str(config_path),
            "--algorithm",
            self.algorithm.get(),
            "--evaluator",
            self.evaluator.get(),
        ]
        if self.quick_run.get():
            command.append("--quick-run")
        if self.skip_final_test.get():
            command.append("--skip-final-test")

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.process_log_path = LOG_DIR / f"gui_process_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        log_handle = self.process_log_path.open("w", encoding="utf-8", errors="replace")
        log_handle.write("Command: " + " ".join(command) + "\n\n")
        log_handle.flush()
        self.process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.status.set(f"Started PID {self.process.pid}")
        self.refresh_all_views()

    def stop_process(self) -> None:
        """Terminate the process launched from this GUI."""
        if not self.process or self.process.poll() is not None:
            self.status.set("No running process")
            return
        self.process.terminate()
        self.status.set(f"Stopping PID {self.process.pid}")

    def refresh_runs(self) -> None:
        """Refresh run-directory choices."""
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        runs = [str(path) for path in sorted(LOG_DIR.iterdir(), reverse=True) if path.is_dir()]
        self.run_selector.configure(values=runs)
        if runs and self.selected_run.get() not in runs:
            self.selected_run.set(runs[0])

    def refresh_all_views(self) -> None:
        """Refresh all live views."""
        self.refresh_runs()
        self.refresh_process_log()
        run_dir = self.current_run_dir()
        self.refresh_analysis(run_dir)
        self.refresh_prompts(run_dir)

    def refresh_process_log(self) -> None:
        """Refresh process output and status."""
        if self.process and self.process.poll() is not None:
            self.status.set(f"Process exited with code {self.process.returncode}")
        if self.process_log_path:
            self._set_text(self.process_output, read_tail(self.process_log_path, 18000))

    def refresh_analysis(self, run_dir: Path | None) -> None:
        """Refresh GA/MO analysis for one run."""
        if run_dir is None:
            self.analysis_summary.set("No run selected")
            self._set_text(self.analysis_output, "")
            return
        report = build_live_analysis_report(run_dir)
        self.analysis_summary.set(report.summary)
        self._set_text(self.analysis_output, report.body)

    def refresh_prompts(self, run_dir: Path | None) -> None:
        """Refresh prompt list from generation logs and run_state."""
        previous = self.selected_prompt_id()
        self.prompt_table.delete(*self.prompt_table.get_children())
        self.loaded_prompts = load_prompts(run_dir) if run_dir else {}
        for prompt_id in self.loaded_prompts:
            self.prompt_table.insert("", "end", iid=prompt_id, values=(prompt_id,))
        if previous in self.loaded_prompts:
            self.prompt_table.selection_set(previous)
        elif self.loaded_prompts:
            self.prompt_table.selection_set(next(iter(self.loaded_prompts)))
        self.show_selected_prompt()

    def show_selected_prompt(self, _event: object | None = None) -> None:
        """Show the currently selected prompt text."""
        prompt_id = self.selected_prompt_id()
        self._set_text(self.prompt_output, self.loaded_prompts.get(prompt_id or "", "No prompt text found."))

    def selected_prompt_id(self) -> str | None:
        """Return the selected prompt ID."""
        selected = self.prompt_table.selection()
        return selected[0] if selected else None

    def current_run_dir(self) -> Path | None:
        """Return selected run directory."""
        selected = self.selected_run.get()
        path = Path(selected) if selected else None
        return path if path and path.exists() else None

    def _set_text(self, widget: ScrolledText, text: str) -> None:
        """Replace a text widget's content."""
        widget.delete("1.0", "end")
        widget.insert("1.0", text)

    def _schedule_refresh(self) -> None:
        """Periodically refresh process output and selected-run analysis."""
        self.refresh_process_log()
        self.refresh_analysis(self.current_run_dir())
        self.root.after(3000, self._schedule_refresh)


class AnalysisReport:
    """Live-analysis display payload."""

    def __init__(self, summary: str, body: str) -> None:
        """Store one summary line and full report body."""
        self.summary = summary
        self.body = body


def parse_int(value: str, field_name: str) -> int:
    """Parse a positive integer form field."""
    try:
        parsed = int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc
    if parsed < 1:
        raise ValueError(f"{field_name} must be >= 1.")
    return parsed


def parse_optional_int(value: str, field_name: str) -> int | None:
    """Parse an optional integer form field."""
    stripped = str(value).strip()
    if not stripped or stripped.lower() == "none":
        return None
    return parse_int(stripped, field_name)


def parse_optional_nonnegative_int(value: str, field_name: str) -> int | None:
    """Parse an optional integer field that may be zero."""
    stripped = str(value).strip()
    if not stripped or stripped.lower() == "none":
        return None
    try:
        parsed = int(stripped)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc
    if parsed < 0:
        raise ValueError(f"{field_name} must be >= 0.")
    return parsed


def parse_float(value: str, field_name: str) -> float:
    """Parse a non-negative float form field."""
    try:
        parsed = float(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a number.") from exc
    if parsed < 0:
        raise ValueError(f"{field_name} must be >= 0.")
    return parsed


def parse_csv_values(value: str) -> list[str]:
    """Parse comma-separated text into non-empty values."""
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_target_list(value: Any) -> list[str]:
    """Normalize target opponent config values into a list."""
    if isinstance(value, str):
        return parse_csv_values(value)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def objective_key_for_target(target: str | None, index: int) -> str:
    """Return the stable objective key used by the MicroRTS evaluator."""
    if target is None:
        return f"objective_{index}"
    short_name = str(target).split(".")[-1]
    return short_name or f"objective_{index}"


def first_output_line_index(lines: list[str]) -> int | None:
    """Return the first OUTPUT/OUPUT marker line index."""
    for index, line in enumerate(lines):
        if line.strip().upper() in {"OUTPUT:", "OUPUT:"}:
            return index
    return None


def parse_feature_units(lines: list[str]) -> list[dict[str, Any]]:
    """Parse prompt feature-location lines into unit dictionaries."""
    units: list[dict[str, Any]] = []
    pattern = re.compile(r"^\((\d+),\s*(\d+)\)\s+(Ally|Enemy|Neutral)\s+(.+?)\s+\{(.*)\}")
    for line in lines:
        match = pattern.match(line.strip())
        if not match:
            continue
        x, y, owner, kind, attrs_text = match.groups()
        units.append(
            {
                "position": (int(x), int(y)),
                "owner": owner,
                "kind": kind,
                "unit_type": unit_type_from_kind(kind),
                "attrs": parse_feature_attrs(attrs_text),
            }
        )
    return units


def parse_feature_attrs(attrs_text: str) -> dict[str, Any]:
    """Parse simple feature attributes from a prompt feature line."""
    attrs: dict[str, Any] = {}
    for part in attrs_text.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"')
        if value.lstrip("-").isdigit():
            attrs[key] = int(value)
        else:
            attrs[key] = value
    return attrs


def unit_type_from_kind(kind: str) -> str:
    """Convert prompt unit kind text into raw_move unit type text."""
    lowered = kind.lower()
    for suffix in (" unit", " node"):
        if lowered.endswith(suffix):
            lowered = lowered[: -len(suffix)]
    return lowered.replace(" ", "_")


def unit_display_name(unit: dict[str, Any]) -> str:
    """Return one compact combobox label for a state unit."""
    x, y = unit["position"]
    return f"({x},{y}) {unit['owner']} {unit['kind']}"


def unit_coordinate(unit: dict[str, Any]) -> str:
    """Return only the unit coordinate for compact GUI selection."""
    x, y = unit["position"]
    return f"({x},{y})"


def build_training_example_move(command: str, unit: dict[str, Any], units: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Build a legal-format JSON move object from one command and selected unit."""
    if command not in legal_training_example_commands(unit, units):
        return None
    unit_type = str(unit["unit_type"])
    position = tuple(unit["position"])
    if command == "idle":
        raw_move = f"{format_position(position)}: {unit_type} idle()"
        action_type = "idle"
    elif command == "move":
        target = nearest_empty_adjacent(position, units)
        raw_move = f"{format_position(position)}: {unit_type} move({format_position(target)})"
        action_type = "move"
    elif command == "train_worker":
        if unit_type != "base":
            return None
        raw_move = f"{format_position(position)}: base train(worker)"
        action_type = "train"
    elif command in {"train_light", "train_heavy", "train_ranged"}:
        if unit_type != "barracks":
            return None
        trained_type = command.removeprefix("train_")
        raw_move = f"{format_position(position)}: barracks train({trained_type})"
        action_type = "train"
    elif command == "build_barracks":
        if unit_type != "worker":
            return None
        raw_move = f"{format_position(position)}: worker build({format_position(adjacent_position(position))}, barracks)"
        action_type = "build"
    elif command == "harvest":
        if unit_type != "worker":
            return None
        resource = nearest_unit(position, units, owner="Neutral", kind_contains="Resource")
        base = nearest_unit(position, units, owner="Ally", kind_contains="Base")
        if resource is None or base is None:
            return None
        raw_move = f"{format_position(position)}: worker harvest({format_position(resource['position'])},{format_position(base['position'])})"
        action_type = "harvest"
    elif command == "attack":
        target = nearest_unit(position, units, owner="Enemy")
        if target is None:
            return None
        raw_move = f"{format_position(position)}: {unit_type} attack({format_position(target['position'])})"
        action_type = "attack"
    else:
        return None
    return {
        "raw_move": raw_move,
        "unit_position": list(position),
        "unit_type": unit_type,
        "action_type": action_type,
    }


def legal_training_example_commands(
    unit: dict[str, Any] | None,
    units: list[dict[str, Any]] | None = None,
) -> tuple[str, ...]:
    """Return legal command choices from the six MicroRTS action families."""
    if unit is None:
        return ()
    units = units or []
    unit_type = str(unit.get("unit_type", ""))
    owner = str(unit.get("owner", ""))
    if owner != "Ally":
        return ()
    if unit_type == "base":
        resources = int((unit.get("attrs") or {}).get("resources", 0))
        return ("train_worker",) if resources >= 1 else ()
    if unit_type == "barracks":
        resources = ally_base_resources(units)
        commands = []
        if resources >= 2:
            commands.extend(["train_light", "train_ranged"])
        if resources >= 3:
            commands.append("train_heavy")
        return tuple(commands)
    if unit_type == "worker":
        commands = ["move"]
        if ally_base_resources(units) >= 5:
            commands.append("build_barracks")
        commands.extend(["harvest", "attack", "idle"])
        return tuple(commands)
    if unit_type in {"light", "heavy", "ranged"}:
        return ("move", "attack", "idle")
    return ("idle",)


def ally_base_resources(units: list[dict[str, Any]]) -> int:
    """Return current ally base resources parsed from the state."""
    for unit in units:
        if unit.get("owner") == "Ally" and unit.get("unit_type") == "base":
            try:
                return int((unit.get("attrs") or {}).get("resources", 0))
            except (TypeError, ValueError):
                return 0
    return 0


def nearest_unit(
    position: tuple[int, int],
    units: list[dict[str, Any]],
    *,
    owner: str | None = None,
    kind_contains: str | None = None,
) -> dict[str, Any] | None:
    """Return nearest parsed feature matching filters."""
    candidates = []
    for unit in units:
        if owner is not None and unit["owner"] != owner:
            continue
        if kind_contains is not None and kind_contains not in unit["kind"]:
            continue
        candidates.append(unit)
    if not candidates:
        return None
    return min(candidates, key=lambda unit: manhattan(position, unit["position"]))


def manhattan(left: tuple[int, int], right: tuple[int, int]) -> int:
    """Return Manhattan distance between two grid positions."""
    return abs(int(left[0]) - int(right[0])) + abs(int(left[1]) - int(right[1]))


def adjacent_position(position: tuple[int, int]) -> tuple[int, int]:
    """Return a deterministic adjacent build location."""
    x, y = position
    return (min(7, x + 1), y)


def nearest_empty_adjacent(position: tuple[int, int], units: list[dict[str, Any]]) -> tuple[int, int]:
    """Return a deterministic adjacent location not occupied by parsed features."""
    x, y = position
    occupied = {tuple(unit["position"]) for unit in units}
    for candidate in ((x + 1, y), (x, y + 1), (x - 1, y), (x, y - 1)):
        cx, cy = max(0, min(7, candidate[0])), max(0, min(7, candidate[1]))
        if (cx, cy) not in occupied:
            return (cx, cy)
    return position


def format_position(position: tuple[int, int]) -> str:
    """Format a MicroRTS coordinate."""
    return f"({int(position[0])},{int(position[1])})"


def append_move_to_example_lines(lines: list[str], move: dict[str, Any]) -> list[str]:
    """Append one JSON move object to an example OUTPUT block."""
    if first_output_line_index(lines) is None:
        return [
            *lines,
            "",
            "OUTPUT:",
            "{",
            f'  "thinking": "{build_thinking_prefix(parse_feature_units(lines))}; reason=...",',
            '  "moves": [',
            *move_json_lines(move),
            "  ]",
            "}",
        ]
    closing_index = find_moves_closing_index(lines)
    if closing_index is None:
        return [*lines, '  "moves": [', *move_json_lines(move), "  ]", "}"]
    output = list(lines)
    previous = previous_non_empty_index(output, closing_index)
    if previous is not None and output[previous].strip() == "}":
        output[previous] = output[previous] + ","
    for offset, move_line in enumerate(move_json_lines(move)):
        output.insert(closing_index + offset, move_line)
    return output


def apply_thinking_prefix(lines: list[str]) -> list[str]:
    """Update thinking fields before reason while preserving the reason text."""
    prefix = build_thinking_prefix(parse_feature_units(lines))
    reason = "..."
    for line in lines:
        if '"thinking"' not in line:
            continue
        match = re.search(r"reason=([^\";]+(?:;[^\";]+)*)", line)
        if match:
            reason = match.group(1).rstrip(",")
        break
    thinking_line = f'  "thinking": "{prefix}; reason={reason}",'
    output = list(lines)
    for index, line in enumerate(output):
        if '"thinking"' in line:
            output[index] = thinking_line
            return output
    output_index = first_output_line_index(output)
    insert_index = output_index + 2 if output_index is not None and output_index + 1 < len(output) else len(output)
    output.insert(insert_index, thinking_line)
    return output


def build_thinking_prefix(units: list[dict[str, Any]]) -> str:
    """Build the non-reason thinking fields from parsed state units."""
    workers = [
        unit for unit in units
        if unit.get("owner") == "Ally" and unit.get("unit_type") == "worker"
    ]
    worker_count = len(workers)
    worker_status = "less_than_2" if worker_count < 2 else "enough_workers"
    has_ally_barracks = any(
        unit.get("owner") == "Ally" and unit.get("unit_type") == "barracks"
        for unit in units
    )
    builder = "none"
    if worker_count >= 2 and not has_ally_barracks:
        builder_unit = workers[1]
        builder = format_position(builder_unit["position"])
    if worker_count < 2:
        decision = "train_worker"
    elif not has_ally_barracks:
        decision = "build_barracks_with_worker_2"
    else:
        decision = "train_army_or_attack"
    return (
        f"worker_count={worker_count}; "
        f"worker_status={worker_status}; "
        f"has_ally_barracks={has_ally_barracks}; "
        f"builder={builder}; "
        f"decision={decision}"
    )


def find_moves_closing_index(lines: list[str]) -> int | None:
    """Find the closing bracket for the moves array in an example output."""
    seen_moves = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if '"moves"' in stripped:
            seen_moves = True
            continue
        if seen_moves and stripped == "]":
            return index
    return None


def previous_non_empty_index(lines: list[str], before_index: int) -> int | None:
    """Return the previous non-empty line index."""
    for index in range(before_index - 1, -1, -1):
        if lines[index].strip():
            return index
    return None


def move_json_lines(move: dict[str, Any]) -> list[str]:
    """Format one move as the prompt JSON object style."""
    x, y = move["unit_position"]
    return [
        "    {",
        f'      "raw_move": "{move["raw_move"]}",',
        f'      "unit_position": [{x},{y}],',
        f'      "unit_type": "{move["unit_type"]}",',
        f'      "action_type": "{move["action_type"]}"',
        "    }",
    ]


def normalize_probability_map(weights: dict[str, float], field_name: str) -> None:
    """Normalize one non-empty probability map in-place."""
    total = sum(weights.values())
    if total <= 0:
        raise ValueError(f"{field_name} must have a positive total weight.")
    for key in list(weights):
        weights[key] = weights[key] / total


def resolve_repo_path(path_text: str) -> Path:
    """Resolve a path against the repository root when it is relative."""
    path = Path(path_text)
    return path if path.is_absolute() else ROOT / path


def relative_or_absolute(path: Path) -> str:
    """Return a repository-relative path when possible."""
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def read_tail(path: Path, limit: int) -> str:
    """Read a text file tail."""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[-limit:]


def load_json_file(path: Path) -> dict[str, Any]:
    """Load one JSON mapping, returning an empty mapping on missing or invalid data."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_population(run_dir: Path) -> list[dict[str, Any]]:
    """Load the latest checkpointed population."""
    run_state = load_json_file(run_dir / "run_state.json")
    population = run_state.get("population")
    return list(population) if isinstance(population, list) else []


def load_checkpoint_rows(run_dir: Path) -> list[dict[str, Any]]:
    """Load generation rows from checkpoints.jsonl."""
    path = run_dir / "checkpoints.jsonl"
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        generation = payload.get("generation")
        phase = payload.get("phase")
        for item in payload.get("population") or []:
            rows.append({"generation": generation, "phase": phase, "individual": item})
    return rows


def load_prompts(run_dir: Path | None) -> dict[str, str]:
    """Extract prompt text from generation logs and run state."""
    if run_dir is None:
        return {}
    prompts: dict[str, str] = {}
    for path in sorted(run_dir.glob("generation*.txt")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for index, block in enumerate(text.split("Prompt:\n")[1:], start=1):
            prompt = block.split("\nIndividual(", 1)[0].split("\nPopulation", 1)[0].strip()
            if prompt:
                prompts[f"{path.stem}_{index}"] = prompt
    for item in load_population(run_dir):
        prompt = item.get("rendered_prompt")
        if prompt:
            prompts[str(item.get("id") or len(prompts))] = str(prompt)
    return prompts


def build_live_analysis_report(run_dir: Path) -> AnalysisReport:
    """Build a live GA/MO analysis report from existing run artifacts."""
    config = load_json_file(run_dir / "config.json")
    run_state = load_json_file(run_dir / "run_state.json")
    algorithm = str(config.get("algorithm") or run_state.get("algorithm") or "unknown")
    normalized_algorithm = algorithm.lower()
    mode = "GA" if normalized_algorithm in GA_ALGORITHMS else "MO"
    population = load_population(run_dir)
    checkpoint_rows = load_checkpoint_rows(run_dir)
    latest_generation = latest_value([row.get("generation") for row in checkpoint_rows])
    phase = str(run_state.get("phase") or latest_value([row.get("phase") for row in checkpoint_rows]) or "unknown")

    lines = [
        f"Run: {run_dir}",
        f"Algorithm: {algorithm} ({mode})",
        f"Current generation: {latest_generation if latest_generation is not None else 'unknown'}",
        f"Current phase: {phase}",
        f"Population records: {len(population)}",
        f"Checkpoint fitness rows: {len(checkpoint_rows)}",
        "",
    ]
    lines.extend(operator_usage_lines(population, checkpoint_rows))
    lines.append("")
    if mode == "GA":
        lines.extend(ga_analysis_lines(population, checkpoint_rows))
    else:
        lines.extend(mo_analysis_lines(population, checkpoint_rows))

    summary = f"{mode} | generation={latest_generation if latest_generation is not None else 'unknown'} | phase={phase}"
    return AnalysisReport(summary=summary, body="\n".join(lines))


def latest_value(values: list[Any]) -> Any:
    """Return the last non-empty value from a list."""
    for value in reversed(values):
        if value not in (None, ""):
            return value
    return None


def fitness_values(fitness: Any) -> list[float]:
    """Normalize fitness payloads to an ordered float list."""
    if isinstance(fitness, dict):
        return [float(value) for _, value in sorted(fitness.items()) if is_number(value)]
    if isinstance(fitness, list):
        return [float(value) for value in fitness if is_number(value)]
    if is_number(fitness):
        return [float(fitness)]
    return []


def is_number(value: Any) -> bool:
    """Return whether value can be interpreted as a finite float."""
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def scalar_score(individual: dict[str, Any]) -> float | None:
    """Return the GA scalar score; the first objective is the canonical scalar."""
    values = fitness_values(individual.get("fitness"))
    return values[0] if values else None


def operator_usage_lines(population: list[dict[str, Any]], checkpoint_rows: list[dict[str, Any]]) -> list[str]:
    """Summarize operator and mutation usage from available metadata."""
    items = list(population)
    items.extend(row["individual"] for row in checkpoint_rows)
    operator_counter: Counter[str] = Counter()
    mutation_counter: Counter[str] = Counter()
    for item in items:
        profile = item.get("operator_profile") or {}
        mutation_metadata = item.get("mutation_metadata") or {}
        operator_type = profile.get("operator_type")
        mutation_mode = profile.get("mutation_mode") or mutation_metadata.get("mutation_mode")
        if operator_type:
            operator_counter[str(operator_type)] += 1
        if mutation_mode:
            mutation_counter[str(mutation_mode)] += 1
    lines = ["Operator usage:"]
    lines.append("  operators: " + (", ".join(f"{key}={value}" for key, value in operator_counter.items()) or "none"))
    lines.append("  mutation modes: " + (", ".join(f"{key}={value}" for key, value in mutation_counter.items()) or "none"))
    return lines


def ga_analysis_lines(population: list[dict[str, Any]], checkpoint_rows: list[dict[str, Any]]) -> list[str]:
    """Build GA first-objective analysis lines."""
    lines = ["GA analysis:"]
    if population:
        scored = [(scalar_score(item), item) for item in population]
        scored = [(score, item) for score, item in scored if score is not None]
        if scored:
            best_score, best = max(scored, key=lambda pair: pair[0])
            lines.append(f"  current best first objective: {best_score:.4f} id={best.get('id')}")
    generation_best: dict[Any, float] = {}
    for row in checkpoint_rows:
        score = scalar_score(row["individual"])
        if score is None:
            continue
        generation = row.get("generation")
        generation_best[generation] = max(score, generation_best.get(generation, score))
    if generation_best:
        lines.append("  best by generation:")
        for generation in sorted(generation_best, key=lambda value: (value is None, value)):
            lines.append(f"    gen {generation}: {generation_best[generation]:.4f}")
    else:
        lines.append("  no GA fitness history found yet")
    return lines


def mo_analysis_lines(population: list[dict[str, Any]], checkpoint_rows: list[dict[str, Any]]) -> list[str]:
    """Build MO Pareto-front analysis lines."""
    lines = ["MO analysis:"]
    active_population = population or [row["individual"] for row in checkpoint_rows]
    vectors = [(fitness_values(item.get("fitness")), item) for item in active_population]
    vectors = [(values, item) for values, item in vectors if len(values) >= 2]
    if not vectors:
        lines.append("  no two-objective fitness data found yet")
        return lines
    front = nondominated_front(vectors)
    lines.append(f"  objective count: {len(vectors[0][0])}")
    lines.append(f"  non-dominated front size: {len(front)}")
    lines.append("  front sample:")
    for values, item in front[:20]:
        vector_text = ", ".join(f"{value:.4f}" for value in values)
        lines.append(f"    id={item.get('id')} fitness=[{vector_text}]")
    return lines


def nondominated_front(vectors: list[tuple[list[float], dict[str, Any]]]) -> list[tuple[list[float], dict[str, Any]]]:
    """Return maximization non-dominated front for fitness vectors."""
    front: list[tuple[list[float], dict[str, Any]]] = []
    for values, item in vectors:
        dominated = False
        for other_values, _other_item in vectors:
            if other_values is values:
                continue
            if dominates(other_values, values):
                dominated = True
                break
        if not dominated:
            front.append((values, item))
    return front


def dominates(left: list[float], right: list[float]) -> bool:
    """Return whether left Pareto-dominates right under maximization."""
    pairs = list(zip(left, right))
    return bool(pairs) and all(a >= b for a, b in pairs) and any(a > b for a, b in pairs)


def main() -> None:
    """Launch the native desktop GUI."""
    root = Tk()
    EagleDesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
