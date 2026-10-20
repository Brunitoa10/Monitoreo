"""Etiquetas y formatos compartidos por los reportes."""
from __future__ import annotations

from typing import Optional

from nemesis.domain.enums import InsightLevel, Status
from nemesis.domain.models import format_duration

LEVEL_LABEL = {
    InsightLevel.CRITICAL: "Crítico",
    InsightLevel.WARNING: "Atención",
    InsightLevel.INFO: "Info",
    InsightLevel.POSITIVE: "Positivo",
}
LEVEL_COLOR = {
    InsightLevel.CRITICAL: "#dc2626",
    InsightLevel.WARNING: "#d97706",
    InsightLevel.INFO: "#2563eb",
    InsightLevel.POSITIVE: "#16a34a",
}


def status_label(value: str) -> str:
    try:
        return Status(value).label
    except ValueError:
        return str(value)


def pct(value: Optional[float], digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}%"


def ms(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.1f} ms"


def num(value: Optional[float], digits: int = 1, suffix: str = "") -> str:
    return "—" if value is None else f"{value:,.{digits}f}{suffix}"


def minutes(value: Optional[float]) -> str:
    if value is None:
        return "—"
    if value >= 120:
        return f"{value / 60:.1f} h"
    return f"{value:.0f} min"


def kpi_rows(k) -> list[tuple[str, str]]:
    return [
        ("Disponibilidad global", pct(k.availability_pct, 3)),
        ("Health score", num(k.health_score, 1, " / 100")),
        ("Equipos monitoreados", str(k.devices_monitored)),
        ("Operativos / Degradados / Caídos (ahora)", f"{k.up_now} / {k.degraded_now} / {k.down_now}"),
        ("Equipos con fallas en el período", str(k.devices_with_failures)),
        ("Latencia promedio", ms(k.latency_avg_ms)),
        ("Latencia p95", ms(k.latency_p95_ms)),
        ("Jitter promedio", ms(k.jitter_avg_ms)),
        ("Pérdida de paquetes promedio", pct(k.loss_avg_pct)),
        ("Saltos promedio (estimado)", num(k.hops_avg)),
        ("Incidentes (abiertos)", f"{k.incidents_total} ({k.incidents_open})"),
        ("MTTR (tiempo medio de recuperación)", minutes(k.mttr_min)),
        ("MTBF (tiempo medio entre fallas por equipo)", num(k.mtbf_h, 1, " h")),
        ("Tiempo total con falla", format_duration((k.downtime_min or 0) * 60)),
        ("Mediciones analizadas", f"{k.checks_total:,}"),
    ]
