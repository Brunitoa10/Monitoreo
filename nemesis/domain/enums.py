from __future__ import annotations

from enum import Enum


class Status(str, Enum):
    """Estado de salud de un dispositivo."""

    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    AVAILABLE = "AVAILABLE"
    UNKNOWN = "UNKNOWN"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def color(self) -> str:
        return _COLORS[self]

    @property
    def severity(self) -> int:
        """Mayor número = más grave (útil para ordenar)."""
        return _SEVERITY[self]

    @property
    def counts_as_up(self) -> bool:
        """Para el cálculo de disponibilidad: degradado sigue respondiendo."""
        return self in (Status.HEALTHY, Status.WARNING)

    @property
    def is_monitored(self) -> bool:
        """Los equipos reservados/disponibles no cuentan en la disponibilidad."""
        return self not in (Status.AVAILABLE, Status.UNKNOWN)


_LABELS = {
    Status.HEALTHY: "Operativo",
    Status.WARNING: "Degradado",
    Status.CRITICAL: "Caído",
    Status.AVAILABLE: "Disponible",
    Status.UNKNOWN: "Sin datos",
}

_COLORS = {
    Status.HEALTHY: "#16a34a",
    Status.WARNING: "#d97706",
    Status.CRITICAL: "#dc2626",
    Status.AVAILABLE: "#64748b",
    Status.UNKNOWN: "#94a3b8",
}

_SEVERITY = {
    Status.HEALTHY: 0,
    Status.AVAILABLE: 1,
    Status.UNKNOWN: 2,
    Status.WARNING: 3,
    Status.CRITICAL: 4,
}


class IssueSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class InsightLevel(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"
    POSITIVE = "POSITIVE"
