"""Genera histórico simulado para probar dashboard y reportes sin esperar días de mediciones.

Usar SIEMPRE con una base aparte:  python -m nemesis demo-data --days 7 --db data/demo.db
"""
from __future__ import annotations

import logging
import random
from dataclasses import replace
from datetime import datetime, timedelta

from nemesis.core.events import CycleCompleted
from nemesis.domain.models import TracerouteResult
from nemesis.infrastructure.probes import SimulatedPingProbe, SimulatedTracer
from nemesis.monitors import build_registry

log = logging.getLogger(__name__)


def generate_demo_history(container, days: int = 7, step_minutes: int = 5, seed: int = 42) -> int:
    random.seed(seed)
    probe = SimulatedPingProbe(container.settings.probe.ping_count, seed=seed)
    registry = build_registry(lambda _t: [probe], container.policy, container.catalog)
    tracer = SimulatedTracer()
    devices, _ = container.devices.get_all()
    end = datetime.now().replace(second=0, microsecond=0)
    t = end - timedelta(days=days)
    cycles = 0
    while t <= end:
        results = [replace(registry.for_device(d).check(d), timestamp=t) for d in devices]
        container.store.save_cycle(results, duration_s=random.uniform(6, 14), errors=0)
        container.bus.publish(CycleCompleted(results, 0, 0))
        if cycles % max(1, (6 * 60) // step_minutes) == 0:  # traceroute cada ~6 h
            for d in devices:
                hops, reached = tracer.trace(d.primary_ip)
                container.store.save_traceroute(TracerouteResult(d.id, d.name, d.primary_ip, t, tuple(hops), reached))
        cycles += 1
        t += timedelta(minutes=step_minutes)
    log.info("Demo: %d ciclos simulados para %d equipos", cycles, len(devices))
    return cycles
