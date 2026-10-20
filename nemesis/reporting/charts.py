"""Gráficos estáticos (matplotlib) para el PDF."""
from __future__ import annotations

import io
import os

from nemesis.config import PROJECT_ROOT

# Portable: la caché de fuentes de matplotlib queda dentro de la carpeta de la app, no en el perfil del usuario.
os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_ROOT / "data" / "matplotlib"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

INK = "#0f172a"
MUTED = "#64748b"
GRID = "#e2e8f0"
SERIES = ["#2563eb", "#0891b2", "#7c3aed", "#db2777", "#ea580c", "#65a30d"]
GOOD, WARN, BAD = "#16a34a", "#d97706", "#dc2626"


def _style(ax, title: str) -> None:
    ax.set_title(title, loc="left", fontsize=11, color=INK, fontweight="bold", pad=10)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def availability_bars(df: pd.DataFrame, column: str, title: str) -> bytes | None:
    if df.empty:
        return None
    df = df.sort_values("disponibilidad_pct")
    fig, ax = plt.subplots(figsize=(7.2, max(2.2, 0.32 * len(df) + 0.8)))
    ax.barh(df[column].astype(str), df["disponibilidad_pct"], color=SERIES[0], height=0.6)
    low = max(0, min(df["disponibilidad_pct"].min() - 2, 95))
    ax.set_xlim(low, 100.5)
    for i, v in enumerate(df["disponibilidad_pct"]):
        ax.text(v, i, f" {v:.2f}%", va="center", fontsize=8, color=INK)
    _style(ax, title)
    ax.grid(axis="x", color=GRID)
    ax.grid(axis="y", visible=False)
    return _png(fig)


def time_series(df: pd.DataFrame, value: str, by: str | None, title: str, ylabel: str,
                target: float | None = None) -> bytes | None:
    if df.empty:
        return None
    fig, ax = plt.subplots(figsize=(7.2, 2.8))
    groups = df.groupby(by) if by and by in df.columns else [("Total", df)]
    for i, (name, g) in enumerate(groups):
        ax.plot(g["ts"], g[value], label=str(name), color=SERIES[i % len(SERIES)], linewidth=1.6)
    if target is not None:
        ax.axhline(target, color=INK, linestyle="--", linewidth=1)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
    fig.autofmt_xdate(rotation=0, ha="center")
    if by:
        ax.legend(fontsize=7, frameon=False, ncol=min(6, df[by].nunique()), loc="upper left",
                  bbox_to_anchor=(0, -0.12))
    _style(ax, title)
    return _png(fig)


def status_donut(up: int, degraded: int, down: int, reserved: int) -> bytes | None:
    values = [up, degraded, down, reserved]
    if sum(values) == 0:
        return None
    labels = ["Operativo", "Degradado", "Caído", "Disponible"]
    colors = [GOOD, WARN, BAD, "#94a3b8"]
    pairs = [(v, l, c) for v, l, c in zip(values, labels, colors) if v]
    fig, ax = plt.subplots(figsize=(3.2, 2.6))
    ax.pie([p[0] for p in pairs], colors=[p[2] for p in pairs], startangle=90, counterclock=False,
           wedgeprops={"width": 0.38, "edgecolor": "white", "linewidth": 2})
    ax.text(0, 0, f"{sum(values)}\nequipos", ha="center", va="center", fontsize=10, color=INK, fontweight="bold")
    ax.legend([f"{p[1]} ({p[0]})" for p in pairs], fontsize=7, frameon=False, loc="center left",
              bbox_to_anchor=(1, 0.5))
    ax.set_title("Estado actual", loc="left", fontsize=11, color=INK, fontweight="bold")
    return _png(fig)
