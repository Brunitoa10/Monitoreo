"""Arranca Streamlit con el watchdog activo desde el inicio (lo usa el lanzador)."""
from __future__ import annotations

import sys

from nemesis.launcher import start_idle_watchdog, start_parent_watchdog


def _prewarm() -> None:
    """Importa todo lo pesado ANTES de abrir el puerto: la ventana muestra la pantalla de carga
    hasta que la app está lista, en lugar de una página en blanco (la 1.ª vez Python compila todo)."""
    try:
        import importlib
        for name in ("nemesis.ui.app", "nemesis.container", "nemesis.reporting"):  # streamlit, pandas, plotly...
            importlib.import_module(name)
    except Exception:  # si algo falla, que lo muestre Streamlit con el detalle
        pass


def main() -> int:
    start_parent_watchdog()
    _prewarm()
    start_idle_watchdog()
    from streamlit.web import cli as stcli
    sys.argv = ["streamlit", "run", *sys.argv[1:]]
    return stcli.main()


if __name__ == "__main__":
    sys.exit(main())
