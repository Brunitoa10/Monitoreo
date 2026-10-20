"""Política de evaluación de estado (patrón Strategy).

Separa "cómo se mide" (probes) de "cómo se decide el estado" (policy). Cambiar
la regla de negocio no requiere tocar los monitores (SRP / OCP).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping, Sequence

from nemesis.domain.enums import Status
from nemesis.domain.models import Device, ProbeResult


@dataclass(frozen=True)
class Thresholds:
    latency_warning_ms: float = 100.0
    loss_warning_pct: float = 34.0
    jitter_warning_ms: float = 50.0


class StatusPolicy(ABC):
    @abstractmethod
    def evaluate(self, device: Device, probes: Sequence[ProbeResult]) -> tuple[Status, str]:
        ...


class ThresholdStatusPolicy(StatusPolicy):
    """HEALTHY / WARNING (degradado o parcial) / CRITICAL / AVAILABLE."""

    def __init__(self, default: Thresholds, per_type: Mapping[str, Thresholds] | None = None):
        self._default = default
        self._per_type = {k.lower(): v for k, v in (per_type or {}).items()}

    def thresholds_for(self, device_type: str) -> Thresholds:
        return self._per_type.get(device_type.lower(), self._default)

    def evaluate(self, device: Device, probes: Sequence[ProbeResult]) -> tuple[Status, str]:
        if not probes:
            return Status.UNKNOWN, "Sin chequeos configurados"

        online = [p for p in probes if p.online]
        if device.is_reserved:  # stock / sin asignar: se informa pero no cuenta en la disponibilidad
            return Status.AVAILABLE, "Disponible (responde)" if online else "Disponible (sin respuesta)"
        if not online:
            return Status.CRITICAL, "Sin respuesta"

        down = [p for p in probes if not p.online]
        if down:
            roles = ", ".join(f"{p.role} ({p.method})" for p in down)
            return Status.WARNING, f"Respuesta parcial - sin respuesta: {roles}"

        th = self.thresholds_for(device.type)
        problems: list[str] = []
        worst_latency = max((p.rtt_avg_ms or 0.0) for p in online)
        if worst_latency > th.latency_warning_ms:
            problems.append(f"latencia {worst_latency:.0f} ms > {th.latency_warning_ms:.0f} ms")
        worst_loss = max(p.loss_pct for p in online)
        if worst_loss >= th.loss_warning_pct:
            problems.append(f"pérdida {worst_loss:.0f}%")
        worst_jitter = max((p.jitter_ms or 0.0) for p in online)
        if worst_jitter > th.jitter_warning_ms:
            problems.append(f"jitter {worst_jitter:.0f} ms")

        if problems:
            return Status.WARNING, "Degradado: " + ", ".join(problems)
        return Status.HEALTHY, "OK"
