"""Punto de entrada de la UI. Ejecutar con:  streamlit run dashboard.py"""
from __future__ import annotations

import streamlit as st

from nemesis.ui import theme
from nemesis.ui.context import app, sidebar_filter
from nemesis.ui.pages import admin, audit, device, executive, incidents, live, reports

PAGES = [
    ("Resumen ejecutivo", "📊", "resumen", executive.render),
    ("Monitoreo en vivo", "📡", "vivo", live.render),
    ("Análisis por equipo", "🔬", "equipo", device.render),
    ("Incidentes", "🚨", "incidentes", incidents.render),
    ("Auditoría", "🧾", "auditoria", audit.render),
    ("Reportes", "📄", "reportes", reports.render),
    ("Administración", "🔐", "admin", admin.render),
]


def main() -> None:
    st.set_page_config(page_title="Nemesis Monitor", page_icon="🛰️", layout="wide")
    st.markdown(theme.CSS, unsafe_allow_html=True)
    container = app()

    with st.sidebar:
        st.markdown(f"## 🛰️ {container.settings.app.name}")
        st.caption(container.settings.app.organization)

    def make(render):
        def page():
            render(container, sidebar_filter(container))
        page.__name__ = render.__module__.split(".")[-1]
        return page

    nav = st.navigation([st.Page(make(r), title=t, icon=i, url_path=u, default=(u == "resumen")) for t, i, u, r in PAGES])
    nav.run()
