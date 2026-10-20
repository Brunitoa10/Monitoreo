"""Generación y descarga de reportes (PDF, Excel, Power BI)."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from nemesis.container import Container
from nemesis.services.metrics import ReportFilter
from nemesis.ui import components as ui

DESCRIPTIONS = {
    "pdf": "Reporte ejecutivo para gerencia: KPIs, hallazgos con recomendaciones, gráficos y top de problemas.",
    "excel": "Detalle completo con formato condicional y gráficos nativos: por sitio, tipo, equipo, incidentes, saltos y datos por hora.",
    "powerbi": "Modelo estrella (dimensiones + hechos) en CSV, con guía de relaciones y medidas DAX. "
               "También actualiza reports/powerbi/latest para refrescar el tablero con un clic.",
}


def render(c: Container, f: ReportFilter) -> None:
    ui.header("Reportes", f"Período y filtros de la barra lateral · {f.label}")
    st.caption(f"Sitios: {', '.join(f.sites) or 'todos'} · Tipos: {', '.join(f.types) or 'todos'}")

    cols = st.columns(3)
    for col, exporter in zip(cols, c.reports.exporters):
        with col, st.container(border=True):
            st.markdown(f"#### {exporter.label}")
            st.caption(DESCRIPTIONS.get(exporter.key, ""))
            if st.button(f"Generar {exporter.extension.upper()}", key=f"gen_{exporter.key}", width="stretch"):
                with st.spinner("Generando..."):
                    name, content, path = c.reports.generate(exporter.key, f)
                st.session_state[f"report_{exporter.key}"] = (name, content, str(path))
            if f"report_{exporter.key}" in st.session_state:
                name, content, path = st.session_state[f"report_{exporter.key}"]
                st.download_button(f"⬇️ Descargar {name}", content, file_name=name, mime=exporter.mime,
                                   width="stretch", type="primary")
                st.caption(f"Guardado en {path}")

    st.subheader("Reportes anteriores")
    folder = c.settings.paths.reports_dir
    files = sorted(folder.glob("nemesis_reporte_*.*"), key=lambda p: p.stat().st_mtime, reverse=True)[:20] if folder.exists() else []
    if not files:
        st.caption("Todavía no se generó ninguno.")
    for p in files:
        a, b = st.columns([4, 1])
        a.write(f"📄 {p.name} · {datetime.fromtimestamp(p.stat().st_mtime):%d/%m/%Y %H:%M} · {p.stat().st_size / 1024:,.0f} KB")
        b.download_button("Descargar", p.read_bytes(), file_name=p.name, key=f"dl_{p.name}", width="stretch")

    with st.expander("Automatizar reportes (Programador de tareas de Windows)"):
        st.code(f'"{folder.parent}\\nemesis.bat" report --format pdf excel powerbi --days 7', language="bat")
        st.caption("Programalo semanal (lunes 8:00) para tener el reporte listo sin abrir el dashboard.")
