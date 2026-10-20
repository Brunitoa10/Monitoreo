"""Componentes visuales reutilizables (DRY entre páginas)."""
from __future__ import annotations

import html
from typing import Optional, Sequence

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from nemesis.domain.enums import InsightLevel, Status
from nemesis.domain.models import Insight
from nemesis.reporting.formatting import LEVEL_COLOR, LEVEL_LABEL
from nemesis.ui.theme import CATEGORICAL, GRID, INK, STATUS_ICON


def header(title: str, subtitle: str, pills: Sequence[tuple[str, str]] = ()) -> None:
    pills_html = "".join(f'<span class="nm-pill {cls}">{html.escape(text)}</span>' for text, cls in pills)
    st.markdown(
        f'<div class="nm-header"><div><div class="t">{html.escape(title)}</div>'
        f'<div class="s">{html.escape(subtitle)}</div></div><div>{pills_html}</div></div>',
        unsafe_allow_html=True,
    )


def kpi(label: str, value: str, detail: str = "", tone: str = "") -> None:
    st.markdown(
        f'<div class="nm-kpi {tone}"><div class="l">{html.escape(label)}</div>'
        f'<div class="v">{html.escape(value)}</div><div class="d">{html.escape(detail)}</div></div>',
        unsafe_allow_html=True,
    )


def insight_card(ins: Insight) -> None:
    color = LEVEL_COLOR[ins.level]
    st.markdown(
        f'<div class="nm-insight" style="border-left-color:{color}">'
        f'<div class="h"><span style="color:{color}">{LEVEL_LABEL[ins.level]}</span> · {html.escape(ins.title)}</div>'
        f'<div class="b">{html.escape(ins.detail)}</div>'
        f'<div class="r"><b>Recomendación:</b> {html.escape(ins.recommendation)}</div></div>',
        unsafe_allow_html=True,
    )


def empty(msg: str = "Sin datos para el período/filtros seleccionados.") -> None:
    st.info(msg, icon="ℹ️")


def status_text(value: str) -> str:
    try:
        s = Status(value)
        return f"{STATUS_ICON[value]} {s.label}"
    except ValueError:
        return str(value)


def fmt(value: Optional[float], suffix: str = "", digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{value:,.{digits}f}{suffix}"


def color_map(values: Sequence[str]) -> dict[str, str]:
    """Color fijo por entidad (orden alfabético): un filtro no repinta las series."""
    return {v: CATEGORICAL[i % len(CATEGORICAL)] for i, v in enumerate(sorted(set(values)))}


# ------------------------------------------------------------------ gráficos
def availability_bar(df: pd.DataFrame, column: str, title: str) -> go.Figure:
    df = df.sort_values("disponibilidad_pct", ascending=True)
    fig = go.Figure(go.Bar(
        x=df["disponibilidad_pct"], y=df[column].astype(str), orientation="h", marker_color=CATEGORICAL[0],
        marker_line_width=0, text=[f"{v:.2f}%" for v in df["disponibilidad_pct"]], textposition="outside",
        textfont=dict(color=INK, size=11),
        customdata=df[["equipos", "incidentes"]].values,
        hovertemplate="<b>%{y}</b><br>Disponibilidad %{x:.3f}%<br>Equipos %{customdata[0]}<br>Incidentes %{customdata[1]}<extra></extra>",
    ))
    low = max(0.0, min(float(df["disponibilidad_pct"].min()) - 2, 95.0)) if len(df) else 90
    fig.update_layout(title=title, height=max(240, 34 * len(df) + 90), xaxis_range=[low, 101.5],
                      xaxis_title=None, yaxis_title=None, bargap=0.35, showlegend=False)
    fig.update_xaxes(showgrid=True, gridcolor=GRID, ticksuffix="%")
    fig.update_yaxes(showgrid=False)
    return fig


def status_donut(current: pd.DataFrame) -> go.Figure:
    counts = current["status"].value_counts()
    order = [s for s in (Status.HEALTHY, Status.WARNING, Status.CRITICAL, Status.AVAILABLE, Status.UNKNOWN)
             if counts.get(s.value, 0)]
    fig = go.Figure(go.Pie(
        labels=[s.label for s in order], values=[int(counts[s.value]) for s in order],
        marker=dict(colors=[s.color for s in order], line=dict(color="white", width=2)),
        hole=0.62, sort=False, textinfo="value", textfont=dict(color="white", size=13),
        hovertemplate="%{label}: %{value} equipos (%{percent})<extra></extra>",
    ))
    fig.update_layout(title="Estado actual", height=320, showlegend=True,
                      legend=dict(orientation="v", x=1, y=0.5, yanchor="middle"),
                      annotations=[dict(text=f"<b>{int(counts.sum())}</b><br>equipos", showarrow=False,
                                        font=dict(size=16, color=INK))])
    return fig


def line_chart(df: pd.DataFrame, y: str, by: str | None, title: str, y_title: str,
               colors: dict[str, str] | None = None) -> go.Figure:
    fig = go.Figure()
    groups = df.groupby(by) if by and by in df.columns else [("Total", df)]
    for name, g in groups:
        fig.add_trace(go.Scatter(
            x=g["ts"], y=g[y], mode="lines", name=str(name),
            line=dict(width=2, color=(colors or {}).get(str(name))),
            hovertemplate=f"{name}: %{{y:.2f}}<extra></extra>",
        ))
    fig.update_layout(title=title, height=320, hovermode="x unified", yaxis_title=y_title,
                      showlegend=bool(by))
    return fig


def heatmap(pivot: pd.DataFrame, title: str) -> go.Figure:
    fig = go.Figure(go.Heatmap(
        z=pivot.values, x=[f"{h:02d}h" for h in pivot.columns], y=list(pivot.index),
        colorscale=[[0, "#f8fafc"], [0.2, "#fde68a"], [1, "#b91c1c"]], xgap=2, ygap=2,
        hovertemplate="%{y} %{x}<br>Fallas: %{z:.2f}%<extra></extra>", colorbar=dict(ticksuffix="%"),
    ))
    fig.update_layout(title=title, height=300)
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return fig


DEVICE_COLUMNS = {
    "equipo": st.column_config.TextColumn("Equipo", width="medium"),
    "tipo": "Tipo", "sitio": "Sitio", "ip": "IP",
    "estado_actual": "Estado",
    "mediciones": st.column_config.NumberColumn("Mediciones", format="%d"),
    "disponibilidad_pct": st.column_config.ProgressColumn("Disponibilidad", format="%.2f%%", min_value=0, max_value=100),
    "latencia_prom_ms": st.column_config.NumberColumn("Lat. prom", format="%.1f ms"),
    "latencia_p95_ms": st.column_config.NumberColumn("Lat. p95", format="%.1f ms"),
    "latencia_max_ms": st.column_config.NumberColumn("Lat. máx", format="%.1f ms"),
    "jitter_prom_ms": st.column_config.NumberColumn("Jitter", format="%.1f ms"),
    "perdida_prom_pct": st.column_config.NumberColumn("Pérdida", format="%.1f%%"),
    "saltos": st.column_config.NumberColumn("Saltos", format="%d"),
    "incidentes": st.column_config.NumberColumn("Incid.", format="%d"),
    "downtime_min": st.column_config.NumberColumn("Tiempo con falla", format="%.0f min"),
    "mttr_min": st.column_config.NumberColumn("MTTR", format="%.0f min"),
    "device_id": None,
}


def device_table(df: pd.DataFrame, height: int = 420) -> None:
    view = df.copy()
    if "estado_actual" in view:
        view["estado_actual"] = view["estado_actual"].map(status_text)
    st.dataframe(view, column_config=DEVICE_COLUMNS, hide_index=True, width="stretch", height=height)


def level_order(insights: Sequence[Insight]) -> dict[InsightLevel, int]:
    return {lvl: sum(1 for i in insights if i.level == lvl) for lvl in InsightLevel}
