"""Vista ejecutiva: KPIs, tendencias, hallazgos y recomendaciones."""
from __future__ import annotations

import streamlit as st

from nemesis.container import Container
from nemesis.services.metrics import ReportFilter
from nemesis.ui import components as ui


def render(c: Container, f: ReportFilter) -> None:
    ctx = c.reports.insight_context(f)
    k = ctx.kpis
    insights = c.insights.generate(ctx)

    pills = []
    if k.down_now:
        pills.append((f"{k.down_now} caídos", "bad"))
    ui.header("Resumen ejecutivo", f"{c.settings.app.organization} · {f.label}", pills)

    if k.checks_total == 0:
        ui.empty("Todavía no hay mediciones en el período. El colector las va generando automáticamente "
                 "(o usá 'Monitoreo en vivo → Chequear ahora').")
        return

    cols = st.columns(6)
    with cols[0]:
        ui.kpi("Disponibilidad", ui.fmt(k.availability_pct, "%", 2), "promedio del período",
               "ok" if (k.availability_pct or 0) >= 99.9 else "warn")
    with cols[1]:
        score = k.health_score
        ui.kpi("Health score", ui.fmt(score, "", 0), "0-100 · disponibilidad + calidad",
               "ok" if (score or 0) >= 95 else "warn" if (score or 0) >= 85 else "bad")
    with cols[2]:
        ui.kpi("Caídos / degradados", f"{k.down_now} / {k.degraded_now}", f"de {k.devices_monitored} monitoreados",
               "bad" if k.down_now else "warn" if k.degraded_now else "ok")
    with cols[3]:
        ui.kpi("Incidentes", f"{k.incidents_total}", f"{k.incidents_open} abiertos · MTTR {ui.fmt(k.mttr_min, ' min', 0)}",
               "warn" if k.incidents_open else "")
    with cols[4]:
        ui.kpi("Latencia p95", ui.fmt(k.latency_p95_ms, " ms"), f"prom {ui.fmt(k.latency_avg_ms, ' ms')} · jitter {ui.fmt(k.jitter_avg_ms, ' ms')}")
    with cols[5]:
        ui.kpi("Pérdida / saltos", f"{ui.fmt(k.loss_avg_pct, '%')} · {ui.fmt(k.hops_avg, '', 1)}",
               f"{k.devices_with_failures} equipos con fallas", "warn" if k.devices_with_failures else "")

    st.write("")
    left, right = st.columns([1, 2])
    current = c.metrics.current_status(f)
    with left:
        if not current.empty:
            st.plotly_chart(ui.status_donut(current), width="stretch")
    with right:
        if not ctx.by_site.empty:
            st.plotly_chart(ui.availability_bar(ctx.by_site, "site", "Disponibilidad por sitio"),
                            width="stretch")

    left, right = st.columns(2)
    with left:
        series = c.metrics.availability_series(f)
        if not series.empty:
            st.plotly_chart(ui.line_chart(series, "disponibilidad_pct", None, "Evolución de la disponibilidad", "%"),
                            width="stretch")
    with right:
        lat = c.metrics.latency_series(f, by="type")
        if not lat.empty:
            st.plotly_chart(ui.line_chart(lat, "latencia_prom_ms", "type", "Latencia promedio por tipo", "ms",
                                          colors=ui.color_map(lat["type"])), width="stretch")

    st.subheader("Hallazgos y recomendaciones")
    counts = ui.level_order(insights)
    st.caption(" · ".join(f"{n} {lvl.value.lower()}" for lvl, n in counts.items() if n) or "Sin hallazgos")
    for ins in insights:
        ui.insight_card(ins)

    left, right = st.columns(2)
    with left:
        if not ctx.by_type.empty:
            st.plotly_chart(ui.availability_bar(ctx.by_type, "type", "Disponibilidad por tipo"),
                            width="stretch")
    with right:
        heat = c.metrics.failure_heatmap(f)
        if not heat.empty:
            st.plotly_chart(ui.heatmap(heat, "Patrón de caídas (día × hora)"), width="stretch")

    st.subheader("Equipos que más afectan el servicio")
    worst = ctx.devices.sort_values(["downtime_min", "incidentes"], ascending=False).head(15)
    ui.device_table(worst, height=420)
