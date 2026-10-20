"""Estado compartido de la app Streamlit: contenedor único y colector embebido."""
from __future__ import annotations

from datetime import datetime, timedelta

import streamlit as st

from nemesis.container import Container, get_container
from nemesis.services.metrics import ReportFilter

PERIODS = {
    "Última hora": 1,
    "Últimas 6 h": 6,
    "Últimas 24 h": 24,
    "Últimos 7 días": 24 * 7,
    "Últimos 30 días": 24 * 30,
    "Personalizado": None,
}


@st.cache_resource(show_spinner=False)
def app() -> Container:
    container = get_container()
    if container.settings.collector.embedded:
        container.scheduler.start()
    return container


def reload_app() -> None:
    """Aplica cambios de configuración (organización, backend...) sin reiniciar el proceso."""
    try:
        app().scheduler.stop()
    except Exception:
        pass
    st.cache_resource.clear()
    get_container.cache_clear()
    st.rerun()


def sidebar_filter(c: Container) -> ReportFilter:
    """Filtros globales (período, sitios, tipos) en la barra lateral, compartidos por todas las páginas."""
    with st.sidebar:
        st.markdown("### Filtros")
        label = st.selectbox("Período", list(PERIODS), index=2, key="period")
        hours = PERIODS[label]
        if hours is None:
            today = datetime.now().date()
            rng = st.date_input("Rango", (today - timedelta(days=7), today), max_value=today, key="custom_range")
            start_d, end_d = (rng if isinstance(rng, tuple) and len(rng) == 2 else (today, today))
            start = datetime.combine(start_d, datetime.min.time())
            end = datetime.combine(end_d, datetime.max.time()).replace(microsecond=0)
        else:
            end = datetime.now().replace(second=0, microsecond=0)
            start = end - timedelta(hours=hours)

        current = c.metrics.current_status()
        sites = sorted(current["site"].dropna().unique()) if not current.empty else []
        types = sorted(current["type"].dropna().unique()) if not current.empty else []
        sel_sites = st.multiselect("Sitios", sites, key="f_sites", placeholder="Todos")
        sel_types = st.multiselect("Tipos", types, key="f_types", placeholder="Todos")
        _collector_status(c)
    return ReportFilter(start, end, tuple(sel_sites), tuple(sel_types))


def _collector_status(c: Container) -> None:
    last = c.store.last_cycle()
    st.divider()
    interval = c.settings.collector.interval_seconds
    if not last:
        st.caption("⚪ Sin mediciones todavía")
    else:
        age = (datetime.now() - last["ts"]).total_seconds()
        icon = "🟢" if age < interval * 3 else "🟠" if age < interval * 10 else "🔴"
        st.caption(f"{icon} Última medición hace {_ago(age)} · ciclo {last['duration_s']:.1f}s · {last['devices']} equipos")
    mode = "simulado" if c.simulated else "real"
    role = "activo" if c.scheduler.is_leader else ("en espera" if c.scheduler.running else "detenido")
    st.caption(f"Colector: {role} · modo {mode} · cada {interval}s")


def _ago(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"
