"""Incidentes: abiertos, línea de tiempo, MTTR y frecuencia."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from nemesis.container import Container
from nemesis.domain.enums import Status
from nemesis.domain.models import format_duration
from nemesis.services.metrics import ReportFilter
from nemesis.ui import components as ui
from nemesis.ui.theme import CATEGORICAL, STATUS_COLORS


def render(c: Container, f: ReportFilter) -> None:
    ui.header("Incidentes", f"Detección con confirmación de {c.settings.collector.confirm_cycles} ciclos · {f.label}")
    inc = c.metrics.incidents(f)
    if inc.empty:
        ui.empty("Sin incidentes en el período. 👌")
        return

    closed = inc[~inc["is_open"]]
    cols = st.columns(4)
    with cols[0]:
        ui.kpi("Incidentes", str(len(inc)), f"{inc['device_id'].nunique()} equipos afectados")
    with cols[1]:
        ui.kpi("Abiertos", str(int(inc["is_open"].sum())), "", "bad" if inc["is_open"].any() else "ok")
    with cols[2]:
        ui.kpi("MTTR", ui.fmt(closed["duration_min"].mean() if not closed.empty else None, " min", 0), "tiempo medio de recuperación")
    with cols[3]:
        ui.kpi("Tiempo total con falla", format_duration(inc["duration_s"].sum()), "suma de todas las fallas")

    open_now = inc[inc["is_open"]]
    if not open_now.empty:
        st.subheader("🔴 Abiertos ahora")
        view = open_now[["device_name", "type", "site", "status", "started_at", "duration_s", "message"]].copy()
        view["status"] = view["status"].map(ui.status_text)
        view["started_at"] = view["started_at"].dt.strftime("%d/%m/%Y %H:%M:%S")
        view["duration_s"] = view["duration_s"].map(format_duration)
        st.dataframe(view.rename(columns={"device_name": "Equipo", "type": "Tipo", "site": "Sitio", "status": "Severidad",
                                          "started_at": "Caído desde", "duration_s": "Tiempo caído", "message": "Detalle"}),
                     hide_index=True, width="stretch")

    st.write("")
    left, right = st.columns(2)
    with left:
        daily = inc.groupby([pd.Grouper(key="started_at", freq="1D"), "type"]).size().reset_index(name="n")
        cmap = ui.color_map(daily["type"])
        fig = go.Figure()
        for t, g in daily.groupby("type"):
            fig.add_trace(go.Bar(x=g["started_at"], y=g["n"], name=t, marker_color=cmap[t], marker_line_width=0))
        fig.update_layout(title="Incidentes por día", barmode="group", height=320, yaxis_title="incidentes")
        st.plotly_chart(fig, width="stretch")
    with right:
        mttr = closed.groupby("type")["duration_min"].mean().sort_values().reset_index() if not closed.empty else pd.DataFrame()
        if not mttr.empty:
            fig = go.Figure(go.Bar(x=mttr["duration_min"], y=mttr["type"], orientation="h", marker_color=CATEGORICAL[0],
                                   marker_line_width=0, text=[f"{v:.0f} min" for v in mttr["duration_min"]],
                                   textposition="outside"))
            fig.update_layout(title="MTTR por tipo", height=320, xaxis_title="minutos")
            st.plotly_chart(fig, width="stretch")

    st.subheader("Línea de tiempo")
    top_devices = inc.groupby("device_name")["duration_min"].sum().nlargest(25).index
    tl = inc[inc["device_name"].isin(top_devices)].copy()
    tl["fin"] = tl["ended_at"].fillna(pd.Timestamp(datetime.now()))
    tl["Severidad"] = tl["status"].map(lambda v: Status(v).label)
    fig = px.timeline(tl, x_start="started_at", x_end="fin", y="device_name", color="Severidad",
                      color_discrete_map={Status(k).label: v for k, v in STATUS_COLORS.items()},
                      hover_data={"site": True, "duration_min": True, "message": True})
    fig.update_layout(height=max(300, 26 * tl["device_name"].nunique() + 120), yaxis_title=None,
                      title="25 equipos con más downtime")
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, width="stretch")

    st.subheader("Historial")
    st.caption("Detalle completo con hora de caída/recuperación y exportación: página Auditoría.")
    view = inc[["device_name", "type", "site", "status", "started_at", "ended_at", "duration_s", "message"]].copy()
    view["status"] = view["status"].map(ui.status_text)
    view["started_at"] = view["started_at"].dt.strftime("%d/%m/%Y %H:%M:%S")
    view["ended_at"] = view["ended_at"].dt.strftime("%d/%m/%Y %H:%M:%S").fillna("en curso")
    view["duration_s"] = view["duration_s"].map(format_duration)
    st.dataframe(view.rename(columns={"device_name": "Equipo", "type": "Tipo", "site": "Sitio", "status": "Severidad",
                                      "started_at": "Caída", "ended_at": "Recuperación", "duration_s": "Duración",
                                      "message": "Detalle"}), hide_index=True, width="stretch", height=400)
