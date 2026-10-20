"""Parsers de la salida de ping / tracert (Windows en español o inglés, y Linux)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Optional

from nemesis.domain.models import TracerouteHop

# "tiempo=12ms", "tiempo<1m", "time=1ms", "time<1ms", "time=12.3 ms", "Zeit=3ms", "temps=4 ms"
_RTT_RE = re.compile(r"(?:time|tiempo|zeit|temps|tempo|tid)\s*([=<])\s*(\d+(?:[.,]\d+)?)\s*m?s?", re.I)
_TTL_RE = re.compile(r"\bttl\s*=\s*(\d+)", re.I)
_IP_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")
_HOP_LINE_RE = re.compile(r"^\s*(\d{1,2})\s+(.*)$")
_HOP_RTT_RE = re.compile(r"(<?\s*\d+(?:[.,]\d+)?)\s*ms", re.I)

COMMON_INITIAL_TTLS = (32, 64, 128, 255)


@dataclass(frozen=True)
class PingStats:
    rtts: tuple[float, ...]
    ttl: Optional[int]

    @property
    def received(self) -> int:
        return len(self.rtts)

    @property
    def avg(self) -> Optional[float]:
        return round(mean(self.rtts), 2) if self.rtts else None

    @property
    def minimum(self) -> Optional[float]:
        return min(self.rtts) if self.rtts else None

    @property
    def maximum(self) -> Optional[float]:
        return max(self.rtts) if self.rtts else None

    @property
    def jitter(self) -> Optional[float]:
        """Desvío estándar del RTT: mide estabilidad del enlace."""
        return round(pstdev(self.rtts), 2) if len(self.rtts) > 1 else (0.0 if self.rtts else None)


def _to_float(raw: str) -> float:
    return float(raw.replace(",", "."))


def parse_ping(output: str) -> PingStats:
    """Cuenta sólo las líneas de respuesta real (las que traen TTL).

    "Host de destino inaccesible" no trae TTL, así que no cuenta como respuesta:
    esto evita el falso positivo clásico de ping en Windows (exit code 0 sin respuesta).
    """
    rtts: list[float] = []
    ttl: Optional[int] = None
    for line in output.splitlines():
        ttl_match = _TTL_RE.search(line)
        rtt_match = _RTT_RE.search(line)
        if not ttl_match or not rtt_match:
            continue
        op, value = rtt_match.groups()
        rtt = _to_float(value)
        if op == "<":  # "tiempo<1m" => menos de 1 ms
            rtt = rtt / 2
        rtts.append(rtt)
        ttl = int(ttl_match.group(1))
    return PingStats(tuple(rtts), ttl)


def estimate_hops(ttl: Optional[int]) -> Optional[int]:
    """Estima saltos a partir del TTL recibido (TTL inicial típico - TTL recibido).

    Windows arranca en 128, Linux/impresoras en 64, equipos de red en 255.
    Es una estimación barata que se calcula en cada ciclo; el valor exacto
    se obtiene con traceroute.
    """
    if ttl is None or ttl <= 0:
        return None
    initial = next((t for t in COMMON_INITIAL_TTLS if t >= ttl), 255)
    return max(0, initial - ttl)


def parse_traceroute(output: str, target_ip: str) -> tuple[list[TracerouteHop], bool]:
    hops: list[TracerouteHop] = []
    for line in output.splitlines():
        m = _HOP_LINE_RE.match(line)
        if not m:
            continue
        number, rest = int(m.group(1)), m.group(2)
        ips = _IP_RE.findall(rest)
        rtts = []
        for raw in _HOP_RTT_RE.findall(rest):
            raw = raw.replace(" ", "")
            rtts.append(0.5 if raw.startswith("<") else _to_float(raw.lstrip("<")))
        hop_ip = ips[-1] if ips else None
        hops.append(TracerouteHop(number, hop_ip, round(mean(rtts), 2) if rtts else None))
    reached = any(h.ip == target_ip for h in hops)
    # Cortamos los saltos posteriores al destino (Linux a veces repite líneas).
    if reached:
        last = max(h.number for h in hops if h.ip == target_ip)
        hops = [h for h in hops if h.number <= last]
    return hops, reached
