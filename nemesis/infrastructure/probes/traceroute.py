from __future__ import annotations

import socket

from nemesis.domain.models import TracerouteHop
from nemesis.infrastructure.probes.base import IS_WINDOWS, CommandRunner, Tracer, run_command
from nemesis.infrastructure.probes.parsers import parse_traceroute


class SystemTracer(Tracer):
    """tracert (Windows) / traceroute (Linux) sin resolución DNS (-d / -n) para ir rápido."""

    def __init__(self, max_hops: int = 20, timeout_ms: int = 500, runner: CommandRunner = run_command):
        self._max_hops = max_hops
        self._timeout_ms = timeout_ms
        self._runner = runner

    def _command(self, ip: str) -> list[str]:
        if IS_WINDOWS:
            return ["tracert", "-d", "-h", str(self._max_hops), "-w", str(self._timeout_ms), ip]
        return ["traceroute", "-n", "-q", "1", "-m", str(self._max_hops), "-w", "1", ip]

    def trace(self, ip: str) -> tuple[list[TracerouteHop], bool]:
        budget = self._max_hops * 3 * (self._timeout_ms / 1000) + 10
        output = self._runner(self._command(ip), budget)
        try:
            target = socket.gethostbyname(ip)  # hostnames: comparar contra la IP resuelta
        except OSError:
            target = ip
        return parse_traceroute(output, target)
