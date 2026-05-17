"""Shared Ravenclaw-inspired NiceGUI theme."""

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
    "bronze_dark": "#7c5f35",
    "text": "#e5e7eb",
    "muted": "#94a3b8",
    "success": "#22c55e",
    "warning": "#d99a2b",
    "error": "#ef4444",
}

CARD_CLASS = "eagle-card"
BUTTON_CLASS = "eagle-button"
INPUT_CLASS = "eagle-input"
TEXTAREA_CLASS = "eagle-textarea"
BADGE_CLASS = "eagle-badge"
TAB_CLASS = "eagle-tab"
TABLE_CLASS = "eagle-table"

PAGE_CLASS = "eagle-page"
HEADER_CLASS = "eagle-header"
SECTION_HEADER_CLASS = "eagle-section-header"
ROW_CLASS = "eagle-row"
GRID_CLASS = "eagle-grid"
MONO_CLASS = "eagle-mono"
DANGER_CLASS = "eagle-danger"
SUCCESS_CLASS = "eagle-success"
MUTED_CLASS = "eagle-muted"


def button_class(*, danger: bool = False, success: bool = False) -> str:
    """Return button classes with optional semantic accent."""
    extra = DANGER_CLASS if danger else SUCCESS_CLASS if success else ""
    return f"{BUTTON_CLASS} {extra}".strip()


def status_badge_class(status: str) -> str:
    """Return status badge classes for running and idle states."""
    return f"{BADGE_CLASS} {SUCCESS_CLASS if status.startswith('running') else MUTED_CLASS}"


def height_class(px: int) -> str:
    """Return a fixed-height utility class for stable text panes."""
    return f"h-[{int(px)}px]"


def install_theme() -> None:
    """Install global dashboard colors and component CSS."""
    ui.colors(
        primary=COLORS["raven_blue"],
        secondary=COLORS["surface_alt"],
        accent=COLORS["bronze"],
        positive=COLORS["success"],
        warning=COLORS["warning"],
        negative=COLORS["error"],
    )
    ui.add_head_html(
        f"""
        <style>
        body, .nicegui-content {{
            background: {COLORS["background"]};
            color: {COLORS["text"]};
        }}
        .{PAGE_CLASS} {{
            background: {COLORS["background"]};
            color: {COLORS["text"]};
        }}
        .{HEADER_CLASS} {{
            background: linear-gradient(90deg, {COLORS["surface"]}, {COLORS["raven_blue"]});
            border-bottom: 1px solid {COLORS["border"]};
            color: {COLORS["text"]};
        }}
        .{CARD_CLASS} {{
            background: {COLORS["surface"]};
            border: 1px solid {COLORS["border"]};
            border-radius: 8px;
            padding: 16px;
            color: {COLORS["text"]};
        }}
        .{SECTION_HEADER_CLASS} {{
            color: {COLORS["bronze"]};
            font-weight: 650;
            letter-spacing: 0;
        }}
        .{BUTTON_CLASS} {{
            background: {COLORS["raven_blue"]} !important;
            border: 1px solid {COLORS["sky_blue"]};
            color: {COLORS["text"]} !important;
            border-radius: 6px;
        }}
        .{BUTTON_CLASS}:hover {{
            border-color: {COLORS["bronze"]};
            filter: brightness(1.08);
        }}
        .{BUTTON_CLASS}.{DANGER_CLASS} {{
            background: {COLORS["bronze_dark"]} !important;
            border-color: {COLORS["error"]};
        }}
        .{BUTTON_CLASS}.{SUCCESS_CLASS} {{
            border-color: {COLORS["success"]};
        }}
        .{INPUT_CLASS} .q-field__control,
        .{TEXTAREA_CLASS} .q-field__control {{
            background: {COLORS["surface_alt"]};
            border: 1px solid {COLORS["border"]};
            color: {COLORS["text"]};
        }}
        .{INPUT_CLASS} .q-field__native,
        .{INPUT_CLASS} .q-field__input,
        .{INPUT_CLASS} .q-field__label,
        .{TEXTAREA_CLASS} .q-field__native,
        .{TEXTAREA_CLASS} .q-field__label {{
            color: {COLORS["text"]};
        }}
        .{TEXTAREA_CLASS} textarea {{
            color: {COLORS["text"]};
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        }}
        .{BADGE_CLASS} {{
            background: {COLORS["surface_alt"]};
            border: 1px solid {COLORS["border"]};
            color: {COLORS["text"]};
        }}
        .{BADGE_CLASS}.{SUCCESS_CLASS} {{
            border-color: {COLORS["success"]};
            color: {COLORS["success"]};
        }}
        .{BADGE_CLASS}.{MUTED_CLASS} {{
            color: {COLORS["muted"]};
        }}
        .{TAB_CLASS} {{
            color: {COLORS["muted"]};
        }}
        .{TAB_CLASS}.q-tab--active {{
            color: {COLORS["bronze"]};
        }}
        .{TABLE_CLASS} .q-table__container,
        .{TABLE_CLASS} .q-table,
        .{TABLE_CLASS} .q-table__top,
        .{TABLE_CLASS} .q-table__bottom,
        .{TABLE_CLASS} thead tr,
        .{TABLE_CLASS} tbody tr {{
            background: {COLORS["surface"]};
            color: {COLORS["text"]};
        }}
        .{TABLE_CLASS} th {{
            color: {COLORS["bronze"]};
            border-bottom: 1px solid {COLORS["border"]};
        }}
        .{TABLE_CLASS} td {{
            border-bottom: 1px solid {COLORS["border"]};
        }}
        .q-menu {{
            background: {COLORS["surface_alt"]};
            color: {COLORS["text"]};
            border: 1px solid {COLORS["border"]};
        }}
        </style>
        """
    )
