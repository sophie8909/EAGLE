"""Restored Ravenclaw-inspired NiceGUI theme."""

from __future__ import annotations

from nicegui import ui


COLORS = {
    "background": "#07111f",
    "surface": "#0f1d2e",
    "surface_alt": "#16263a",
    "border": "#2d4059",
    "raven_blue": "#1f4e79",
    "sky_blue": "#38bdf8",
    "bronze": "#b08d57",
    "text": "#e5e7eb",
    "muted": "#94a3b8",
    "success": "#22c55e",
    "error": "#ef4444",
}

CARD_CLASS = "eagle-card"
INPUT_CLASS = "eagle-input"
TEXTAREA_CLASS = "eagle-textarea"
BUTTON_CLASS = "eagle-button"
MONO_CLASS = "eagle-mono"


def install_theme() -> None:
    ui.colors(
        primary=COLORS["raven_blue"],
        secondary=COLORS["surface_alt"],
        accent=COLORS["bronze"],
        positive=COLORS["success"],
        negative=COLORS["error"],
    )
    ui.add_head_html(
        f"""
        <style>
        body, .nicegui-content {{
          background: {COLORS['background']}; color: {COLORS['text']};
          font-family: Inter, ui-sans-serif, system-ui, sans-serif;
        }}
        .{CARD_CLASS} {{
          background: {COLORS['surface']}; border: 1px solid {COLORS['border']};
          border-radius: 8px; padding: 16px; color: {COLORS['text']};
        }}
        .{INPUT_CLASS} .q-field__control, .{TEXTAREA_CLASS} .q-field__control {{
          background: {COLORS['surface_alt']}; color: {COLORS['text']};
        }}
        .{INPUT_CLASS} .q-field__native, .{INPUT_CLASS} .q-field__input,
        .{INPUT_CLASS} .q-field__label, .{TEXTAREA_CLASS} .q-field__native,
        .{TEXTAREA_CLASS} .q-field__label {{ color: {COLORS['text']}; }}
        .{BUTTON_CLASS} {{ border: 1px solid {COLORS['sky_blue']}; }}
        .{MONO_CLASS}, .{TEXTAREA_CLASS} textarea {{
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        }}
        </style>
        """
    )
