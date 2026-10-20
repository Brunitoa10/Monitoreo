"""Estilos y paleta de la UI (los colores de estado están reservados para estados)."""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

from nemesis.domain.enums import Status

INK = "#0f172a"
MUTED = "#64748b"
GRID = "#e2e8f0"
SURFACE = "#ffffff"
ACCENT = "#1e3a8a"

# Paleta categórica validada (orden fijo, nunca ciclar): para tipos/sitios.
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
STATUS_COLORS = {s.value: s.color for s in Status}
STATUS_ICON = {
    Status.HEALTHY.value: "🟢", Status.WARNING.value: "🟠", Status.CRITICAL.value: "🔴",
    Status.AVAILABLE.value: "⚪", Status.UNKNOWN.value: "⚫",
}

CSS = f"""
<style>
.block-container {{ padding-top: 3.2rem; padding-bottom: 2rem; max-width: 1500px; }}
h1, h2, h3 {{ color: {INK}; letter-spacing: -0.01em; }}
.nm-header {{ display:flex; justify-content:space-between; align-items:flex-end; flex-wrap:wrap; gap:.5rem;
             border-bottom:1px solid {GRID}; padding-bottom:.6rem; margin-bottom:1rem; }}
.nm-header .t {{ font-size:1.6rem; font-weight:700; color:{INK}; line-height:1.1; }}
.nm-header .s {{ color:{MUTED}; font-size:.85rem; }}
.nm-pill {{ display:inline-block; padding:.15rem .55rem; border-radius:999px; font-size:.75rem; font-weight:600;
           border:1px solid {GRID}; background:#f8fafc; color:{INK}; margin-left:.35rem; }}
.nm-pill.ok {{ background:#dcfce7; border-color:#bbf7d0; color:#166534; }}
.nm-pill.warn {{ background:#fef3c7; border-color:#fde68a; color:#92400e; }}
.nm-pill.bad {{ background:#fee2e2; border-color:#fecaca; color:#991b1b; }}
.nm-kpi {{ border:1px solid {GRID}; border-radius:12px; padding:.85rem 1rem; background:{SURFACE};
          box-shadow:0 1px 2px rgba(15,23,42,.04); height:100%; }}
.nm-kpi .l {{ color:{MUTED}; font-size:.72rem; text-transform:uppercase; letter-spacing:.06em; font-weight:600; }}
.nm-kpi .v {{ color:{INK}; font-size:1.75rem; font-weight:700; line-height:1.25; font-variant-numeric:tabular-nums; }}
.nm-kpi .d {{ color:{MUTED}; font-size:.78rem; }}
.nm-kpi.bad {{ border-left:4px solid {Status.CRITICAL.color}; }}
.nm-kpi.warn {{ border-left:4px solid {Status.WARNING.color}; }}
.nm-kpi.ok {{ border-left:4px solid {Status.HEALTHY.color}; }}
.nm-insight {{ border:1px solid {GRID}; border-left-width:4px; border-radius:10px; padding:.7rem .9rem;
              margin-bottom:.55rem; background:{SURFACE}; }}
.nm-insight .h {{ font-weight:650; color:{INK}; }}
.nm-insight .b {{ color:#334155; font-size:.86rem; margin-top:.15rem; }}
.nm-insight .r {{ color:{INK}; font-size:.86rem; margin-top:.35rem; }}
.nm-insight .r b {{ color:{ACCENT}; }}
</style>
"""


def _template() -> go.layout.Template:
    t = go.layout.Template()
    t.layout = go.Layout(
        font=dict(family="Inter, Segoe UI, sans-serif", size=12, color=INK),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, colorway=CATEGORICAL,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(showgrid=False, linecolor=GRID, tickcolor=GRID, tickfont=dict(color=MUTED)),
        yaxis=dict(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont=dict(color=MUTED)),
        legend=dict(orientation="h", yanchor="top", y=-0.12, x=0, font=dict(color=MUTED)),
        hoverlabel=dict(bgcolor="white", font=dict(color=INK), bordercolor=GRID),
        title=dict(font=dict(size=14, color=INK), x=0, xanchor="left"),
    )
    return t


pio.templates["nemesis"] = _template()
pio.templates.default = "nemesis"
