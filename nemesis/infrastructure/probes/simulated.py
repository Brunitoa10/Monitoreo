"""Probes simulados: permiten probar el dashboard y los reportes sin red (mode = "simulated")."""
from __future__ import annotations

import hashlib
import random
import time

from nemesis.domain.models import ProbeResult, Target, TracerouteHop
from nemesis.infrastructure.probes.base import Probe, Tracer
from nemesis.infrastructure.probes.parsers import estimate_hops


def _profile(ip: str) -> tuple[float, float, int]:
    """Perfil determinístico por IP: (latencia base, prob. de caída, saltos)."""
    h = int(hashlib.md5(ip.encode()).hexdigest(), 16)
    base = 1 + (h % 40)
    down_prob = (0.002, 0.01, 0.03, 0.15)[h % 4] if h % 7 else 0.6
    hops = 1 + (h % 5)
    return float(base), down_prob, hops


class SimulatedPingProbe(Probe):
    method = "icmp"

    def __init__(self, count: int = 3, seed: int | None = None):
        self._count = count
        self._rng = random.Random(seed)

    def probe(self, target: Target) -> ProbeResult:
        base, down_prob, hops = _profile(target.ip)
        # La probabilidad de caída varía con la hora para que haya incidentes "reales".
        if self._rng.random() < down_prob:
            return ProbeResult(target.role, target.ip, self.method, False, self._count, 0, error="Sin respuesta")
        received = self._count - (1 if self._rng.random() < 0.05 else 0)
        rtts = [max(0.5, self._rng.gauss(base, base * 0.25)) for _ in range(received)]
        if self._rng.random() < 0.03:
            rtts = [r * 6 for r in rtts]  # pico de latencia
        ttl = 255 - hops if base > 20 else 64 - hops
        avg = sum(rtts) / len(rtts)
        jitter = (sum((r - avg) ** 2 for r in rtts) / len(rtts)) ** 0.5
        return ProbeResult(
            target.role, target.ip, self.method, True, self._count, received,
            round(avg, 2), round(min(rtts), 2), round(max(rtts), 2), round(jitter, 2), ttl, estimate_hops(ttl),
        )


class SimulatedTracer(Tracer):
    def trace(self, ip: str) -> tuple[list[TracerouteHop], bool]:
        base, down_prob, hops = _profile(ip)
        time.sleep(0.01)
        path = [TracerouteHop(i + 1, f"10.0.{i}.1", round(base * (i + 1) / (hops + 1), 2)) for i in range(hops)]
        path.append(TracerouteHop(hops + 1, ip, base))
        return path, down_prob < 0.5
