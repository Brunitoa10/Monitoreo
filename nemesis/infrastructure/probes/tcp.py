from __future__ import annotations

import socket
import time

from nemesis.domain.models import ProbeResult, Target
from nemesis.infrastructure.probes.base import Probe


class TcpProbe(Probe):
    """Verifica que un servicio (puerto TCP) acepte conexiones y mide el handshake."""

    def __init__(self, port: int, timeout_ms: int = 1000):
        self._port = port
        self._timeout = timeout_ms / 1000
        self.method = f"tcp:{port}"

    def probe(self, target: Target) -> ProbeResult:
        start = time.perf_counter()
        try:
            with socket.create_connection((target.ip, self._port), timeout=self._timeout):
                rtt = round((time.perf_counter() - start) * 1000, 2)
            return ProbeResult(
                role=target.role, ip=target.ip, method=self.method, online=True,
                sent=1, received=1, rtt_avg_ms=rtt, rtt_min_ms=rtt, rtt_max_ms=rtt, jitter_ms=0.0,
            )
        except OSError as exc:
            return ProbeResult(
                role=target.role, ip=target.ip, method=self.method, online=False,
                sent=1, received=0, error=f"Puerto {self._port} cerrado: {exc.__class__.__name__}",
            )
