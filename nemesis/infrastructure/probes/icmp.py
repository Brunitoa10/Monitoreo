from __future__ import annotations

from nemesis.domain.models import ProbeResult, Target
from nemesis.infrastructure.probes.base import IS_WINDOWS, CommandRunner, Probe, run_command
from nemesis.infrastructure.probes.parsers import estimate_hops, parse_ping


class SystemPingProbe(Probe):
    """Ping usando el comando del sistema.

    Ventaja sobre sockets raw: no requiere ejecutar como administrador en Windows.
    Envía N paquetes para medir latencia (min/prom/max), jitter, pérdida y TTL.
    """

    method = "icmp"

    def __init__(self, count: int = 3, timeout_ms: int = 800, runner: CommandRunner = run_command):
        self._count = max(1, count)
        self._timeout_ms = max(100, timeout_ms)
        self._runner = runner

    def _command(self, ip: str) -> list[str]:
        if IS_WINDOWS:
            return ["ping", "-n", str(self._count), "-w", str(self._timeout_ms), ip]
        timeout_s = max(1, round(self._timeout_ms / 1000))
        return ["ping", "-n", "-c", str(self._count), "-i", "0.2", "-W", str(timeout_s), ip]

    def probe(self, target: Target) -> ProbeResult:
        budget = self._count * (self._timeout_ms / 1000 + 1.2) + 2
        output = self._runner(self._command(target.ip), budget)
        stats = parse_ping(output)
        online = stats.received > 0
        return ProbeResult(
            role=target.role,
            ip=target.ip,
            method=self.method,
            online=online,
            sent=self._count,
            received=stats.received,
            rtt_avg_ms=stats.avg,
            rtt_min_ms=stats.minimum,
            rtt_max_ms=stats.maximum,
            jitter_ms=stats.jitter,
            ttl=stats.ttl,
            hops=estimate_hops(stats.ttl),
            error=None if online else ("Sin respuesta" if output else "No se pudo ejecutar ping"),
        )
