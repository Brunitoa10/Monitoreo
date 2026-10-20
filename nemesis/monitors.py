"""Monitores por tipo de dispositivo.

- Template Method: Monitor.check() define el algoritmo (medir -> evaluar -> armar resultado)
  y las subclases sólo redefinen los pasos que cambian.
- Registry + Factory: MonitorRegistry asocia "Type" del JSON -> monitor. Para un tipo nuevo
  (ej. "Camara") alcanza con registrarlo; no hace falta tocar MonitoringService (OCP).
"""
from __future__ import annotations

from abc import ABC
from datetime import datetime
from typing import Callable, Sequence

from nemesis.domain.enums import Status
from nemesis.domain.models import Device, HealthResult, ProbeResult
from nemesis.domain.status_policy import StatusPolicy
from nemesis.infrastructure.probes.base import Probe

ProbeFactory = Callable[[str], Sequence[Probe]]  # tipo de dispositivo -> probes a ejecutar


class Monitor(ABC):
    def __init__(self, probes_for: ProbeFactory, policy: StatusPolicy):
        self._probes_for = probes_for
        self._policy = policy

    def check(self, device: Device) -> HealthResult:
        probes = self._measure(device)
        status, message = self._evaluate(device, probes)
        return HealthResult(device, status, tuple(probes), datetime.now().replace(microsecond=0), message)

    # ---- pasos redefinibles ------------------------------------------------
    def _measure(self, device: Device) -> list[ProbeResult]:
        results: list[ProbeResult] = []
        for target in device.targets:
            for probe in self._probes_for(device.type):
                results.append(probe.probe(target))
        return results

    def _evaluate(self, device: Device, probes: Sequence[ProbeResult]) -> tuple[Status, str]:
        return self._policy.evaluate(device, probes)


class HostMonitor(Monitor):
    """Equipos de un solo extremo: switch, impresora, cartelería, UPS, y tipos nuevos."""


class LinkMonitor(Monitor):
    """Enlaces punto a punto (Padre/Hijo) con diagnóstico de causa raíz."""

    def _evaluate(self, device: Device, probes: Sequence[ProbeResult]) -> tuple[Status, str]:
        status, message = super()._evaluate(device, probes)
        by_role = {p.role.lower(): p for p in probes if p.method == "icmp"}
        padre, hijo = by_role.get("padre"), by_role.get("hijo")
        if padre and hijo:
            if not padre.online and not hijo.online:
                message = "Enlace caído: sin respuesta en ambos extremos (revisar Padre / alimentación / switch de origen)"
            elif padre.online and not hijo.online:
                message = "Radio/extremo Hijo sin respuesta: posible desalineación, energía o equipo remoto"
            elif hijo.online and not padre.online:
                message = "Extremo Padre sin respuesta pero el Hijo responde: revisar gestión del Padre"
        return status, message


class MonitorRegistry:
    def __init__(self, default: Monitor):
        self._default = default
        self._by_type: dict[str, Monitor] = {}

    def register(self, device_type: str, monitor: Monitor) -> None:
        self._by_type[device_type.lower()] = monitor

    def for_device(self, device: Device) -> Monitor:
        return self._by_type.get(device.type.lower(), self._default)

    @property
    def known_types(self) -> list[str]:
        return sorted(self._by_type)


def build_registry(probes_for: ProbeFactory, policy: StatusPolicy, catalog=None) -> MonitorRegistry:
    """Tipos con varios extremos (Padre/Hijo...) usan LinkMonitor; el resto HostMonitor.
    Un tipo nuevo cargado desde el JSON o el panel funciona sin tocar código (monitor por defecto)."""
    from nemesis.domain.device_types import TypeCatalog
    catalog = catalog or TypeCatalog()
    host = HostMonitor(probes_for, policy)
    link = LinkMonitor(probes_for, policy)
    registry = MonitorRegistry(default=host)
    for t in catalog.types:
        registry.register(t.name, link if t.multi_target else host)
    return registry
