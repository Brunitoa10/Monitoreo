"""Bus de eventos en memoria (patrón Observer).

El servicio de monitoreo sólo publica "terminé un ciclo"; incidentes, notificaciones
y logs se suscriben sin que el servicio los conozca (bajo acoplamiento).
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Sequence, TypeVar

from nemesis.domain.models import HealthResult, Incident

log = logging.getLogger(__name__)
E = TypeVar("E")


@dataclass(frozen=True)
class CycleCompleted:
    results: Sequence[HealthResult]
    duration_s: float
    errors: int


@dataclass(frozen=True)
class IncidentOpened:
    incident: Incident


@dataclass(frozen=True)
class IncidentEscalated:
    incident: Incident


@dataclass(frozen=True)
class IncidentClosed:
    incident: Incident


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        with self._lock:
            self._handlers[event_type].append(handler)

    def publish(self, event: object) -> None:
        with self._lock:
            handlers = list(self._handlers[type(event)])
        for handler in handlers:
            try:
                handler(event)
            except Exception:  # un suscriptor con error no debe frenar a los demás
                log.exception("Error en handler de %s", type(event).__name__)
