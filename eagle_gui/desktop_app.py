"""Native desktop GUI for configuring, launching, and monitoring EAGLE runs."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from tkinter import BooleanVar, PhotoImage, StringVar, Tk, filedialog, messagebox, simpledialog
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from eagle.config import normalize_algorithm_name
from eagle.eval.microrts.state_generator import StateGenerator
from eagle.envs.microrts.runner import save_prompt, set_config_property
from eagle.objectives.registry import get_objectives, list_objective_names, normalize_objective_key
from eagle.operators.registry import list_operator_names
from eagle.utils.log_parse import parse_log_file
from eagle.utils.component_pool import ComponentPool


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "configs" / "evolution"
EXPERIMENT_DIR = ROOT / "configs" / "experiments"
LOG_DIR = ROOT / "logs" / "eagle"
GUI_PROCESS_STATE_PATH = LOG_DIR / "gui_process_state.json"
APP_ICON = ROOT / "assets" / "eagle.png"
DEFAULT_CONFIG = CONFIG_DIR / "default.json"
APPLICATION_CHOICES = ("microrts",)
ALGORITHM_CHOICES = ("ga", "nsga2", "ga_surrogate")
EVALUATOR_CHOICES = ("gameplay",)
SURROGATE_CHOICES = ("round", "policy_agent", "java_agent")
MICRORTS_OPPONENT_CHOICES = (
    "ai.abstraction.HeavyRush",
    "ai.abstraction.LightRush",
    "ai.RandomBiasedAI",
    "ai.RandomAI",
    "ai.PassiveAI",
)
GA_ALGORITHMS = {"ga", "ga_surrogate"}
SURROGATE_ALGORITHMS = {"ga_surrogate"}
PARENT_SELECTION_BY_ALGORITHM = {
    "ga": "ga_fitness_tournament",
    "ga_surrogate": "ga_fitness_tournament",
    "nsga2": "nsga2_tournament",
}
ENV_SELECTION_BY_ALGORITHM = {
    "ga": "ga_fitness_elitism",
    "ga_surrogate": "ga_fitness_elitism",
    "nsga2": "nsga2_environmental",
}
SURROGATE_PATH_LINES = (
    "round: fast local MicroRTS round evaluator used inside GA Surrogate",
    "eaglePolicy.java: reusable fixed policy template -> ai.abstraction.eaglePolicy",
    "eagleJava.java: generated Java with the same policy behavior -> ai.abstraction.eagleJava",
)

# File layout guide:
# - EagleDesktopApp.__init__ stores Tk variables and process handles.
# - _build_* methods create visible tabs and side-panel controls.
# - sync/refresh methods keep GUI selections consistent with available algorithm modes.
# - component_* and training_example_* methods own component JSON editing.
# - render/save prompt methods bridge component JSON, prompt preview, and Java prompt.txt.
# - start/launch/refresh methods run Python EAGLE or visible Java MicroRTS processes.
# - module-level helpers parse prompt text, load run artifacts, and format live analysis.


class EagleDesktopApp:
    """Tkinter application for the native EAGLE desktop workflow."""

    def __init__(self, root: Tk) -> None:
        """Create the desktop window and bind periodic refreshes."""
        self.root = root
        self.root.title("EAGLE Desktop")
        self.root.minsize(1020, 680)
        self.maximize_window()
        self.window_icon = None
        if APP_ICON.exists():
            self.window_icon = PhotoImage(file=str(APP_ICON))
            root.iconphoto(True, self.window_icon)

        # Long-running child processes are tracked separately so experiment runs and
        # visible Java MicroRTS runs can be started/stopped independently.
        self.process: subprocess.Popen | None = None
        self.monitored_process_pid: int | None = None
        self.process_log_path: Path | None = None
        self.microrts_gui_process: subprocess.Popen | None = None
        self.microrts_gui_log_path: Path | None = None
        self.generated_config_path: Path | None = None

        # Component editor state owns the JSON payload and prompt-builder candidate selection.
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
        self.training_example_sample_min = StringVar(value="0")
        self.training_example_sample_max = StringVar(value="4")
        self.training_example_fixed_sample_count = StringVar(value="4")
        self.training_example_fixed_count = BooleanVar(value=False)
        self.training_example_units: list[dict[str, Any]] = []
        self.selected_run = StringVar(value="")
        self.status = StringVar(value="Ready")

        # Algorithm settings mirror the JSON config schema produced by build_config_payload().
        self.application = StringVar(value="microrts")
        self.algorithm = StringVar(value="nsga2")
        self.evaluator = StringVar(value="gameplay")
        self.surrogate = StringVar(value="round")
        self.population_size = StringVar(value="10")
        self.num_generations = StringVar(value="50")
        self.tick_limit = StringVar(value="5000")
        self.llm_call_limit = StringVar(value="50")
        self.gameplay_map_dir = StringVar(value="8x8")
        self.gameplay_rate = StringVar(value="0.25")
        self.gameplay_refresh_interval = StringVar(value="5")
        self.surrogate_top_ratio = StringVar(value="0.3")
        self.archive_parent_ratio = StringVar(value="0.25")
        self.one_eval_rounds = StringVar(value="8")
        self.round_eval_parallel_workers = StringVar(value="8")
        self.agent_eval_parallel_workers = StringVar(value="8")
        self.individual_eval_parallel_workers = StringVar(value="8")
        self.llm_parallel_workers = StringVar(value="8")
        self.final_test_max_front = StringVar(value="1")
        self.selection_method = StringVar(value="random")
        self.parent_selection_operator = StringVar(value=PARENT_SELECTION_BY_ALGORITHM["nsga2"])
        self.tournament_size = StringVar(value="3")
        self.crossover = StringVar(value="uniform")
        self.crossover_operator = StringVar(value="uniform")
        self.mutation_operator = StringVar(value="mix")
        self.env_selection_operator = StringVar(value=ENV_SELECTION_BY_ALGORITHM["nsga2"])
        self.crossover_repair_enabled = BooleanVar(value=True)
        self.enable_reflection_operator = BooleanVar(value=True)
        self.skip_final_test = BooleanVar(value=False)
        self.quick_run = BooleanVar(value=False)
        self.precompile_python = BooleanVar(value=False)
        self.opponents_text = StringVar(value="ai.abstraction.LightRush, ai.abstraction.HeavyRush")
        self.objective_mode = StringVar(value="multi")
        self.single_objective = StringVar(value="resource_advantage")
        self.objective_weights: dict[str, StringVar] = {}
        self.multi_objectives: dict[str, BooleanVar] = {}
        self.objective_targets: list[str] = ["ai.abstraction.LightRush", "ai.abstraction.HeavyRush"]
        self.objective_detail = StringVar(value="Select an objective to inspect its calculation.")

        # Java GUI settings are separate from experiment settings; they patch the vendored
        # MicroRTS config only when launching a visible Java game.
        self.microrts_gui_status = StringVar(value="Java GUI not running")
        self.microrts_gui_opponent = StringVar(value="ai.abstraction.HeavyRush")
        self.microrts_gui_map_dir = StringVar(value="8x8")
        self.microrts_gui_map_file = StringVar(value="basesWorkers8x8.xml")
        self.microrts_gui_update_interval = StringVar(value="50")
        self.microrts_gui_llm_interval = StringVar(value="1")
        self.microrts_gui_save_trace = BooleanVar(value=False)
        self.selected_trace = StringVar(value="")

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

        self.main_layout = ttk.Frame(root)
        self.main_layout.pack(fill="both", expand=True, padx=10, pady=10)
        self.main_layout.columnconfigure(0, weight=2, uniform="main")
        self.main_layout.columnconfigure(1, weight=1, uniform="main")
        self.main_layout.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(self.main_layout)
        self.notebook.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.algorithm_panel = ttk.LabelFrame(self.main_layout, text="Algorithm", padding=10)
        self.algorithm_panel.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        self._build_component_tab()
        self._build_flow_tab()
        self._build_objectives_tab()
        self._build_operators_tab()
        self._build_run_tab()
        self._build_analysis_tab()
        self._build_timing_tab()
        self._build_prompt_tab()
        self._build_java_gui_tab()

        self.load_base_config_into_form()
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)
        self.refresh_runs()
        self.attach_existing_process()
        self._schedule_refresh()

    # ------------------------------------------------------------------
    # Window and tab construction
    # ------------------------------------------------------------------

    def maximize_window(self) -> None:
        """Open the GUI maximized, with a portable geometry fallback."""
        try:
            self.root.state("zoomed")
            return
        except Exception:
            pass

        try:
            self.root.attributes("-zoomed", True)
            return
        except Exception:
            pass

        width = self.root.winfo_screenwidth()
        height = self.root.winfo_screenheight()
        self.root.geometry(f"{width}x{height}+0+0")

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
        editor.rowconfigure(5, weight=1)
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
        ttk.Button(actions, text="Add candidate", command=self.add_component_candidate).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Delete candidate", command=self.delete_component_candidate).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Save JSON", command=self.save_component_json).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Save as components file", command=self.save_component_json_as).pack(side="left", padx=(8, 0))

        self.move_builder = ttk.LabelFrame(editor, text="Move Builder", padding=8)
        self.move_builder.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.move_builder.columnconfigure(1, weight=0)
        self.move_builder.columnconfigure(3, weight=0)
        self.move_builder.columnconfigure(4, weight=1)

        sample_controls = ttk.Frame(self.move_builder)
        sample_controls.grid(row=0, column=0, columnspan=5, sticky="ew")
        sample_controls.columnconfigure(3, weight=1)
        ttk.Checkbutton(
            sample_controls,
            text="Fixed example count",
            variable=self.training_example_fixed_count,
            command=self.refresh_training_example_sampling_controls,
        ).grid(row=0, column=0, sticky="w")
        self.training_example_range_frame = ttk.Frame(sample_controls)
        self.training_example_range_frame.grid(row=0, column=1, sticky="w", padx=(16, 0))
        ttk.Label(self.training_example_range_frame, text="Sample range").pack(side="left")
        ttk.Label(self.training_example_range_frame, text="A").pack(side="left", padx=(8, 0))
        ttk.Entry(
            self.training_example_range_frame,
            textvariable=self.training_example_sample_min,
            width=4,
        ).pack(side="left", padx=(4, 0))
        ttk.Label(self.training_example_range_frame, text="B").pack(side="left", padx=(8, 0))
        ttk.Entry(
            self.training_example_range_frame,
            textvariable=self.training_example_sample_max,
            width=4,
        ).pack(side="left", padx=(4, 0))
        self.training_example_fixed_frame = ttk.Frame(sample_controls)
        self.training_example_fixed_frame.grid(row=0, column=1, sticky="w", padx=(16, 0))
        ttk.Label(self.training_example_fixed_frame, text="Sample count").pack(side="left")
        ttk.Entry(
            self.training_example_fixed_frame,
            textvariable=self.training_example_fixed_sample_count,
            width=8,
        ).pack(side="left", padx=(8, 0))
        self.training_example_sample_min.trace_add("write", self.on_training_example_sampling_changed)
        self.training_example_sample_max.trace_add("write", self.on_training_example_sampling_changed)
        self.training_example_fixed_sample_count.trace_add("write", self.on_training_example_sampling_changed)
        self.refresh_training_example_sampling_controls()

        ttk.Button(self.move_builder, text="Random state", command=self.generate_training_example_state).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Button(self.move_builder, text="Refresh units", command=self.refresh_training_example_units).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0)
        )
        ttk.Label(self.move_builder, text="Unit").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.training_example_unit_combo = ttk.Combobox(
            self.move_builder,
            textvariable=self.training_example_unit,
            state="readonly",
            values=(),
            width=10,
        )
        self.training_example_unit_combo.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
        self.training_example_unit_combo.bind("<<ComboboxSelected>>", self.update_training_example_move_preview)

        ttk.Label(self.move_builder, text="Command").grid(row=2, column=2, sticky="w", padx=(16, 0), pady=(8, 0))
        self.training_example_command_combo = ttk.Combobox(
            self.move_builder,
            textvariable=self.training_example_command,
            state="readonly",
            values=(),
            width=18,
        )
        self.training_example_command_combo.grid(row=2, column=3, sticky="w", padx=(8, 0), pady=(8, 0))
        self.training_example_command_combo.bind("<<ComboboxSelected>>", self.update_training_example_move_preview)

        ttk.Button(self.move_builder, text="Append move", command=self.append_training_example_move).grid(
            row=2, column=4, sticky="w", padx=(12, 0), pady=(8, 0)
        )
        ttk.Label(
            self.move_builder,
            textvariable=self.training_example_current_move,
            wraplength=640,
            justify="left",
        ).grid(row=3, column=0, columnspan=5, sticky="ew", pady=(8, 0))
        self.refresh_move_builder_visibility()

        self.component_editor = ScrolledText(editor, wrap="word", height=18)
        self.component_editor.grid(row=5, column=0, columnspan=2, sticky="nsew")

        preview = ttk.LabelFrame(workspace, text="Prompt Builder", padding=8)
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)
        preview.rowconfigure(3, weight=1)
        workspace.add(preview, weight=1)

        self.component_selection_table = ttk.Treeview(
            preview,
            columns=("component", "static", "candidate", "candidate_count", "lines"),
            show="headings",
            selectmode="browse",
            height=9,
        )
        self.component_selection_table.heading("component", text="Component")
        self.component_selection_table.heading("static", text="Static")
        self.component_selection_table.heading("candidate", text="Candidate")
        self.component_selection_table.heading("candidate_count", text="Count")
        self.component_selection_table.heading("lines", text="Lines")
        self.component_selection_table.column("component", width=190, anchor="w")
        self.component_selection_table.column("static", width=70, anchor="center")
        self.component_selection_table.column("candidate", width=90, anchor="center")
        self.component_selection_table.column("candidate_count", width=70, anchor="center")
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
        ttk.Button(builder_actions, text="Add component", command=self.add_component_category).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(builder_actions, text="Delete component", command=self.delete_component_category).pack(
            side="left", padx=(8, 0)
        )
        rendered_prompt_header = ttk.Frame(preview)
        rendered_prompt_header.grid(row=2, column=0, sticky="ew")
        ttk.Label(rendered_prompt_header, text="Rendered prompt").pack(side="left")
        ttk.Button(
            rendered_prompt_header,
            text="Copy current prompt",
            command=self.copy_current_prompt,
        ).pack(side="right")
        self.component_prompt_output = ScrolledText(preview, wrap="word", height=14)
        self.component_prompt_output.grid(row=3, column=0, sticky="nsew", pady=(4, 0))

    def _build_flow_tab(self) -> None:
        """Build the fixed right-side algorithm and flow controls."""
        tab = self.algorithm_panel
        for column in (1, 3):
            tab.columnconfigure(column, weight=1)

        application_combo = self._labeled_combo(tab, "Application", self.application, APPLICATION_CHOICES, 0, 0)
        application_combo.bind("<<ComboboxSelected>>", self.on_objective_mode_selected)
        evaluator_combo = self._labeled_combo(tab, "Eval mode", self.evaluator, EVALUATOR_CHOICES, 0, 2)
        evaluator_combo.bind("<<ComboboxSelected>>", self.on_evaluator_selected)
        self.surrogate_controls_frame = ttk.Frame(tab)
        self.surrogate_controls_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.surrogate_controls_frame.columnconfigure(1, weight=1)
        surrogate_combo = self._labeled_combo(self.surrogate_controls_frame, "Surrogate", self.surrogate, SURROGATE_CHOICES, 0, 0)
        surrogate_combo.bind("<<ComboboxSelected>>", self.on_surrogate_selected)
        algorithm_combo = self._labeled_combo(tab, "Algorithm", self.algorithm, ALGORITHM_CHOICES, 1, 2)
        algorithm_combo.bind("<<ComboboxSelected>>", self.on_algorithm_selected)
        self._labeled_entry(tab, "Config name", self.config_name, 2, 0)
        self._labeled_entry(tab, "Population size", self.population_size, 2, 2)
        self._labeled_entry(tab, "Generations", self.num_generations, 3, 0)
        self.game_seconds_frame = ttk.Frame(tab)
        self.game_seconds_frame.grid(row=3, column=2, columnspan=2, sticky="ew")
        self.game_seconds_frame.columnconfigure(1, weight=1)
        self._labeled_entry(self.game_seconds_frame, "Tick limit", self.tick_limit, 0, 0)
        self._labeled_entry(self.game_seconds_frame, "LLM call limit", self.llm_call_limit, 0, 2)
        eval_map_combo = self._labeled_combo(
            self.game_seconds_frame,
            "Eval map folder",
            self.gameplay_map_dir,
            microrts_map_dir_choices(),
            1,
            0,
        )
        eval_map_combo.configure(state="readonly")
        self.surrogate_algorithm_frame = ttk.Frame(tab)
        self.surrogate_algorithm_frame.grid(row=4, column=0, columnspan=4, sticky="ew")
        self.surrogate_algorithm_frame.columnconfigure(1, weight=1)
        self.surrogate_algorithm_frame.columnconfigure(3, weight=1)
        self._labeled_entry(
            self.surrogate_algorithm_frame,
            "gameplay_refresh_interval",
            self.gameplay_refresh_interval,
            0,
            0,
        )
        self._labeled_entry(
            self.surrogate_algorithm_frame,
            "surrogate_top_ratio",
            self.surrogate_top_ratio,
            0,
            2,
        )
        self._labeled_entry(
            self.surrogate_algorithm_frame,
            "archive_parent_ratio",
            self.archive_parent_ratio,
            1,
            0,
        )
        self._labeled_entry(
            self.surrogate_algorithm_frame,
            "one_eval_rounds",
            self.one_eval_rounds,
            1,
            2,
        )
        self._labeled_entry(
            self.surrogate_algorithm_frame,
            "round_eval_parallel_workers",
            self.round_eval_parallel_workers,
            2,
            0,
        )
        self._labeled_entry(
            self.surrogate_algorithm_frame,
            "agent_eval_parallel_workers",
            self.agent_eval_parallel_workers,
            2,
            2,
        )
        self._labeled_entry(
            self.surrogate_algorithm_frame,
            "individual_eval_parallel_workers",
            self.individual_eval_parallel_workers,
            3,
            0,
        )
        self._labeled_entry(
            self.surrogate_algorithm_frame,
            "llm_parallel_workers",
            self.llm_parallel_workers,
            3,
            2,
        )
        self._labeled_entry(tab, "Final-test max front", self.final_test_max_front, 5, 0)
        self._labeled_entry(tab, "Gameplay opponents", self.opponents_text, 5, 2)
        ttk.Checkbutton(tab, text="Enable reflection operator", variable=self.enable_reflection_operator).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=4
        )
        ttk.Checkbutton(tab, text="Quick run override", variable=self.quick_run).grid(
            row=6, column=2, sticky="w", pady=4
        )
        ttk.Checkbutton(tab, text="Skip final test", variable=self.skip_final_test).grid(
            row=6, column=3, sticky="w", pady=4
        )
        ttk.Checkbutton(tab, text="Precompile Python", variable=self.precompile_python).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=4
        )

        selection_frame = ttk.LabelFrame(tab, text="Selection", padding=8)
        selection_frame.grid(row=8, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        selection_frame.columnconfigure(1, weight=1)
        ttk.Label(selection_frame, text="Mutation").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Label(selection_frame, textvariable=self.mutation_operator).grid(
            row=0, column=1, sticky="ew", padx=(8, 0), pady=4
        )
        ttk.Label(selection_frame, text="Crossover").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Label(selection_frame, textvariable=self.crossover_operator).grid(
            row=1, column=1, sticky="ew", padx=(8, 0), pady=4
        )
        self._labeled_combo(
            selection_frame,
            "Parent",
            self.parent_selection_operator,
            self.operator_choices("parent_selection"),
            2,
            0,
        )
        self._labeled_entry(selection_frame, "Tournament size", self.tournament_size, 3, 0)
        self._labeled_combo(
            selection_frame,
            "Env",
            self.env_selection_operator,
            self.operator_choices("env_selection"),
            4,
            0,
        )

        self.surrogate_paths_frame = ttk.LabelFrame(tab, text="Surrogate Paths", padding=8)
        self.surrogate_paths_frame.grid(row=9, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        for index, line in enumerate(SURROGATE_PATH_LINES):
            ttk.Label(self.surrogate_paths_frame, text=line).grid(row=index, column=0, sticky="w")

        actions = ttk.Frame(tab)
        actions.grid(row=10, column=0, columnspan=4, sticky="ew", pady=(16, 0))
        ttk.Button(actions, text="Validate settings", command=self.validate_settings).pack(side="left")
        ttk.Button(actions, text="Save generated config", command=self.save_generated_config).pack(side="left", padx=(8, 0))
        self.refresh_surrogate_visibility()

    def _build_objectives_tab(self) -> None:
        """Build objective selection controls."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Objectives")
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(2, weight=1)

        self.objective_mode_frame = ttk.Frame(tab)
        self.objective_mode_frame.grid(row=0, column=0, columnspan=4, sticky="ew")
        self.objective_mode_combo = self._labeled_combo(
            self.objective_mode_frame,
            "Mode",
            self.objective_mode,
            ("single", "weighted_mix"),
            0,
            0,
        )
        self.objective_mode_combo.bind("<<ComboboxSelected>>", self.on_objective_mode_selected)

        self.single_objective_frame = ttk.Frame(tab)
        self.single_objective_frame.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        self.single_objective_combo = self._labeled_combo(
            self.single_objective_frame,
            "Objective",
            self.single_objective,
            self.objective_choices(),
            0,
            0,
        )
        self.single_objective_combo.bind("<<ComboboxSelected>>", self.on_objective_selected)

        self.objective_table = ttk.Treeview(
            tab,
            columns=("selected", "objective", "label", "direction", "weight"),
            show="headings",
            selectmode="browse",
            height=9,
        )
        self.objective_table.heading("selected", text="Use")
        self.objective_table.heading("objective", text="Objective key")
        self.objective_table.heading("label", text="Label")
        self.objective_table.heading("direction", text="Direction")
        self.objective_table.heading("weight", text="Weight")
        self.objective_table.column("selected", width=70, anchor="center")
        self.objective_table.column("objective", width=230, anchor="w")
        self.objective_table.column("label", width=260, anchor="w")
        self.objective_table.column("direction", width=90, anchor="center")
        self.objective_table.column("weight", width=110, anchor="e")
        self.objective_table.grid(row=2, column=0, columnspan=4, sticky="nsew", pady=(12, 0))
        self.objective_table.bind("<<TreeviewSelect>>", self.on_objective_selected)
        self.objective_table.bind("<Double-1>", self.on_objective_table_double_click)

        objective_actions = ttk.Frame(tab)
        objective_actions.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Button(objective_actions, text="Toggle selected", command=self.toggle_selected_objective).pack(side="left")
        ttk.Button(objective_actions, text="Set weight", command=self.set_selected_objective_weight).pack(
            side="left", padx=(8, 0)
        )

        ttk.Label(tab, textvariable=self.objective_detail, wraplength=820, justify="left").grid(
            row=4, column=0, columnspan=4, sticky="ew", pady=(8, 0)
        )

    def _build_operators_tab(self) -> None:
        """Build mutation and crossover operator controls."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Operators")
        for column in (1, 3):
            tab.columnconfigure(column, weight=1)

        crossover_frame = ttk.LabelFrame(tab, text="Crossover", padding=8)
        crossover_frame.grid(row=0, column=0, columnspan=4, sticky="ew")
        crossover_frame.columnconfigure(1, weight=1)
        crossover_combo = self._labeled_combo(
            crossover_frame,
            "Operator",
            self.crossover_operator,
            self.operator_choices("crossover"),
            0,
            0,
        )
        crossover_combo.bind("<<ComboboxSelected>>", self.refresh_crossover_repair_visibility)
        self.crossover_repair_checkbutton = ttk.Checkbutton(
            crossover_frame,
            text="LLM repair",
            variable=self.crossover_repair_enabled,
        )
        self.crossover_repair_checkbutton.grid(
            row=1, column=0, columnspan=2, sticky="w", pady=4
        )

        mutation_frame = ttk.LabelFrame(tab, text="Mutation", padding=8)
        mutation_frame.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        for column in (1, 3):
            mutation_frame.columnconfigure(column, weight=1)
        mutation_combo = self._labeled_combo(
            mutation_frame,
            "Operator",
            self.mutation_operator,
            self.operator_choices("mutation"),
            0,
            0,
        )
        mutation_combo.bind("<<ComboboxSelected>>", self.refresh_mutation_weight_visibility)
        self.mutation_weights_frame = ttk.Frame(mutation_frame)
        self.mutation_weights_frame.grid(row=1, column=0, columnspan=4, sticky="ew")
        for column_index in (1, 3):
            self.mutation_weights_frame.columnconfigure(column_index, weight=1)
        ttk.Label(self.mutation_weights_frame, text="Mode weights").grid(
            row=0, column=0, sticky="w", pady=(14, 4)
        )
        row = 2
        column = 0
        for name in self.mutation_weight_names():
            variable = self.mutation_weights.setdefault(name, StringVar(value="0.0"))
            self._labeled_entry(
                self.mutation_weights_frame,
                name.replace("_", " "),
                variable,
                row,
                column,
            )
            column += 2
            if column > 2:
                column = 0
                row += 1
        self.refresh_crossover_repair_visibility()
        self.refresh_mutation_weight_visibility()

    def operator_choices(self, operator_type: str) -> tuple[str, ...]:
        """Return registered operator names discovered from plugin folders."""
        return list_operator_names(operator_type)

    def mutation_weight_names(self) -> tuple[str, ...]:
        """Return mutation plugins that can participate in roulette weighting."""
        excluded = {"mix"}
        return tuple(name for name in self.operator_choices("mutation") if name not in excluded)

    def refresh_mutation_weight_visibility(self, _event: object | None = None) -> None:
        """Show mutation weights only for the weighted mix operator."""
        if not hasattr(self, "mutation_weights_frame"):
            return
        if self.mutation_operator.get() == "mix":
            self.mutation_weights_frame.grid()
        else:
            self.mutation_weights_frame.grid_remove()

    def refresh_crossover_repair_visibility(self, _event: object | None = None) -> None:
        """Show LLM repair only for uniform crossover."""
        if not hasattr(self, "crossover_repair_checkbutton"):
            return
        if self.crossover_operator.get() == "uniform":
            self.crossover_repair_checkbutton.grid()
        else:
            self.crossover_repair_checkbutton.grid_remove()

    def ensure_operator_choice(self, variable: StringVar, operator_type: str, default_name: str) -> None:
        """Reset a stale operator selection to a discovered default."""
        choices = self.operator_choices(operator_type)
        if variable.get() not in choices:
            variable.set(default_name if default_name in choices else (choices[0] if choices else ""))

    def ensure_objective_choice(self) -> None:
        """Reset stale objective selections to available objectives."""
        choices = self.objective_choices()
        if hasattr(self, "single_objective_combo"):
            self.single_objective_combo.configure(values=choices)
        if self.single_objective.get() not in choices:
            self.single_objective.set(choices[0] if choices else "")
        for key in choices:
            self.objective_weights.setdefault(key, StringVar(value="1.0"))
            self.multi_objectives.setdefault(key, BooleanVar(value=True))
        for key in list(self.objective_weights):
            if key not in choices:
                del self.objective_weights[key]
        for key in list(self.multi_objectives):
            if key not in choices:
                del self.multi_objectives[key]

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

    def _build_timing_tab(self) -> None:
        """Build timing-analysis controls."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Time Analysis")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(3, weight=1)

        toolbar = ttk.Frame(tab)
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Button(toolbar, text="Refresh", command=self.refresh_all_views).pack(side="left")

        self.timing_summary = StringVar(value="No run selected")
        ttk.Label(tab, textvariable=self.timing_summary).grid(row=1, column=0, sticky="w", pady=(8, 0))

        self.timing_table = ttk.Treeview(
            tab,
            columns=("phase", "count", "total", "avg", "max"),
            show="headings",
            height=8,
        )
        self.timing_table.heading("phase", text="Phase")
        self.timing_table.heading("count", text="Count")
        self.timing_table.heading("total", text="Total sec")
        self.timing_table.heading("avg", text="Avg sec")
        self.timing_table.heading("max", text="Max sec")
        self.timing_table.column("phase", width=260, anchor="w")
        self.timing_table.column("count", width=80, anchor="e")
        self.timing_table.column("total", width=100, anchor="e")
        self.timing_table.column("avg", width=100, anchor="e")
        self.timing_table.column("max", width=100, anchor="e")
        self.timing_table.grid(row=2, column=0, sticky="ew", pady=(8, 0))

        self.timing_output = ScrolledText(tab, wrap="word")
        self.timing_output.grid(row=3, column=0, sticky="nsew", pady=(8, 0))

    def _build_prompt_tab(self) -> None:
        """Build prompt inspection controls."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Prompts")
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)

        self.prompt_table = ttk.Treeview(
            tab,
            columns=("generation", "individual", "mode", "opponent"),
            show="headings",
        )
        self.prompt_table.heading("generation", text="Gen")
        self.prompt_table.heading("individual", text="Individual")
        self.prompt_table.heading("mode", text="Mode")
        self.prompt_table.heading("opponent", text="Opponent")
        self.prompt_table.column("generation", width=70, anchor="center")
        self.prompt_table.column("individual", width=140, anchor="w")
        self.prompt_table.column("mode", width=130, anchor="w")
        self.prompt_table.column("opponent", width=220, anchor="w")
        self.prompt_table.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        self.prompt_table.bind("<<TreeviewSelect>>", self.show_selected_prompt)

        inspector = ttk.Frame(tab)
        inspector.grid(row=0, column=1, sticky="nsew")
        inspector.columnconfigure(0, weight=1)
        inspector.rowconfigure(1, weight=1)
        inspector.rowconfigure(3, weight=1)

        self.prompt_metadata = StringVar(value="No prompt selected")
        ttk.Label(inspector, textvariable=self.prompt_metadata).grid(row=0, column=0, sticky="w")

        prompt_frame = ttk.LabelFrame(inspector, text="Individual prompt", padding=6)
        prompt_frame.grid(row=1, column=0, sticky="nsew", pady=(4, 8))
        prompt_frame.columnconfigure(0, weight=1)
        prompt_frame.rowconfigure(0, weight=1)
        self.individual_prompt_output = ScrolledText(prompt_frame, wrap="word", height=14)
        self.individual_prompt_output.grid(row=0, column=0, sticky="nsew")

        response_frame = ttk.LabelFrame(inspector, text="LLM response", padding=6)
        response_frame.grid(row=3, column=0, sticky="nsew")
        response_frame.columnconfigure(0, weight=1)
        response_frame.rowconfigure(0, weight=1)
        self.llm_response_output = ScrolledText(response_frame, wrap="word", height=12)
        self.llm_response_output.grid(row=0, column=0, sticky="nsew")
        self.loaded_prompts: dict[str, dict[str, Any]] = {}

    def _build_java_gui_tab(self) -> None:
        """Build controls for saving a prompt and launching the Java MicroRTS GUI."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Java GUI")
        tab.columnconfigure(0, weight=1)

        settings = ttk.Frame(tab)
        settings.grid(row=0, column=0, sticky="ew")
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)
        ttk.Label(settings, text="Opponent").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(
            settings,
            textvariable=self.microrts_gui_opponent,
            values=MICRORTS_OPPONENT_CHOICES,
            state="readonly",
        ).grid(
            row=0, column=1, sticky="ew", padx=(8, 16), pady=4
        )
        ttk.Label(settings, text="Map folder").grid(row=0, column=2, sticky="w", pady=4)
        self.microrts_gui_map_dir_combo = ttk.Combobox(
            settings,
            textvariable=self.microrts_gui_map_dir,
            values=microrts_map_dir_choices(),
            state="readonly",
        )
        self.microrts_gui_map_dir_combo.grid(row=0, column=3, sticky="ew", padx=(8, 16), pady=4)
        self.microrts_gui_map_dir_combo.bind("<<ComboboxSelected>>", self.on_microrts_map_dir_selected)
        ttk.Label(settings, text="Map file").grid(row=1, column=0, sticky="w", pady=4)
        self.microrts_gui_map_file_combo = ttk.Combobox(
            settings,
            textvariable=self.microrts_gui_map_file,
            values=microrts_map_file_choices(self.microrts_gui_map_dir.get()),
            state="readonly",
        )
        self.microrts_gui_map_file_combo.grid(row=1, column=1, sticky="ew", padx=(8, 16), pady=4)
        ttk.Label(settings, text="Update interval").grid(row=1, column=2, sticky="w", pady=4)
        ttk.Entry(settings, textvariable=self.microrts_gui_update_interval, width=8).grid(
            row=1, column=3, sticky="w", padx=(8, 16), pady=4
        )
        ttk.Label(settings, text="LLM interval").grid(row=1, column=4, sticky="w", pady=4)
        ttk.Entry(settings, textvariable=self.microrts_gui_llm_interval, width=8).grid(
            row=1, column=5, sticky="w", padx=(8, 0), pady=4
        )
        ttk.Checkbutton(settings, text="Save trace", variable=self.microrts_gui_save_trace).grid(
            row=1, column=6, sticky="w", padx=(8, 0), pady=4
        )

        actions = ttk.Frame(tab)
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(actions, text="Load current prompt", command=self.load_current_prompt_for_java_gui).pack(side="left")
        ttk.Button(actions, text="Save prompt.txt", command=self.save_java_gui_prompt).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Save and launch MicroRTS", command=self.launch_microrts_java_gui).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(actions, text="Stop MicroRTS", command=self.stop_microrts_java_gui).pack(side="left", padx=(8, 0))
        ttk.Label(actions, textvariable=self.microrts_gui_status).pack(side="left", padx=(16, 0))

        trace_actions = ttk.Frame(tab)
        trace_actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.trace_selector = ttk.Combobox(trace_actions, textvariable=self.selected_trace, state="readonly", width=100)
        self.trace_selector.pack(side="left", fill="x", expand=True)
        ttk.Button(trace_actions, text="Refresh traces", command=self.refresh_trace_choices).pack(side="left", padx=(8, 0))
        ttk.Button(trace_actions, text="Open trace", command=self.open_selected_trace).pack(side="left", padx=(8, 0))

        self.java_gui_prompt_output = ScrolledText(tab, wrap="word", height=14)
        self.java_gui_prompt_output.grid(row=3, column=0, sticky="nsew", pady=(8, 0))

        ttk.Label(tab, text="Java MicroRTS log").grid(row=4, column=0, sticky="w", pady=(12, 0))
        self.microrts_gui_output = ScrolledText(tab, wrap="word", height=10)
        self.microrts_gui_output.grid(row=5, column=0, sticky="nsew", pady=(4, 0))
        tab.rowconfigure(3, weight=1)
        tab.rowconfigure(5, weight=1)
        self.refresh_trace_choices()

    # ------------------------------------------------------------------
    # Small widget factories
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Algorithm, evaluator, surrogate, and objective synchronization
    # ------------------------------------------------------------------

    def on_algorithm_selected(self, _event: object | None = None) -> None:
        """Keep algorithm-derived defaults in sync with the current flow."""
        self.sync_algorithm_operator_defaults()
        if self.algorithm.get() in GA_ALGORITHMS and self.objective_mode.get() not in {"single", "weighted_mix"}:
            self.objective_mode.set("single")
        if self.algorithm.get() not in GA_ALGORITHMS:
            self.objective_mode.set("multi")
        self.refresh_surrogate_visibility()
        self.ensure_objective_choice()
        self.refresh_objective_table()

    def sync_algorithm_operator_defaults(self) -> None:
        """Keep algorithm-specific parent and environment operators compatible."""
        algorithm = self.algorithm.get()
        parent_default = PARENT_SELECTION_BY_ALGORITHM.get(algorithm)
        env_default = ENV_SELECTION_BY_ALGORITHM.get(algorithm)
        if parent_default and self.parent_selection_operator.get() != parent_default:
            self.parent_selection_operator.set(parent_default)
        if env_default and self.env_selection_operator.get() != env_default:
            self.env_selection_operator.set(env_default)

    def on_surrogate_selected(self, _event: object | None = None) -> None:
        """Refresh surrogate-specific evaluator and objective choices."""
        if self.algorithm.get() not in SURROGATE_ALGORITHMS:
            return
        self.ensure_objective_choice()
        self.refresh_objective_table()

    def on_evaluator_selected(self, _event: object | None = None) -> None:
        """Refresh objective controls after changing eval mode."""
        self.refresh_surrogate_visibility()
        self.ensure_objective_choice()
        self.refresh_objective_table()

    def refresh_surrogate_visibility(self) -> None:
        """Show surrogate-only controls only for the ga_surrogate algorithm."""
        gameplay_active = self.evaluator.get() == "gameplay"
        surrogate_active = self.algorithm.get() in SURROGATE_ALGORITHMS
        if hasattr(self, "surrogate_controls_frame"):
            if surrogate_active:
                self.surrogate_controls_frame.grid()
                if self.surrogate.get() not in SURROGATE_CHOICES:
                    self.surrogate.set(SURROGATE_CHOICES[0])
            else:
                self.surrogate_controls_frame.grid_remove()
        if hasattr(self, "surrogate_algorithm_frame"):
            if surrogate_active:
                self.surrogate_algorithm_frame.grid()
            else:
                self.surrogate_algorithm_frame.grid_remove()
        if hasattr(self, "game_seconds_frame"):
            if gameplay_active:
                self.game_seconds_frame.grid()
            else:
                self.game_seconds_frame.grid_remove()
        if hasattr(self, "surrogate_paths_frame"):
            if gameplay_active:
                self.surrogate_paths_frame.grid()
            else:
                self.surrogate_paths_frame.grid_remove()

    def current_eval_mode(self) -> str:
        """Return the objective-facing eval mode implied by GUI settings."""
        return "full_game"

    def objective_choices(self) -> tuple[str, ...]:
        """Return registered objective names discovered from objective plugins."""
        return list_objective_names(self.application.get(), self.current_eval_mode())

    def on_objective_mode_selected(self, _event: object | None = None) -> None:
        """Refresh objective rows after changing objective mode."""
        self.refresh_objective_table()

    def selected_objective_key(self) -> str | None:
        """Return the selected objective key."""
        selection = self.objective_table.selection()
        if not selection:
            return None
        return str(selection[0])

    def refresh_objective_table(self, *, select_target: str | None = None) -> None:
        """Refresh objective rows and show their calculation details."""
        if not hasattr(self, "objective_table"):
            return
        self.ensure_objective_choice()
        single_algorithm = self.algorithm.get() in GA_ALGORITHMS
        if single_algorithm:
            self.objective_mode_frame.grid()
        else:
            self.objective_mode.set("multi")
            self.objective_mode_frame.grid_remove()

        if single_algorithm and self.objective_mode.get() == "single":
            self.single_objective_frame.grid()
            self.objective_table.grid_remove()
        else:
            self.single_objective_frame.grid_remove()
            self.objective_table.grid()

        self.objective_table.delete(*self.objective_table.get_children())
        for objective in get_objectives(self.application.get(), self.current_eval_mode()):
            selected = self.multi_objectives.setdefault(objective.key, BooleanVar(value=True)).get()
            weight = self.objective_weights.setdefault(objective.key, StringVar(value="1.0")).get()
            self.objective_table.insert(
                "",
                "end",
                iid=objective.key,
                values=(
                    "yes" if selected else "no",
                    objective.key,
                    objective.label,
                    objective.direction,
                    weight,
                ),
            )
        key_to_select = select_target or self.selected_objective_key() or self.single_objective.get()
        if key_to_select in self.objective_table.get_children():
            self.objective_table.selection_set(key_to_select)
        elif self.objective_table.get_children():
            self.objective_table.selection_set(self.objective_table.get_children()[0])
        self.update_objective_detail()

    def on_objective_selected(self, _event: object | None = None) -> None:
        """Show the calculation details for the selected objective."""
        self.update_objective_detail()

    def on_objective_table_double_click(self, _event: object | None = None) -> None:
        """Toggle or edit the selected objective according to current mode."""
        if self.objective_mode.get() == "weighted_mix":
            self.set_selected_objective_weight()
        else:
            self.toggle_selected_objective()

    def toggle_selected_objective(self) -> None:
        """Toggle the selected multi-objective row."""
        key = self.selected_objective_key()
        if not key:
            return
        variable = self.multi_objectives.setdefault(key, BooleanVar(value=True))
        variable.set(not bool(variable.get()))
        self.refresh_objective_table(select_target=key)

    def set_selected_objective_weight(self) -> None:
        """Edit the selected weighted-mix objective weight."""
        key = self.selected_objective_key()
        if not key:
            return
        current = self.objective_weights.setdefault(key, StringVar(value="1.0")).get()
        value = simpledialog.askstring("Set objective weight", f"Weight for {key}:", initialvalue=current, parent=self.root)
        if value is None:
            return
        parse_float(value, f"weight for {key}")
        self.objective_weights[key].set(value.strip())
        self.multi_objectives.setdefault(key, BooleanVar(value=True)).set(True)
        self.refresh_objective_table(select_target=key)

    def update_objective_detail(self) -> None:
        """Show how the selected objective is calculated."""
        if self.algorithm.get() in GA_ALGORITHMS and self.objective_mode.get() == "single":
            key = self.single_objective.get()
        else:
            key = self.selected_objective_key()
        if not key:
            self.objective_detail.set("No objective selected.")
            return
        objective_by_key = {objective.key: objective for objective in get_objectives(self.application.get(), self.current_eval_mode())}
        objective = objective_by_key.get(key)
        if objective is None:
            self.objective_detail.set(f"{key} is not available for {self.current_eval_mode()}.")
            return
        self.objective_detail.set(
            f"{objective.key}: {objective.label}; direction={objective.direction}; eval_mode={self.current_eval_mode()}."
        )

    # ------------------------------------------------------------------
    # Component JSON loading, editing, and candidate management
    # ------------------------------------------------------------------

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
        initial_dir = self.component_file_dialog_dir()
        path = filedialog.askopenfilename(
            initialdir=str(initial_dir),
            initialfile=self.default_component_filename(),
            title="Select component.json",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if path:
            self.component_source_path.set(path)
            selected_path = Path(path)
            self.component_runtime_path.set(relative_or_absolute(selected_path))
            self.preview_component(selected_path)

    def component_file_dialog_dir(self) -> Path:
        """Return the directory that should open for component file dialogs."""
        candidates: list[Path] = []
        if self.loaded_component_path is not None:
            candidates.append(self.loaded_component_path)
        for value in (
            self.component_source_path.get(),
            self.component_runtime_path.get(),
        ):
            if value:
                candidates.append(resolve_repo_path(value))
        try:
            payload = load_json_file(resolve_repo_path(self.base_config_path.get()))
        except (OSError, ValueError):
            payload = {}
        configured = str(payload.get("component_pool_path", "")).strip()
        if configured:
            candidates.append(resolve_repo_path(configured))
        candidates.append(ROOT / "eagle" / "prompts" / "components.json")

        for candidate in candidates:
            directory = candidate if candidate.is_dir() else candidate.parent
            if directory.exists():
                return directory
        return ROOT

    def default_component_filename(self) -> str:
        """Return the filename shown by default in component save dialogs."""
        if self.loaded_component_path is not None:
            return self.loaded_component_path.name
        for value in (
            self.component_source_path.get(),
            self.component_runtime_path.get(),
        ):
            if value:
                name = Path(value).name
                if name:
                    return name
        return "components.json"

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
        self.component_source_path.set(str(path))
        self.component_runtime_path.set(relative_or_absolute(path))
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
        self.refresh_move_builder_visibility()

    def refresh_move_builder_visibility(self) -> None:
        """Show the move builder only while editing training examples."""
        if not hasattr(self, "move_builder"):
            return
        if self.is_training_examples_category(self.component_category.get()):
            self.move_builder.grid()
        else:
            self.move_builder.grid_remove()

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
        self.refresh_move_builder_visibility()
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

    # ------------------------------------------------------------------
    # Training-example move builder embedded in the component editor
    # ------------------------------------------------------------------

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
        directory = self.component_file_dialog_dir()
        filename = simpledialog.askstring(
            "Save components JSON",
            "File name:",
            initialvalue=self.default_component_filename(),
            parent=self.root,
        )
        if filename is None:
            return None
        filename = filename.strip()
        if not filename:
            messagebox.showerror("Missing file name", "Enter a component JSON file name.")
            return None
        destination = directory / Path(filename).name
        if destination.suffix.lower() != ".json":
            destination = destination.with_suffix(".json")
        if destination.exists() and not messagebox.askyesno("Overwrite component JSON", f"Overwrite existing file?\n{destination}"):
            return None
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

    # ------------------------------------------------------------------
    # Prompt rendering and Java GUI prompt export
    # ------------------------------------------------------------------

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

    def refresh_training_example_sampling_controls(self) -> None:
        """Toggle range or fixed-count sampling inputs."""
        if not hasattr(self, "training_example_range_frame"):
            return
        if self.training_example_fixed_count.get():
            self.training_example_range_frame.grid_remove()
            self.training_example_fixed_frame.grid()
        else:
            self.training_example_fixed_frame.grid_remove()
            self.training_example_range_frame.grid()
        self.on_training_example_sampling_changed()

    def on_training_example_sampling_changed(self, *_: object) -> None:
        """Refresh prompt preview after changing training-example sampling."""
        self.training_example_sample_count.set(self.training_example_sample_label())
        if not hasattr(self, "component_selection_table"):
            return
        self.refresh_component_selection_table()
        if hasattr(self, "component_prompt_output"):
            self.render_selected_component_prompt()

    def training_example_selection_value(self) -> str | int:
        """Return random or fixed training-example sample-count selection."""
        if self.training_example_fixed_count.get():
            return self._parse_nonnegative_int(
                self.training_example_fixed_sample_count.get(),
                default=4,
            )
        lower, upper = self.training_example_sample_bounds()
        return f"random_{lower}_{upper}"

    def training_example_sample_label(self) -> str:
        """Return the table display text for training-example sampling."""
        if self.training_example_fixed_count.get():
            return str(
                self._parse_nonnegative_int(
                    self.training_example_fixed_sample_count.get(),
                    default=4,
                )
            )
        lower, upper = self.training_example_sample_bounds()
        return f"random {lower}-{upper}"

    def training_example_sample_bounds(self) -> tuple[int, int]:
        """Return normalized training-example sample range bounds."""
        lower = self._parse_nonnegative_int(self.training_example_sample_min.get(), default=0)
        upper = self._parse_nonnegative_int(self.training_example_sample_max.get(), default=4)
        if lower > upper:
            lower, upper = upper, lower
        return lower, upper

    def apply_training_example_sample_config(self, value: object, fixed: object | None = None) -> None:
        """Load training-example sampling from config or legacy GUI values."""
        if fixed is not None:
            self.training_example_fixed_count.set(bool(fixed))
        text = str(value if value is not None else "").strip()
        if isinstance(value, int) or text.isdigit():
            self.training_example_fixed_count.set(True if fixed is None else bool(fixed))
            self.training_example_fixed_sample_count.set(str(self._parse_nonnegative_int(text, default=4)))
        else:
            lower, upper = self._parse_training_example_range(text)
            if fixed is None:
                self.training_example_fixed_count.set(False)
            self.training_example_sample_min.set(str(lower))
            self.training_example_sample_max.set(str(upper))
        self.refresh_training_example_sampling_controls()

    @staticmethod
    def _parse_nonnegative_int(value: object, *, default: int) -> int:
        """Parse a non-negative integer with a stable fallback."""
        try:
            return max(0, int(str(value).strip()))
        except (TypeError, ValueError):
            return default

    @classmethod
    def _parse_training_example_range(cls, value: object) -> tuple[int, int]:
        """Parse A-B, random A-B, or random_A_B training-example ranges."""
        text = str(value or "").strip().lower().replace("_", " ")
        match = re.search(r"(\d+)\s*-\s*(\d+)", text)
        if not match:
            match = re.search(r"random\s+(\d+)\s+(\d+)", text)
        if not match and text.isdigit():
            count = cls._parse_nonnegative_int(text, default=4)
            return count, count
        if not match:
            return 0, 4
        lower = cls._parse_nonnegative_int(match.group(1), default=0)
        upper = cls._parse_nonnegative_int(match.group(2), default=4)
        if lower > upper:
            lower, upper = upper, lower
        return lower, upper

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
                    values=(
                        key,
                        "-",
                        self.training_example_sample_label(),
                        len(examples),
                        line_count,
                    ),
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
                values=(key, static_label, selected_index, candidate_count, line_count),
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

    def copy_current_prompt(self) -> None:
        """Copy the currently rendered prompt to the clipboard."""
        prompt = self.component_prompt_output.get("1.0", "end").rstrip("\n")
        self.root.clipboard_clear()
        self.root.clipboard_append(prompt)
        self.root.update_idletasks()
        self.component_status.set("Copied current prompt to clipboard")

    def current_prompt_text(self) -> str:
        """Return the prompt currently visible in the GUI."""
        if hasattr(self, "component_prompt_output"):
            prompt = self.component_prompt_output.get("1.0", "end").rstrip("\n")
            if prompt.strip():
                return prompt
        prompt_id = self.selected_prompt_id() if hasattr(self, "prompt_table") else None
        record = self.loaded_prompts.get(prompt_id or "") if hasattr(self, "loaded_prompts") else None
        if record:
            prompt = str(record.get("prompt") or "").rstrip("\n")
            if prompt.strip():
                return prompt
        return ""

    def load_current_prompt_for_java_gui(self) -> None:
        """Copy the active rendered/evaluated prompt into the Java GUI prompt editor."""
        prompt = self.current_prompt_text()
        if not prompt.strip():
            messagebox.showwarning("No prompt", "Render or select a prompt first.")
            return
        self._set_text(self.java_gui_prompt_output, prompt)
        self.microrts_gui_status.set("Loaded current prompt")

    def save_java_gui_prompt(self) -> Path | None:
        """Save the Java GUI prompt to the MicroRTS runtime prompt file."""
        prompt = self.java_gui_prompt_output.get("1.0", "end").rstrip("\n")
        if not prompt.strip():
            prompt = self.current_prompt_text()
            if prompt.strip():
                self._set_text(self.java_gui_prompt_output, prompt)
        if not prompt.strip():
            messagebox.showwarning("No prompt", "Render or select a prompt first.")
            return None
        try:
            prompt_path = save_prompt(ROOT, prompt)
        except OSError as exc:
            messagebox.showerror("Could not save prompt", str(exc))
            return None
        self.microrts_gui_status.set(f"Saved {prompt_path}")
        return prompt_path

    def on_microrts_map_dir_selected(self, _event: object | None = None) -> None:
        """Refresh the map-file dropdown after changing the map folder."""
        files = microrts_map_file_choices(self.microrts_gui_map_dir.get())
        if hasattr(self, "microrts_gui_map_file_combo"):
            self.microrts_gui_map_file_combo.configure(values=files)
        if files and self.microrts_gui_map_file.get() not in files:
            self.microrts_gui_map_file.set(files[0])

    def selected_microrts_map(self) -> str:
        """Return the selected MicroRTS map path as `maps/AA/BB.xml`."""
        map_dir = self.microrts_gui_map_dir.get().strip()
        map_file = self.microrts_gui_map_file.get().strip()
        if not map_dir or not map_file:
            return ""
        return f"maps/{map_dir}/{map_file}"

    def refresh_trace_choices(self) -> None:
        """Refresh saved MicroRTS trace choices."""
        traces = [str(path) for path in microrts_trace_choices()]
        if hasattr(self, "trace_selector"):
            self.trace_selector.configure(values=traces)
        if traces and self.selected_trace.get() not in traces:
            self.selected_trace.set(traces[0])
        elif not traces:
            self.selected_trace.set("")

    def open_selected_trace(self) -> None:
        """Open a saved MicroRTS trace in the Java trace viewer."""
        trace_text = self.selected_trace.get().strip()
        if not trace_text:
            messagebox.showwarning("No trace selected", "Select a saved trace first.")
            return
        trace_path = Path(trace_text)
        if not trace_path.exists():
            messagebox.showerror("Missing trace", f"Trace file does not exist:\n{trace_path}")
            self.refresh_trace_choices()
            return
        try:
            microrts_root = require_microrts_class("gui/TraceViewerMain.class")
        except (OSError, RuntimeError, FileNotFoundError) as exc:
            messagebox.showerror("Could not open trace", str(exc))
            return
        classpath = f"{microrts_root / 'lib' / '*'}{os.pathsep}{microrts_root / 'bin'}"
        command = ["java", "-cp", classpath, "gui.TraceViewerMain", str(trace_path)]
        try:
            subprocess.Popen(command, cwd=microrts_root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        except OSError as exc:
            messagebox.showerror("Could not open trace", str(exc))
            return
        self.microrts_gui_status.set(f"Opened trace {trace_path.name}")

    def include_identity_component_in_preview(self) -> bool:
        """Return whether preview rendering should include the identity component."""
        try:
            payload = load_json_file(resolve_repo_path(self.base_config_path.get()))
        except (OSError, json.JSONDecodeError):
            return True
        return bool(payload.get("include_strategy_identity_in_prompt", True))

    # ------------------------------------------------------------------
    # Config load/save and experiment payload assembly
    # ------------------------------------------------------------------

    def load_base_config_into_form(self) -> None:
        """Load config fields into the GUI form."""
        path = Path(self.base_config_path.get())
        if not path.exists():
            messagebox.showerror("Missing config", f"Config file does not exist:\n{path}")
            return
        try:
            payload = load_complete_config_payload(path)
        except (ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror("Invalid config JSON", str(exc))
            return
        self.algorithm.set(
            normalize_algorithm_name(
                payload.get("algorithm", self.algorithm.get()),
                evaluator=payload.get("evaluator"),
                surrogate=payload.get("surrogate"),
                warn=True,
            )
        )
        if self.algorithm.get() not in ALGORITHM_CHOICES:
            self.algorithm.set("nsga2")
        self.application.set(str(payload.get("application", self.application.get())))
        if self.application.get() not in APPLICATION_CHOICES:
            self.application.set("microrts")
        self.evaluator.set("gameplay")
        if self.evaluator.get() not in EVALUATOR_CHOICES:
            self.evaluator.set("gameplay")
        self.surrogate.set(str(payload.get("surrogate", self.surrogate.get())).strip().lower().replace("-", "_").replace(" ", "_"))
        if self.surrogate.get() not in SURROGATE_CHOICES:
            self.surrogate.set(SURROGATE_CHOICES[0])
        self.refresh_surrogate_visibility()
        self.population_size.set(str(payload.get("population_size", self.population_size.get())))
        self.num_generations.set(str(payload.get("num_generations", self.num_generations.get())))
        self.tick_limit.set(str(payload.get("tick_limit", self.tick_limit.get())))
        self.llm_call_limit.set(str(payload.get("llm_call_limit", self.llm_call_limit.get())))
        self.gameplay_map_dir.set(str(payload.get("gameplay_map_dir", self.gameplay_map_dir.get())))
        if self.gameplay_map_dir.get() not in microrts_map_dir_choices():
            self.gameplay_map_dir.set("8x8")
        self.gameplay_rate.set(str(payload.get("gameplay_rate", self.gameplay_rate.get())))
        self.gameplay_refresh_interval.set(
            str(payload.get("gameplay_refresh_interval", self.gameplay_refresh_interval.get()))
        )
        self.surrogate_top_ratio.set(str(payload.get("surrogate_top_ratio", self.surrogate_top_ratio.get())))
        self.archive_parent_ratio.set(str(payload.get("archive_parent_ratio", self.archive_parent_ratio.get())))
        self.one_eval_rounds.set(str(payload.get("one_eval_rounds", self.one_eval_rounds.get())))
        self.round_eval_parallel_workers.set(
            str(payload.get("round_eval_parallel_workers", self.round_eval_parallel_workers.get()))
        )
        self.agent_eval_parallel_workers.set(
            str(payload.get("agent_eval_parallel_workers", self.agent_eval_parallel_workers.get()))
        )
        self.individual_eval_parallel_workers.set(
            str(payload.get("individual_eval_parallel_workers", self.individual_eval_parallel_workers.get()))
        )
        self.llm_parallel_workers.set(str(payload.get("llm_parallel_workers", self.llm_parallel_workers.get())))
        self.load_objective_config(payload.get("objective_config", {}))
        self.apply_training_example_sample_config(
            payload.get(
                "training_example_sample_count",
                self.training_example_selection_value(),
            ),
            payload.get("training_example_fixed_count"),
        )
        self.final_test_max_front.set(str(payload.get("final_test_max_front", self.final_test_max_front.get())))
        self.selection_method.set(str(payload.get("selection_method", self.selection_method.get())))
        self.parent_selection_operator.set(
            str(payload.get("parent_selection_operator", self.parent_selection_operator.get()))
        )
        self.tournament_size.set(str(payload.get("tournament_size", self.tournament_size.get())))
        self.crossover.set(str(payload.get("crossover", self.crossover.get())))
        self.crossover_operator.set(str(payload.get("crossover_operator", self.crossover.get())))
        self.mutation_operator.set(str(payload.get("mutation_operator", self.mutation_operator.get())))
        self.env_selection_operator.set(
            str(
                payload.get(
                    "env_selection_operator",
                    payload.get("environment_selection_method", self.env_selection_operator.get()),
                )
            )
        )
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
        loaded_opponents = parse_target_list(payload.get("gameplay_opponents", []))
        if loaded_opponents:
            self.objective_targets = loaded_opponents
        self.opponents_text.set(", ".join(self.objective_targets))
        for key, variable in self.operator_weights.items():
            variable.set(str((payload.get("reproduction_operator_probs") or {}).get(key, variable.get())))
        for key, variable in self.mutation_weights.items():
            variable.set(str((payload.get("strategy_mutation") or {}).get(key, variable.get())))
        self.ensure_operator_choice(self.parent_selection_operator, "parent_selection", "nsga2_tournament")
        self.ensure_operator_choice(self.crossover_operator, "crossover", "uniform")
        self.ensure_operator_choice(self.mutation_operator, "mutation", "mix")
        self.ensure_operator_choice(self.env_selection_operator, "env_selection", "nsga2_environmental")
        self.sync_algorithm_operator_defaults()
        self.ensure_objective_choice()
        self.refresh_objective_table()
        self.refresh_mutation_weight_visibility()
        self.refresh_crossover_repair_visibility()
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
        write_json_file(path, payload)
        self.generated_config_path = path
        self.generated_config_label.set(f"Generated config: {path}")
        self.status.set(f"Saved {path.name}")
        return path

    def build_config_payload(self) -> dict[str, Any]:
        """Build one EAGLE config payload from the GUI controls."""
        base_path = Path(self.base_config_path.get())
        payload = load_complete_config_payload(base_path)
        component_path = self.component_runtime_path.get().strip()
        if not component_path:
            raise ValueError("Runtime component path is required.")
        if not resolve_repo_path(component_path).exists():
            raise ValueError(f"Runtime component path does not exist: {component_path}")
        if self.application.get() != "microrts":
            raise ValueError(f"Unsupported application: {self.application.get()}.")
        if self.algorithm.get() not in ALGORITHM_CHOICES:
            raise ValueError(f"Unsupported algorithm: {self.algorithm.get()}.")
        if self.gameplay_map_dir.get().strip() not in microrts_map_dir_choices():
            raise ValueError(f"Unsupported eval map folder: {self.gameplay_map_dir.get()}.")
        self.evaluator.set("gameplay")
        if self.evaluator.get() not in EVALUATOR_CHOICES:
            raise ValueError(f"Unsupported evaluator: {self.evaluator.get()}.")
        if self.surrogate.get() not in SURROGATE_CHOICES:
            if self.evaluator.get() == "gameplay":
                raise ValueError(f"Unsupported surrogate: {self.surrogate.get()}.")
            self.surrogate.set(SURROGATE_CHOICES[0])
        self.ensure_objective_choice()
        self.sync_algorithm_operator_defaults()
        objective_targets = self.config_objective_targets()
        objective_config = self.build_objective_config()

        payload.update(
            {
                "application": self.application.get(),
                "evaluator": self.evaluator.get(),
                "algorithm": self.algorithm.get(),
                "surrogate": self.surrogate.get(),
                "population_size": parse_int(self.population_size.get(), "population_size"),
                "num_generations": parse_int(self.num_generations.get(), "num_generations"),
                "tick_limit": parse_int(self.tick_limit.get(), "tick_limit"),
                "llm_call_limit": parse_int(self.llm_call_limit.get(), "llm_call_limit"),
                "gameplay_map_dir": self.gameplay_map_dir.get().strip(),
                "gameplay_rate": parse_float(self.gameplay_rate.get(), "gameplay_rate"),
                "gameplay_refresh_interval": parse_int(
                    self.gameplay_refresh_interval.get(),
                    "gameplay_refresh_interval",
                ),
                "surrogate_top_ratio": parse_float(self.surrogate_top_ratio.get(), "surrogate_top_ratio"),
                "archive_parent_ratio": parse_float(self.archive_parent_ratio.get(), "archive_parent_ratio"),
                "objective_config": objective_config,
                "training_example_sample_count": self.training_example_selection_value(),
                "training_example_fixed_count": bool(self.training_example_fixed_count.get()),
                "final_test_max_front": parse_optional_nonnegative_int(
                    self.final_test_max_front.get(),
                    "final_test_max_front",
                ),
                "selection_method": self.selection_method.get(),
                "parent_selection_operator": self.parent_selection_operator.get(),
                "tournament_size": parse_int(self.tournament_size.get(), "tournament_size"),
                "crossover": self.crossover.get(),
                "crossover_operator": self.crossover_operator.get(),
                "mutation_operator": self.mutation_operator.get(),
                "environment_selection_method": self.env_selection_operator.get(),
                "env_selection_operator": self.env_selection_operator.get(),
                "crossover_repair_enabled": (
                    bool(self.crossover_repair_enabled.get())
                    if self.crossover_operator.get() == "uniform"
                    else False
                ),
                "enable_reflection_operator": bool(self.enable_reflection_operator.get()),
                "component_pool_path": component_path,
                "non_evolving_prompt_components": self.config_static_component_keys(),
                "gameplay_opponents": objective_targets,
                "one_eval_rounds": parse_int(self.one_eval_rounds.get(), "one_eval_rounds"),
                "round_eval_parallel_workers": parse_int(
                    self.round_eval_parallel_workers.get(),
                    "round_eval_parallel_workers",
                ),
                "agent_eval_parallel_workers": parse_int(
                    self.agent_eval_parallel_workers.get(),
                    "agent_eval_parallel_workers",
                ),
                "individual_eval_parallel_workers": parse_int(
                    self.individual_eval_parallel_workers.get(),
                    "individual_eval_parallel_workers",
                ),
                "llm_parallel_workers": parse_int(self.llm_parallel_workers.get(), "llm_parallel_workers"),
                "reproduction_operator_probs": {
                    key: parse_float(variable.get(), key)
                    for key, variable in self.operator_weights.items()
                },
                "strategy_mutation": self.build_strategy_mutation_weights(),
            }
        )
        normalize_probability_map(payload["reproduction_operator_probs"], "reproduction_operator_probs")
        normalize_probability_map(payload["strategy_mutation"], "strategy_mutation")
        return payload

    def build_strategy_mutation_weights(self) -> dict[str, float]:
        """Return mutation weights according to the selected mutation operator."""
        selected_operator = self.mutation_operator.get()
        if selected_operator != "mix":
            return {selected_operator: 1.0}
        return {
            key: parse_float(variable.get(), key)
            for key, variable in self.mutation_weights.items()
            if key in self.mutation_weight_names()
        }

    def config_objective_targets(self) -> list[str]:
        """Return configured gameplay opponents."""
        if self.evaluator.get() == "round":
            self.objective_targets = []
            return []
        targets = parse_target_list(self.opponents_text.get())
        if not targets:
            raise ValueError("At least one gameplay opponent is required.")
        self.objective_targets = targets
        return targets

    def load_objective_config(self, objective_config: Any) -> None:
        """Load objective_config into GUI objective controls."""
        config = dict(objective_config or {})
        mode = str(config.get("mode", self.objective_mode.get())).strip().lower()
        if mode in {"single", "weighted_mix", "multi"}:
            self.objective_mode.set(mode)
        objective = normalize_objective_key(str(config.get("objective", self.single_objective.get())))
        if objective:
            self.single_objective.set(objective)
        for key, value in dict(config.get("weights") or {}).items():
            normalized_key = normalize_objective_key(str(key).strip())
            self.objective_weights[normalized_key] = StringVar(value=str(value))
            self.multi_objectives[normalized_key] = BooleanVar(value=True)
        configured_objectives = [normalize_objective_key(str(key).strip()) for key in config.get("objectives", [])]
        if configured_objectives:
            for key in self.objective_choices():
                self.multi_objectives.setdefault(key, BooleanVar(value=False)).set(key in configured_objectives)

    def build_objective_config(self) -> dict[str, Any]:
        """Build and validate objective_config from GUI objective controls."""
        choices = set(self.objective_choices())
        if self.algorithm.get() in GA_ALGORITHMS:
            mode = self.objective_mode.get()
            if mode == "single":
                objective = self.single_objective.get().strip()
                if objective not in choices:
                    raise ValueError(f"Objective {objective!r} is not available for {self.current_eval_mode()}.")
                return {"mode": "single", "objective": objective}
            weights = {
                key: parse_float(variable.get(), f"weight for {key}")
                for key, variable in self.objective_weights.items()
                if key in choices and self.multi_objectives.setdefault(key, BooleanVar(value=True)).get()
            }
            if not weights:
                raise ValueError("weighted_mix requires at least one objective.")
            weights = {key: value for key, value in weights.items() if value > 0}
            if not weights:
                raise ValueError("weighted_mix requires at least one positive weight.")
            total = sum(weights.values())
            return {"mode": "weighted_mix", "weights": {key: value / total for key, value in weights.items()}}

        objectives = [
            key
            for key in self.objective_choices()
            if self.multi_objectives.setdefault(key, BooleanVar(value=True)).get()
        ]
        if len(objectives) < 2:
            raise ValueError("multi mode requires at least two objectives.")
        return {"mode": "multi", "objectives": objectives}

    def config_filename(self) -> str:
        """Return a safe config filename from the user-provided config name."""
        raw_name = self.config_name.get().strip()
        if not raw_name:
            raw_name = f"gui_evolution_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in raw_name)
        if not safe.endswith(".json"):
            safe = f"{safe}.json"
        return safe

    # ------------------------------------------------------------------
    # Process launch, stop, and live refresh
    # ------------------------------------------------------------------

    def start_experiment(self) -> None:
        """Save current settings and start EAGLE in a background process."""
        self.attach_existing_process()
        if self.is_monitored_process_running():
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
        if self.algorithm.get() == "ga_surrogate":
            command.extend(["--surrogate", self.surrogate.get()])
        if self.quick_run.get():
            command.append("--quick-run")
        if self.skip_final_test.get():
            command.append("--skip-final-test")
        if self.precompile_python.get():
            command.append("--precompile-python")

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.process_log_path = LOG_DIR / f"gui_process_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        log_handle = self.process_log_path.open("w", encoding="utf-8", errors="replace")
        log_handle.write("Command: " + " ".join(command) + "\n\n")
        log_handle.write(
            "[DEBUG] gui start "
            f"surrogate={self.surrogate.get() if self.algorithm.get() == 'ga_surrogate' else '(ignored)'} "
            f"evaluator={self.evaluator.get()} "
            f"objective_config={self.build_objective_config()} "
            f"gameplay_refresh_interval={self.gameplay_refresh_interval.get()} "
            f"surrogate_top_ratio={self.surrogate_top_ratio.get()} "
            f"archive_parent_ratio={self.archive_parent_ratio.get()}\n\n"
        )
        log_handle.flush()
        self.process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.monitored_process_pid = int(self.process.pid)
        self.write_process_state(
            pid=self.monitored_process_pid,
            command=command,
            log_path=self.process_log_path,
            config_path=config_path,
        )
        self.status.set(f"Started PID {self.process.pid}")
        self.refresh_all_views()

    def launch_microrts_java_gui(self) -> None:
        """Save the current prompt and open a visible Java MicroRTS match."""
        if self.microrts_gui_process and self.microrts_gui_process.poll() is None:
            messagebox.showwarning("MicroRTS already running", "Stop the current Java GUI before starting another one.")
            return
        prompt_path = self.save_java_gui_prompt()
        if prompt_path is None:
            return
        try:
            update_interval = parse_int(self.microrts_gui_update_interval.get(), "update_interval")
            llm_interval = parse_int(self.microrts_gui_llm_interval.get(), "llm_interval")
            opponent = self.microrts_gui_opponent.get().strip()
            map_location = self.selected_microrts_map()
            if not opponent:
                raise ValueError("Opponent is required.")
            if not map_location:
                raise ValueError("Map is required.")
            microrts_root = require_microrts_class("rts/MicroRTS.class")
            set_config_property(ROOT, "launch_mode", "STANDALONE")
            set_config_property(ROOT, "headless", "false")
            set_config_property(ROOT, "map_location", map_location)
            set_config_property(ROOT, "AI1", "ai.eagle.EAGLE")
            set_config_property(ROOT, "AI2", opponent)
            set_config_property(ROOT, "update_interval", str(update_interval))
            set_config_property(ROOT, "llm_interval", str(llm_interval))
        except (OSError, RuntimeError, ValueError, FileNotFoundError) as exc:
            messagebox.showerror("Could not launch MicroRTS", str(exc))
            return

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.microrts_gui_log_path = LOG_DIR / f"microrts_gui_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        classpath = f"{microrts_root / 'lib' / '*'}{os.pathsep}{microrts_root / 'bin'}"
        command = ["java", "-Deagle.debug=true", "-cp", classpath, "rts.MicroRTS"]
        trace_path: Path | None = None
        if self.microrts_gui_save_trace.get():
            trace_dir = microrts_trace_dir()
            trace_dir.mkdir(parents=True, exist_ok=True)
            trace_path = trace_dir / f"gui_trace_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
            command.insert(2, f"-Dmicrorts.trace.path={trace_path}")
        log_handle = self.microrts_gui_log_path.open("w", encoding="utf-8", errors="replace")
        log_handle.write("Command: " + " ".join(command) + "\n")
        log_handle.write(f"Prompt: {prompt_path}\nOpponent: {opponent}\nMap: {map_location}\n")
        if trace_path is not None:
            log_handle.write(f"Trace: {trace_path}\n")
            self.selected_trace.set(str(trace_path))
            self.refresh_trace_choices()
        log_handle.write("EAGLE debug: enabled\n\n")
        log_handle.flush()
        try:
            self.microrts_gui_process = subprocess.Popen(
                command,
                cwd=microrts_root,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as exc:
            log_handle.close()
            messagebox.showerror("Could not launch MicroRTS", str(exc))
            return
        self.microrts_gui_status.set(f"MicroRTS PID {self.microrts_gui_process.pid}")
        self.refresh_microrts_gui_log()

    def stop_microrts_java_gui(self) -> None:
        """Terminate the Java MicroRTS process launched from the GUI tab."""
        if not self.microrts_gui_process or self.microrts_gui_process.poll() is not None:
            self.microrts_gui_status.set("Java GUI not running")
            return
        self.microrts_gui_process.terminate()
        self.microrts_gui_status.set(f"Stopping MicroRTS PID {self.microrts_gui_process.pid}")

    def stop_process(self) -> None:
        """Terminate the process launched from this GUI."""
        if not self.is_monitored_process_running():
            self.status.set("No running process")
            return
        pid = self.monitored_process_pid or (self.process.pid if self.process else None)
        if self.process and self.process.poll() is None:
            self.process.terminate()
        elif pid is not None:
            terminate_process_tree(pid)
        self.mark_process_state_stopped()
        self.status.set(f"Stopping PID {pid}")

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
        self.refresh_timing(run_dir)
        self.refresh_prompts(run_dir)

    def refresh_process_log(self) -> None:
        """Refresh process output and status."""
        self.attach_existing_process()
        if self.process and self.process.poll() is not None:
            self.status.set(f"Process exited with code {self.process.returncode}")
            self.mark_process_state_exited(self.process.returncode)
        elif self.monitored_process_pid is not None:
            if process_is_running(self.monitored_process_pid):
                self.status.set(f"Monitoring PID {self.monitored_process_pid}")
            else:
                self.status.set(f"Process PID {self.monitored_process_pid} is not running")
                self.mark_process_state_exited(None)
        if self.process_log_path:
            self._set_text_preserve_scroll(self.process_output, read_tail(self.process_log_path, 18000))

    def attach_existing_process(self) -> None:
        """Attach the GUI monitor to the last run process state if it is still alive."""
        if self.process and self.process.poll() is None:
            self.monitored_process_pid = int(self.process.pid)
            return
        state = load_json_file(GUI_PROCESS_STATE_PATH)
        pid = parse_optional_pid(state.get("pid"))
        log_path = resolve_repo_path(str(state.get("log_path") or "")) if state.get("log_path") else None
        if log_path is not None and log_path.exists():
            self.process_log_path = log_path
        if pid is None:
            return
        self.monitored_process_pid = pid
        if process_is_running(pid):
            self.status.set(f"Monitoring existing PID {pid}")
        elif state.get("status") == "running":
            self.status.set(f"Last PID {pid} is not running")
            self.mark_process_state_exited(None)

    def is_monitored_process_running(self) -> bool:
        """Return whether the current or restored experiment process is alive."""
        if self.process and self.process.poll() is None:
            self.monitored_process_pid = int(self.process.pid)
            return True
        if self.monitored_process_pid is not None:
            return process_is_running(self.monitored_process_pid)
        return False

    def write_process_state(
        self,
        *,
        pid: int,
        command: list[str],
        log_path: Path,
        config_path: Path,
    ) -> None:
        """Persist enough process metadata for a reopened GUI to resume monitoring."""
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        write_json_file(
            GUI_PROCESS_STATE_PATH,
            {
                "status": "running",
                "pid": int(pid),
                "command": list(command),
                "cwd": str(ROOT),
                "log_path": str(log_path),
                "config_path": str(config_path),
                "started_at": datetime.now().isoformat(timespec="seconds"),
            },
        )

    def mark_process_state_stopped(self) -> None:
        """Mark the persisted process state as intentionally stopped."""
        state = load_json_file(GUI_PROCESS_STATE_PATH)
        if not state:
            return
        state["status"] = "stopping"
        state["stopped_at"] = datetime.now().isoformat(timespec="seconds")
        write_json_file(GUI_PROCESS_STATE_PATH, state)

    def mark_process_state_exited(self, returncode: int | None) -> None:
        """Mark the persisted process state as no longer running."""
        state = load_json_file(GUI_PROCESS_STATE_PATH)
        if not state:
            return
        state["status"] = "exited"
        state["exited_at"] = datetime.now().isoformat(timespec="seconds")
        if returncode is not None:
            state["returncode"] = int(returncode)
        write_json_file(GUI_PROCESS_STATE_PATH, state)

    def close_window(self) -> None:
        """Close the GUI without terminating a running experiment process."""
        if self.is_monitored_process_running():
            self.status.set(f"Detached from PID {self.monitored_process_pid}")
        self.root.destroy()

    def refresh_microrts_gui_log(self) -> None:
        """Refresh the Java MicroRTS GUI log panel."""
        if self.microrts_gui_process and self.microrts_gui_process.poll() is not None:
            self.microrts_gui_status.set(f"MicroRTS exited with code {self.microrts_gui_process.returncode}")
            self.refresh_trace_choices()
        if self.microrts_gui_log_path and hasattr(self, "microrts_gui_output"):
            self._set_text_preserve_scroll(self.microrts_gui_output, read_text_file(self.microrts_gui_log_path))

    def refresh_analysis(self, run_dir: Path | None) -> None:
        """Refresh GA/MO analysis for one run."""
        if run_dir is None:
            self.analysis_summary.set("No run selected")
            self._set_text(self.analysis_output, "")
            return
        report = build_live_analysis_report(run_dir)
        self.analysis_summary.set(report.summary)
        self._set_text(self.analysis_output, report.body)

    def refresh_timing(self, run_dir: Path | None) -> None:
        """Refresh timing analysis for one run."""
        if not hasattr(self, "timing_table"):
            return
        self.timing_table.delete(*self.timing_table.get_children())
        if run_dir is None:
            self.timing_summary.set("No run selected")
            self._set_text(self.timing_output, "")
            return
        report = build_timing_analysis_report(run_dir)
        self.timing_summary.set(report.summary)
        for row in report.rows:
            self.timing_table.insert(
                "",
                "end",
                values=(
                    row.get("phase", ""),
                    row.get("count", ""),
                    f"{float(row.get('total_sec', 0.0)):.3f}",
                    f"{float(row.get('avg_sec', 0.0)):.3f}",
                    f"{float(row.get('max_sec', 0.0)):.3f}",
                ),
            )
        self._set_text(self.timing_output, report.body)

    def refresh_prompts(self, run_dir: Path | None) -> None:
        """Refresh prompt list from the latest generation evaluation profiles."""
        previous = self.selected_prompt_id()
        self.prompt_table.delete(*self.prompt_table.get_children())
        self.loaded_prompts = load_prompts(run_dir) if run_dir else {}
        for prompt_id, record in self.loaded_prompts.items():
            self.prompt_table.insert(
                "",
                "end",
                iid=prompt_id,
                values=(
                    record.get("generation", ""),
                    record.get("individual_id", ""),
                    record.get("evaluation_mode", ""),
                    record.get("opponent", ""),
                ),
            )
        if previous in self.loaded_prompts:
            self.prompt_table.selection_set(previous)
        elif self.loaded_prompts:
            self.prompt_table.selection_set(next(iter(self.loaded_prompts)))
        self.show_selected_prompt()

    # ------------------------------------------------------------------
    # Current selection helpers and text widget helpers
    # ------------------------------------------------------------------

    def show_selected_prompt(self, _event: object | None = None) -> None:
        """Show the selected evaluated individual's prompt and LLM outputs."""
        prompt_id = self.selected_prompt_id()
        record = self.loaded_prompts.get(prompt_id or "")
        if not record:
            self.prompt_metadata.set("No prompt selected")
            self._set_text(self.individual_prompt_output, "No prompt text found.")
            self._set_text(self.llm_response_output, "No LLM response selected.")
            return
        metadata = prompt_record_metadata(record)
        self.prompt_metadata.set(" | ".join(metadata))
        self._set_text(
            self.individual_prompt_output,
            str(record.get("prompt") or "No prompt text recorded."),
        )
        self._set_text(
            self.llm_response_output,
            str(record.get("llm_output") or "No LLM response recorded for this evaluation."),
        )

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

    def _set_text_preserve_scroll(self, widget: ScrolledText, text: str) -> None:
        """Replace text without forcing an unrelated scroll jump."""
        current = widget.get("1.0", "end-1c")
        if current == text:
            return
        top_index = widget.index("@0,0")
        _first, last = widget.yview()
        was_at_bottom = last >= 0.995
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        if was_at_bottom:
            widget.see("end")
        else:
            try:
                widget.yview(top_index)
            except Exception:
                pass

    def _schedule_refresh(self) -> None:
        """Periodically refresh process output and selected-run analysis."""
        self.refresh_process_log()
        self.refresh_microrts_gui_log()
        run_dir = self.current_run_dir()
        self.refresh_analysis(run_dir)
        self.refresh_timing(run_dir)
        self.refresh_prompts(run_dir)
        self.root.after(3000, self._schedule_refresh)


# ----------------------------------------------------------------------
# Live-analysis payload and primitive form parsers
# ----------------------------------------------------------------------

class AnalysisReport:
    """Live-analysis display payload."""

    def __init__(self, summary: str, body: str, rows: list[dict[str, Any]] | None = None) -> None:
        """Store one summary line and full report body."""
        self.summary = summary
        self.body = body
        self.rows = list(rows or [])


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


# ----------------------------------------------------------------------
# Prompt feature parsing and training-example synthesis helpers
# ----------------------------------------------------------------------

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


# ----------------------------------------------------------------------
# Validation, path, and file helpers
# ----------------------------------------------------------------------

def normalize_probability_map(weights: dict[str, float], field_name: str) -> None:
    """Normalize one non-empty probability map in-place."""
    total = sum(weights.values())
    if total <= 0:
        raise ValueError(f"{field_name} must have a positive total weight.")
    for key in list(weights):
        weights[key] = weights[key] / total


def read_json_mapping_strict(path: Path) -> dict[str, Any]:
    """Load one JSON object from disk and reject non-object payloads."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Config JSON must be an object: {path}")
    return payload


def merge_config_payload(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge config mappings while letting lists and scalars override."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = merge_config_payload(current, value)
        else:
            merged[key] = value
    return merged


def load_complete_config_payload(config_path: Path) -> dict[str, Any]:
    """Return a complete config payload using default.json as the schema base."""
    payload: dict[str, Any] = {}
    if DEFAULT_CONFIG.exists():
        payload = merge_config_payload(payload, read_json_mapping_strict(DEFAULT_CONFIG))
    if config_path.exists() and config_path.resolve() != DEFAULT_CONFIG.resolve():
        payload = merge_config_payload(payload, read_json_mapping_strict(config_path))
    elif config_path.exists() and not payload:
        payload = merge_config_payload(payload, read_json_mapping_strict(config_path))
    return payload


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


def microrts_root_path() -> Path:
    """Return the vendored MicroRTS root path for GUI file discovery."""
    return ROOT / "third_party" / "microrts"


def require_microrts_class(class_file: str) -> Path:
    """Return MicroRTS root if a required WSL-built class is available."""
    microrts_root = microrts_root_path()
    required = microrts_root / "bin" / class_file
    if not required.exists():
        raise FileNotFoundError(
            "Missing MicroRTS class file. Compile from WSL first:\n"
            "cd /mnt/d/Project/EAGLE/third_party/microrts && "
            "find src -name '*.java' | sort > /tmp/eagle_microrts_sources.txt && "
            "javac -encoding UTF-8 -cp 'lib/gson-2.10.1.jar:lib/minimal-json-0.9.4.jar:lib/jdom.jar:"
            "lib/junit-4.12.jar:lib/hamcrest-all-1.3.jar:lib/weka.jar' "
            "-sourcepath src -d bin @/tmp/eagle_microrts_sources.txt"
        )
    return microrts_root


def microrts_map_dir_choices() -> tuple[str, ...]:
    """Return first-level MicroRTS map folders under `maps/`."""
    maps_dir = microrts_root_path() / "maps"
    if not maps_dir.exists():
        return ("8x8",)
    choices = sorted(path.name for path in maps_dir.iterdir() if path.is_dir())
    return tuple(choices) if choices else ("8x8",)


def microrts_map_file_choices(map_dir: str) -> tuple[str, ...]:
    """Return XML map filenames inside one first-level map folder."""
    normalized_dir = str(map_dir or "").strip()
    maps_dir = microrts_root_path() / "maps" / normalized_dir
    if not maps_dir.exists():
        return ("basesWorkers8x8.xml",)
    choices = sorted(path.name for path in maps_dir.glob("*.xml") if path.is_file())
    return tuple(choices) if choices else ("basesWorkers8x8.xml",)


def microrts_trace_dir() -> Path:
    """Return the GUI-visible MicroRTS trace directory."""
    return ROOT / "logs" / "microrts" / "traces"


def microrts_trace_choices() -> list[Path]:
    """Return saved trace files newest first."""
    roots = [
        microrts_trace_dir(),
        ROOT / "logs" / "microrts",
        ROOT / "logs" / "eagle",
    ]
    paths: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for pattern in ("*.xml", "*.zip"):
            for path in root.rglob(pattern):
                if not path.is_file() or path in seen:
                    continue
                seen.add(path)
                paths.append(path)
    return sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)


def read_tail(path: Path, limit: int) -> str:
    """Read a text file tail."""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[-limit:]


def read_text_file(path: Path) -> str:
    """Read a whole text file for log panels that must stay browseable from the start."""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def load_json_file(path: Path) -> dict[str, Any]:
    """Load one JSON mapping, returning an empty mapping on missing or invalid data."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    """Write one JSON mapping with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_optional_pid(value: Any) -> int | None:
    """Parse a process id from persisted GUI process state."""
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def process_is_running(pid: int | None) -> bool:
    """Return whether a process id is currently alive."""
    if pid is None:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            int(pid),
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return ctypes.windll.kernel32.GetLastError() == 5
    try:
        os.kill(int(pid), 0)
    except ValueError:
        return False
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def terminate_process_tree(pid: int) -> None:
    """Terminate a restored process id, including children where the platform supports it."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if process_is_running(pid):
            try:
                os.kill(int(pid), signal.SIGTERM)
            except OSError:
                return
        return
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError:
        return


# ----------------------------------------------------------------------
# Run artifact and prompt-record loading
# ----------------------------------------------------------------------

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


def load_prompts(run_dir: Path | None) -> dict[str, dict[str, Any]]:
    """Extract latest-generation evaluated prompt records for the prompt inspector."""
    if run_dir is None:
        return {}
    profile_records = latest_generation_profile_records(run_dir)
    checkpoint_records = latest_generation_checkpoint_prompt_records(run_dir)
    if profile_records and checkpoint_records:
        if records_latest_generation(checkpoint_records) > records_latest_generation(profile_records):
            return checkpoint_records
        return profile_records
    if profile_records:
        return profile_records
    if checkpoint_records:
        return checkpoint_records
    return generation_log_prompt_records(run_dir)


def latest_generation_profile_records(run_dir: Path) -> dict[str, dict[str, Any]]:
    """Return profile rows for the latest generation present in profiles.jsonl."""
    rows = load_jsonl_rows(run_dir / "profiles.jsonl")
    rows = [row for row in rows if row.get("record_type") == "evaluation"]
    if not rows:
        return {}
    latest_generation = latest_generation_value([row.get("generation") for row in rows])
    latest_rows = [row for row in rows if row.get("generation") == latest_generation]
    records: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(latest_rows, start=1):
        prompt = str(row.get("prompt") or "")
        if not prompt:
            continue
        record = dict(row)
        record["raw_generation"] = row.get("generation")
        record["generation"] = display_generation(row.get("generation"))
        record["prompt"] = prompt
        record["llm_output"] = llm_output_from_profile_record(record)
        record_id = prompt_record_id(record, index)
        records[record_id] = record
    return records


def latest_generation_checkpoint_prompt_records(run_dir: Path) -> dict[str, dict[str, Any]]:
    """Return prompt rows from the latest checkpoint generation when profiles are absent."""
    rows = load_checkpoint_rows(run_dir)
    if not rows:
        population = load_population(run_dir)
        rows = [{"generation": "state", "phase": "run_state", "individual": item} for item in population]
    if not rows:
        return {}
    latest_generation = latest_generation_value([row.get("generation") for row in rows])
    latest_rows = [row for row in rows if row.get("generation") == latest_generation]
    records: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(latest_rows, start=1):
        item = dict(row.get("individual") or {})
        prompt = str(item.get("rendered_prompt") or "")
        if not prompt:
            continue
        evaluation = prompt_evaluation_from_individual(item)
        record = {
            "raw_generation": row.get("generation"),
            "generation": display_generation(row.get("generation")),
            "phase": row.get("phase", ""),
            "individual_id": item.get("id"),
            "evaluation_mode": item.get("evaluation_mode") or evaluation.get("evaluation_mode", ""),
            "opponent": "",
            "prompt": prompt,
            "llm_output": llm_output_from_evaluation(evaluation),
            "fitness": item.get("fitness"),
        }
        records[prompt_record_id(record, index)] = record
    return records


def generation_log_prompt_records(run_dir: Path) -> dict[str, dict[str, Any]]:
    """Fallback prompt extraction from human-readable generation logs."""
    records: dict[str, dict[str, Any]] = {}
    paths = sorted(run_dir.glob("generation*.txt"))
    if not paths:
        return records
    latest_path = paths[-1]
    text = latest_path.read_text(encoding="utf-8", errors="replace")
    for index, block in enumerate(text.split("Prompt:\n")[1:], start=1):
        prompt = block.split("\nIndividual(", 1)[0].split("\nPopulation", 1)[0].strip()
        if not prompt:
            continue
        record = {
            "generation": latest_path.stem,
            "individual_id": f"prompt-{index}",
            "evaluation_mode": "generation_log",
            "opponent": "",
            "prompt": prompt,
            "llm_output": "No LLM output recorded in generation log.",
        }
        records[prompt_record_id(record, index)] = record
    return records


def latest_generation_value(values: list[Any]) -> Any:
    """Return the newest internal generation value, treating numeric generations as ordered."""
    numeric_values: list[int] = []
    for value in values:
        try:
            numeric_values.append(int(value))
        except (TypeError, ValueError):
            continue
    if numeric_values:
        return max(numeric_values)
    return latest_value(values)


def records_latest_generation(records: dict[str, dict[str, Any]]) -> int:
    """Return the newest internal generation value from loaded prompt records."""
    values = [record.get("raw_generation", record.get("generation")) for record in records.values()]
    generation = latest_generation_value(values)
    try:
        return int(generation)
    except (TypeError, ValueError):
        return -1


def display_generation(value: Any) -> Any:
    """Convert an internal zero-based generation into the GUI's human-readable generation."""
    try:
        return int(value) + 1
    except (TypeError, ValueError):
        return value


def load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    """Load JSONL rows, skipping malformed lines."""
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line.lstrip("\ufeff"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def prompt_record_id(record: dict[str, Any], index: int) -> str:
    """Build a stable prompt-table row id."""
    parts = [
        str(record.get("generation", "")),
        str(record.get("individual_id", "")),
        str(record.get("opponent", "")),
        str(index),
    ]
    return "|".join(part.replace("|", "/") for part in parts)


def prompt_evaluation_from_individual(item: dict[str, Any]) -> dict[str, Any]:
    """Return the most detailed evaluation object stored on one checkpointed individual."""
    for key in ("last_round_evaluation", "last_gameplay_evaluation", "last_surrogate_evaluation"):
        value = item.get(key)
        if isinstance(value, dict) and value:
            return dict(value)
    return {}


def llm_output_from_profile_record(record: dict[str, Any]) -> str:
    """Return all LLM outputs attached to one profile row."""
    if isinstance(record.get("round_samples"), list):
        return format_round_samples(record["round_samples"])
    output = llm_output_from_log_path(record.get("log_path"))
    if output:
        return output
    return "No LLM output recorded for this evaluation."


def llm_output_from_evaluation(evaluation: dict[str, Any]) -> str:
    """Return all LLM outputs attached to one checkpoint evaluation object."""
    samples = evaluation.get("samples")
    if isinstance(samples, list):
        return format_round_samples(samples)
    if evaluation.get("raw_response"):
        return str(evaluation["raw_response"])
    per_opponent = evaluation.get("per_opponent")
    if isinstance(per_opponent, list):
        sections = []
        for item in per_opponent:
            if not isinstance(item, dict):
                continue
            output = llm_output_from_log_path(item.get("log_path"))
            if output:
                sections.append(f"Opponent: {item.get('opponent', '')}\n{output}")
        if sections:
            return "\n\n".join(sections)
    return "No LLM output recorded for this evaluation."


def format_round_samples(samples: list[Any]) -> str:
    """Format every round-sample LLM response."""
    sections: list[str] = []
    for index, sample in enumerate(samples, start=1):
        if not isinstance(sample, dict):
            continue
        response = str(sample.get("raw_response") or "")
        dynamic_prompt = str(sample.get("dynamic_prompt") or "")
        sections.append(
            f"Sample {sample.get('sample', index)}\n"
            f"Dynamic prompt:\n{dynamic_prompt}\n\n"
            f"LLM output:\n{response}"
        )
    return "\n\n".join(sections) if sections else "No fresh LLM samples; this evaluation reused history."


def llm_output_from_log_path(path_value: Any) -> str:
    """Parse every raw LLM response from one MicroRTS gameplay log."""
    if not path_value:
        return ""
    path = resolve_runtime_log_path(str(path_value))
    if not path.exists():
        return f"Log file not found: {path_value}"
    try:
        parsed = parse_log_file(path)
    except (OSError, ValueError) as exc:
        return f"Could not parse log file {path}:\n{exc}"
    sections: list[str] = []
    for segment in parsed.get("segments", []):
        if not isinstance(segment, dict):
            continue
        response = segment.get("raw_llm_response_text")
        if not response:
            continue
        sections.append(
            f"Turn {segment.get('current_time', segment.get('segment_index', ''))}\n{response}"
        )
    return "\n\n".join(sections)


def resolve_runtime_log_path(path_text: str) -> Path:
    """Resolve Windows, repo-relative, or WSL-mounted runtime log paths."""
    normalized = path_text.replace("\\", "/")
    drive_match = re.fullmatch(r"/mnt/([a-zA-Z])/(.*)", normalized)
    if drive_match:
        drive = drive_match.group(1).upper()
        rest = drive_match.group(2).replace("/", "\\")
        return Path(f"{drive}:\\{rest}")
    return resolve_repo_path(path_text)


def prompt_record_metadata(record: dict[str, Any]) -> list[str]:
    """Format one prompt record's metadata for the prompt inspector header."""
    metadata = [
        f"Generation: {record.get('generation', '')}",
        f"Individual: {record.get('individual_id', '')}",
        f"Mode: {record.get('evaluation_mode', '')}",
    ]
    opponent = record.get("opponent")
    if opponent:
        metadata.append(f"Opponent: {opponent}")
    fitness = record.get("fitness")
    if fitness not in (None, ""):
        metadata.append(f"Fitness: {fitness}")
    return metadata


# ----------------------------------------------------------------------
# Live GA/MO analysis formatting
# ----------------------------------------------------------------------

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


def build_timing_analysis_report(run_dir: Path) -> AnalysisReport:
    """Build timing analysis from run-level and per-evaluation profile artifacts."""
    summary = load_json_file(run_dir / "timing_summary.json")
    profile_rows = load_jsonl_rows(run_dir / "profiles.jsonl")
    timing_rows = list(summary.get("top_phases") or [])
    if not timing_rows:
        timing_rows = aggregate_timing_rows_from_profiles(profile_rows)

    report_path = run_dir / "timing_report.md"
    lines = [
        f"Run: {run_dir}",
        f"Timing events: {summary.get('event_count', 0)}",
        f"Total recorded seconds: {float(summary.get('total_recorded_sec', 0.0)):.3f}",
        "",
        "Bottlenecks:",
    ]
    if timing_rows:
        for row in timing_rows[:12]:
            lines.append(
                f"  {row.get('phase')}: total={float(row.get('total_sec', 0.0)):.3f}s "
                f"count={int(row.get('count', 0))} avg={float(row.get('avg_sec', 0.0)):.3f}s"
            )
    else:
        lines.append("  no timing data found yet")

    lines.extend(["", "Evaluation profile totals:"])
    profile_totals = aggregate_named_profile_times(profile_rows)
    if profile_totals:
        for row in profile_totals[:12]:
            lines.append(
                f"  {row['phase']}: total={row['total_sec']:.3f}s "
                f"count={row['count']} avg={row['avg_sec']:.3f}s"
            )
    else:
        lines.append("  no profile timing rows found yet")

    recommendations = list(summary.get("recommendations") or [])
    for item in timing_recommendations(timing_rows, profile_totals):
        if item not in recommendations:
            recommendations.append(item)
    lines.extend(["", "Recommendations:"])
    for item in recommendations:
        lines.append(f"  - {item}")

    if report_path.exists():
        lines.extend(["", "Saved report:", str(report_path)])
    return AnalysisReport(
        summary=f"timing phases={len(timing_rows)} profiles={len(profile_rows)}",
        body="\n".join(lines),
        rows=timing_rows,
    )


def aggregate_timing_rows_from_profiles(profile_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fallback phase rows when timing_summary.json is not available."""
    return aggregate_named_profile_times(profile_rows)


def aggregate_named_profile_times(profile_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate numeric `*_time` profile fields across evaluation rows."""
    totals: dict[str, dict[str, float]] = {}
    for row in profile_rows:
        for key, value in row.items():
            if not str(key).endswith("_time") or not is_number(value):
                continue
            stats = totals.setdefault(str(key), {"count": 0.0, "total_sec": 0.0, "max_sec": 0.0})
            elapsed = float(value)
            stats["count"] += 1.0
            stats["total_sec"] += elapsed
            stats["max_sec"] = max(stats["max_sec"], elapsed)
    rows: list[dict[str, Any]] = []
    for phase, stats in totals.items():
        count = max(1.0, stats["count"])
        rows.append(
            {
                "phase": phase,
                "count": int(stats["count"]),
                "total_sec": stats["total_sec"],
                "avg_sec": stats["total_sec"] / count,
                "max_sec": stats["max_sec"],
            }
        )
    return sorted(rows, key=lambda item: item["total_sec"], reverse=True)


def timing_recommendations(
    timing_rows: list[dict[str, Any]],
    profile_totals: list[dict[str, Any]],
) -> list[str]:
    """Return simple GUI recommendations from timing rows."""
    rows = list(timing_rows) + list(profile_totals)
    if not rows:
        return ["No timing data has been recorded yet."]
    top_phase = str(rows[0].get("phase") or "")
    hints: list[str] = []
    if "game" in top_phase or "evaluate" in top_phase:
        hints.append("Evaluation is the main cost; reduce game seconds, opponents, gameplay_rate, or one_eval_rounds.")
    if any(str(row.get("phase")) == "microrts_compile_time" and float(row.get("total_sec", 0.0)) > 1.0 for row in rows):
        hints.append("MicroRTS compile time is visible; repeated runs should benefit from incremental compile skipping.")
    if any("round_llm" in str(row.get("phase")) for row in rows):
        hints.append("Round LLM calls are visible; prompt-history reuse and fewer round samples will speed iteration.")
    hints.append("Python precompile is useful for import/startup overhead, not for Java or LLM-heavy sections.")
    return hints


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
