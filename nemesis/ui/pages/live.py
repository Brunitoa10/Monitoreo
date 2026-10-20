"""Monitoreo en vivo: estado actual por tipo, con auto-refresco."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from nemesis.container import Container
from nemesis.domain.enums import Status
from nemesis.services.metrics import ReportFilter
from nemesis.ui import components as ui

LIVE_COLUMNS = {
    "estado": st.column_config.TextColumn("Estado", width="small"),
    "device_name": st.column_config.TextColumn("Equipo", width="medium"),
    "site": "Sitio", "ip": "IP", "type": "Tipo",
    "latency_ms": st.column_config.NumberColumn("Latencia", format="%.1f ms"),
    "jitter_ms": st.column_config.NumberColumn("Jitter", format="%.1f ms"),
    "loss_pct": st.column_config.NumberColumn("Pérdida", format="%.0f%%"),
    "hops": st.column_config.NumberColumn("Saltos", format="%d"),
    "message": st.column_config.TextColumn("Detalle", width="large"),
    "ts": st.column_config.DatetimeColumn("Medido", format="HH:mm:ss"),
}


def render(c: Container, f: ReportFilter) -> None:
    ui.header("Monitoreo en vivo", "Último estado de cada equipo · se actualiza solo")

    top = st.columns([1, 1, 2])
    with top[0]:
        if st.button("⚡ Chequear ahora", type="primary", width="stretch"):
            with st.spinner("Chequeando inventario..."):
                report = c.monitoring.run_cycle()
            st.toast(f"{len(report.results)} equipos en {report.duration_s:.1f}s")
    with top[1]:
        only_problems = st.toggle("Sólo con problemas", value=False)
    with top[2]:
        search = st.text_input("Buscar", placeholder="nombre, IP o sitio", label_visibility="collapsed")

    interval = max(10, c.settings.collector.interval_seconds)

    @st.fragment(run_every=interval)
    def live_table() -> None:
        df = c.metrics.current_status(f)
        if df.empty:
            ui.empty("Sin mediciones todavía.")
            return
        counts = df["status"].value_counts()
        cols = st.columns(5)
        for col, s in zip(cols, (Status.HEALTHY, Status.WARNING, Status.CRITICAL, Status.AVAILABLE, Status.UNKNOWN)):
            with col:
                tone = {Status.HEALTHY: "ok", Status.WARNING: "warn", Status.CRITICAL: "bad"}.get(s, "")
                ui.kpi(s.label, str(int(counts.get(s.value, 0))), "", tone if counts.get(s.value, 0) else "")

        if only_problems:
            df = df[df["status"].isin([Status.WARNING.value, Status.CRITICAL.value])]
        if search:
            mask = pd.Series(False, index=df.index)
            for col in ("device_name", "ip", "site"):
                mask |= df[col].astype(str).str.contains(search, case=False, na=False)
            df = df[mask]

        df = df.assign(
            estado=df["status"].map(ui.status_text),
            _sev=df["status"].map(lambda v: Status(v).severity),
        ).sort_values(["_sev", "site", "device_name"], ascending=[False, True, True])

        st.caption(f"Actualizado {datetime.now():%H:%M:%S} · refresco cada {interval}s")
        types = sorted(df["type"].unique())
        if not types:
            ui.empty("Ningún equipo coincide con el filtro.")
            return
        tabs = st.tabs([f"Todos ({len(df)})"] + [f"{t} ({(df['type'] == t).sum()})" for t in types])
        cols = list(LIVE_COLUMNS)
        for tab, subset in zip(tabs, [df] + [df[df["type"] == t] for t in types]):
            with tab:
                st.dataframe(subset[cols], column_config=LIVE_COLUMNS, hide_index=True, width="stretch",
                             height=min(700, 38 * len(subset) + 40))

    live_table()
