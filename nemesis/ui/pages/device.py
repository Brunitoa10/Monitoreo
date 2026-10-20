"""Detalle por equipo: latencia, pérdida, saltos/traceroute e incidentes."""
from __future__ import annotations

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from nemesis.container import Container
from nemesis.services.metrics import ReportFilter
from nemesis.ui import components as ui
from nemesis.ui.theme import CATEGORICAL


def render(c: Container, f: ReportFilter) -> None:
    ui.header("Análisis por equipo", f"Latencia, pérdida, saltos e incidentes · {f.label}")
    devices, _ = c.devices.get_all()
    devices = [d for d in devices if (not f.sites or d.site in f.sites) and (not f.types or d.type in f.types)]
    if not devices:
        ui.empty("No hay equipos para los filtros elegidos.")
        return
    labels = {f"{d.name} · {d.site} · {d.type} ({d.ip_display})": d for d in sorted(devices, key=lambda d: (d.type, d.site, d.name))}
    device = labels[st.selectbox("Equipo", list(labels))]

    metrics = c.metrics.device_metrics(f)
    row = metrics[metrics["device_id"] == device.id]
    cols = st.columns(6)
    if not row.empty:
        r = row.iloc[0]
        values = [
            ("Estado", ui.status_text(r["estado_actual"]), ""),
            ("Disponibilidad", ui.fmt(r["disponibilidad_pct"], "%", 2), f"{int(r['mediciones'] or 0)} mediciones"),
            ("Latencia p95", ui.fmt(r["latencia_p95_ms"], " ms"), f"prom {ui.fmt(r['latencia_prom_ms'], ' ms')}"),
            ("Jitter", ui.fmt(r["jitter_prom_ms"], " ms"), ""),
            ("Pérdida", ui.fmt(r["perdida_prom_pct"], "%"), ""),
            ("Incidentes", str(int(r["incidentes"])), f"downtime {ui.fmt(r['downtime_min'], ' min', 0)}"),
        ]
        for col, (label, value, detail) in zip(cols, values):
            with col:
                ui.kpi(label, value, detail)
    else:
        st.info("Este equipo todavía no tiene mediciones en el período.")

    probes = c.store.probes_for_device(device.id, f.start, f.end)
    if not probes.empty:
        st.write("")
        fig = go.Figure()
        for i, ((role, method), g) in enumerate(probes.groupby(["role", "method"])):
            name = f"{role} ({method})"
            color = CATEGORICAL[i % len(CATEGORICAL)]
            fig.add_trace(go.Scatter(x=g["ts"], y=g["rtt_avg_ms"], mode="lines", name=name, line=dict(width=2, color=color)))
            down = g[g["online"] == 0]
            if not down.empty:
                fig.add_trace(go.Scatter(x=down["ts"], y=[0] * len(down), mode="markers", name=f"{name} sin respuesta",
                                         marker=dict(symbol="x", size=9, color="#dc2626")))
        fig.update_layout(title="Latencia por extremo (las X marcan caídas)", height=340, hovermode="x unified",
                          yaxis_title="ms")
        st.plotly_chart(fig, width="stretch")

        left, right = st.columns(2)
        with left:
            loss = probes[probes["method"] == "icmp"].groupby(pd.Grouper(key="ts", freq="1h"))["loss_pct"].mean().reset_index()
            fig = go.Figure(go.Bar(x=loss["ts"], y=loss["loss_pct"], marker_color=CATEGORICAL[1], marker_line_width=0))
            fig.update_layout(title="Pérdida de paquetes por hora", height=280, yaxis_title="%")
            st.plotly_chart(fig, width="stretch")
        with right:
            hops = probes.dropna(subset=["hops"])
            if not hops.empty:
                fig = go.Figure(go.Scatter(x=hops["ts"], y=hops["hops"], mode="lines", line_shape="hv",
                                           line=dict(width=2, color=CATEGORICAL[6])))
                fig.update_layout(title="Saltos estimados (TTL)", height=280, yaxis_title="saltos")
                st.plotly_chart(fig, width="stretch")

    st.subheader("Saltos de red (traceroute)")
    if st.button("🛰️ Ejecutar traceroute ahora"):
        with st.spinner("Trazando ruta..."):
            results = c.traceroute.trace_device(device)
        for res in results:
            st.success(f"{res.device_name} → {res.ip}: {res.hop_count} saltos · "
                       f"{'destino alcanzado' if res.reached else 'NO alcanzó el destino'}")
            st.dataframe(pd.DataFrame([{"Salto": h.number, "IP": h.ip or "*", "RTT (ms)": h.rtt_ms} for h in res.hops]),
                         hide_index=True, width="stretch")
    traces = c.metrics.traceroutes(f, device.id)
    if traces.empty:
        st.caption("Sin traceroutes en el período (se ejecutan automáticamente cada "
                   f"{c.settings.probe.traceroute_interval_minutes} min).")
    else:
        last = traces.iloc[-1]
        path = json.loads(last["path_json"])
        st.caption(f"Última ruta ({last['ts']:%d/%m %H:%M}): " +
                   " → ".join(h["ip"] or "*" for h in path))
        hist = traces[["ts", "ip", "hop_count", "reached", "avg_rtt_ms"]].rename(columns={
            "ts": "Fecha", "ip": "IP", "hop_count": "Saltos", "reached": "Alcanzado", "avg_rtt_ms": "RTT prom (ms)"})
        hist["Alcanzado"] = hist["Alcanzado"].astype(bool)
        st.dataframe(hist.sort_values("Fecha", ascending=False), hide_index=True, width="stretch", height=220)

    st.subheader("Incidentes del equipo")
    inc = c.metrics.incidents(f)
    inc = inc[inc["device_id"] == device.id] if not inc.empty else inc
    if inc.empty:
        st.caption("Sin incidentes en el período. 👌")
    else:
        view = inc[["status", "started_at", "ended_at", "duration_min", "message"]].copy()
        view["status"] = view["status"].map(ui.status_text)
        st.dataframe(view.rename(columns={"status": "Severidad", "started_at": "Inicio", "ended_at": "Fin",
                                          "duration_min": "Duración (min)", "message": "Detalle"}),
                     hide_index=True, width="stretch")
