"""Entidades y value objects del dominio."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from statistics import mean
from typing import Any, Optional

from nemesis.domain.enums import InsightLevel, IssueSeverity, Status

RESERVED_WORDS = frozenset({"disponible", "diponible", "libre", "spare", "reserva"})
PRIMARY_ROLE = "Principal"


def normalize(text: str) -> str:
    """Minúsculas sin acentos ni espacios extra (para comparar nombres)."""
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip().lower()


@dataclass(frozen=True)
class Target:
    """Un extremo a chequear de un dispositivo (un enlace tiene Padre e Hijo)."""

    role: str
    ip: str


@dataclass(frozen=True)
class Device:
    name: str
    site: str
    type: str
    targets: tuple[Target, ...]
    source_file: str = ""
    raw: dict[str, Any] = field(default_factory=dict, compare=False, hash=False, repr=False)

    @property
    def id(self) -> str:
        """Identificador estable. Si el JSON trae "Id" se respeta; si no, se deriva."""
        explicit = self.raw.get("Id") if self.raw else None
        if explicit:
            return str(explicit)
        return "|".join(normalize(p) for p in (self.type, self.site, self.name, self.primary_ip))

    @property
    def primary_ip(self) -> str:
        return self.targets[0].ip if self.targets else ""

    @property
    def ip_display(self) -> str:
        if len(self.targets) == 1:
            return self.targets[0].ip
        return " / ".join(f"{t.role}: {t.ip}" for t in self.targets)

    @property
    def is_reserved(self) -> bool:
        """Equipos marcados como Disponible/Libre: no cuentan como caídos."""
        return normalize(self.name) in RESERVED_WORDS or normalize(self.site) in RESERVED_WORDS


@dataclass(frozen=True)
class ProbeResult:
    """Resultado de un chequeo contra un Target (ICMP o TCP)."""

    role: str
    ip: str
    method: str
    online: bool
    sent: int = 0
    received: int = 0
    rtt_avg_ms: Optional[float] = None
    rtt_min_ms: Optional[float] = None
    rtt_max_ms: Optional[float] = None
    jitter_ms: Optional[float] = None
    ttl: Optional[int] = None
    hops: Optional[int] = None
    error: Optional[str] = None

    @property
    def loss_pct(self) -> float:
        if self.sent <= 0:
            return 0.0 if self.online else 100.0
        return round(100.0 * (self.sent - self.received) / self.sent, 1)


@dataclass(frozen=True)
class HealthResult:
    device: Device
    status: Status
    probes: tuple[ProbeResult, ...]
    timestamp: datetime
    message: str = ""

    @property
    def online(self) -> bool:
        return any(p.online for p in self.probes)

    @property
    def latency_ms(self) -> Optional[float]:
        """Peor latencia promedio entre los extremos que respondieron."""
        values = [p.rtt_avg_ms for p in self.probes if p.online and p.rtt_avg_ms is not None]
        return round(max(values), 2) if values else None

    @property
    def jitter_ms(self) -> Optional[float]:
        values = [p.jitter_ms for p in self.probes if p.jitter_ms is not None]
        return round(max(values), 2) if values else None

    @property
    def loss_pct(self) -> float:
        """Pérdida sobre los extremos que responden (si nada responde, 100%)."""
        icmp = [p for p in self.probes if p.method == "icmp"]
        alive = [p for p in icmp if p.online]
        if icmp and not alive:
            return 100.0
        return max((p.loss_pct for p in alive), default=0.0)

    @property
    def hops(self) -> Optional[int]:
        values = [p.hops for p in self.probes if p.hops is not None]
        return max(values) if values else None


@dataclass(frozen=True)
class TracerouteHop:
    number: int
    ip: Optional[str]
    rtt_ms: Optional[float]

    @property
    def timed_out(self) -> bool:
        return self.ip is None


@dataclass(frozen=True)
class TracerouteResult:
    device_id: str
    device_name: str
    ip: str
    timestamp: datetime
    hops: tuple[TracerouteHop, ...]
    reached: bool

    @property
    def hop_count(self) -> int:
        return len(self.hops)

    @property
    def avg_rtt_ms(self) -> Optional[float]:
        values = [h.rtt_ms for h in self.hops if h.rtt_ms is not None]
        return round(mean(values), 2) if values else None


@dataclass
class Incident:
    device_id: str
    device_name: str
    site: str
    type: str
    status: Status
    started_at: datetime
    ended_at: Optional[datetime] = None
    message: str = ""
    id: Optional[int] = None
    last_ok_at: Optional[datetime] = None   # último chequeo OK antes de la caída (auditoría)

    @property
    def is_open(self) -> bool:
        return self.ended_at is None

    def duration_seconds(self, now: Optional[datetime] = None) -> float:
        end = self.ended_at or now or datetime.now()
        return max(0.0, (end - self.started_at).total_seconds())


@dataclass(frozen=True)
class ValidationIssue:
    severity: IssueSeverity
    file: str
    device: str
    field: str
    message: str


@dataclass(frozen=True)
class Insight:
    """Hallazgo + recomendación generada automáticamente para el reporte ejecutivo."""

    level: InsightLevel
    title: str
    detail: str
    recommendation: str


def format_duration(seconds: Optional[float]) -> str:
    """Duración legible para auditoría: '2 d 03 h 04 min 05 s', '12 min 30 s', '45 s'."""
    if seconds is None or seconds != seconds:
        return "—"
    total = int(round(max(0.0, seconds)))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days} d {hours:02d} h {minutes:02d} min {secs:02d} s"
    if hours:
        return f"{hours} h {minutes:02d} min {secs:02d} s"
    if minutes:
        return f"{minutes} min {secs:02d} s"
    return f"{secs} s"
