"""Canonical dark visual system for every EAGLE GUI surface."""
from __future__ import annotations
from nicegui import ui

COLORS = {"background":"#07111f","surface":"#0f1d2e","surface_alt":"#16263a","border":"#2d4059","raven_blue":"#1f4e79","sky_blue":"#38bdf8","bronze":"#b08d57","text":"#e5e7eb","muted":"#94a3b8","success":"#22c55e","error":"#ef4444","warning":"#f59e0b","info":"#60a5fa","disabled":"#64748b","input":"#12243a","log":"#050b14"}
CARD_CLASS="eagle-card"; INPUT_CLASS="eagle-input"; TEXTAREA_CLASS="eagle-textarea"; BUTTON_CLASS="eagle-button"; MONO_CLASS="eagle-mono"

def install_theme() -> None:
    ui.dark_mode().enable()
    ui.colors(primary=COLORS["raven_blue"], secondary=COLORS["surface_alt"], accent=COLORS["bronze"], positive=COLORS["success"], negative=COLORS["error"])
    ui.add_head_html(f'''<style>
:root {{ --eagle-bg:{COLORS['background']}; --eagle-surface:{COLORS['surface']}; --eagle-surface-raised:{COLORS['surface_alt']}; --eagle-text:{COLORS['text']}; --eagle-text-muted:{COLORS['muted']}; --eagle-text-disabled:{COLORS['disabled']}; --eagle-border:{COLORS['border']}; --eagle-input-bg:{COLORS['input']}; --eagle-input-text:{COLORS['text']}; --eagle-placeholder:{COLORS['muted']}; --eagle-hover:#1d3553; --eagle-selected:#244d73; --eagle-success:{COLORS['success']}; --eagle-warning:{COLORS['warning']}; --eagle-error:{COLORS['error']}; --eagle-info:{COLORS['info']}; --eagle-log-bg:{COLORS['log']}; --eagle-log-text:#dbeafe; }}
html,body,#app,.nicegui-content {{ background:var(--eagle-bg); color:var(--eagle-text); font-family:Inter,ui-sans-serif,system-ui,sans-serif; }}
.{CARD_CLASS} {{ background:var(--eagle-surface); border:1px solid var(--eagle-border); border-radius:8px; padding:16px; color:var(--eagle-text); }}
.q-field__control,.{INPUT_CLASS} .q-field__control,.{TEXTAREA_CLASS} .q-field__control {{ background:var(--eagle-input-bg); color:var(--eagle-input-text); }}
.q-field__native,.q-field__input,.q-field__label,.q-field__marginal,.q-field__bottom,.q-field__messages,.q-checkbox__label,.q-radio__label {{ color:var(--eagle-text) !important; }}
.q-field__native::placeholder,.q-field__input::placeholder {{ color:var(--eagle-placeholder) !important; opacity:1; }}
.q-field--disabled {{ opacity:.72; }} input:-webkit-autofill,textarea:-webkit-autofill {{ -webkit-text-fill-color:var(--eagle-input-text); box-shadow:0 0 0 1000px var(--eagle-input-bg) inset; }}
.q-card,.q-menu,.q-dialog__inner>div,.q-tab-panels,.q-expansion-item,.q-table__container,.q-table__card {{ background:var(--eagle-surface); color:var(--eagle-text); }}
.q-tab {{ color:var(--eagle-text-muted); }} .q-tab--active {{ color:var(--eagle-info); }} .q-table thead,.q-table th {{ background:var(--eagle-surface-raised); color:var(--eagle-text); }} .q-table tbody td {{ color:var(--eagle-text); border-color:var(--eagle-border); }} .q-table tbody tr:hover {{ background:var(--eagle-hover); }}
.q-menu,.q-notification,.q-tooltip {{ background:var(--eagle-surface-raised); color:var(--eagle-text); border:1px solid var(--eagle-border); }} .q-btn {{ color:var(--eagle-text); }} .q-btn:hover {{ background:var(--eagle-hover); }}
.eagle-log {{ background:var(--eagle-log-bg); color:var(--eagle-log-text); border:1px solid var(--eagle-border); padding:12px; border-radius:8px; }} .eagle-log textarea {{ color:var(--eagle-log-text) !important; background:var(--eagle-log-bg) !important; white-space:pre-wrap; overflow-wrap:anywhere; user-select:text; }}
.eagle-empty,.eagle-loading,.eagle-error {{ background:var(--eagle-surface); border:1px dashed var(--eagle-border); color:var(--eagle-text-muted); padding:20px; border-radius:8px; }} .eagle-error {{ color:#fecaca; border-color:var(--eagle-error); }} .echarts,.echarts canvas {{ background:var(--eagle-surface) !important; }} pre,code {{ background:var(--eagle-log-bg); color:var(--eagle-log-text); }}
.{BUTTON_CLASS} {{ border:1px solid var(--eagle-info); }} .{MONO_CLASS},textarea {{ font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }}
</style>''')