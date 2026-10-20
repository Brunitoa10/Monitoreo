"""Gestión de incidentes con confirmación anti-flapping (Observer de CycleCompleted)."""
from __future__ import annotations

import logging
from datetime import datetime
import threading
from collections import defaultdict

from nemesis.core.events import CycleCompleted, EventBus, IncidentClosed, IncidentEscalated, IncidentOpened
from nemesis.domain.enums import Status
from nemesis.domain.models import HealthResult, Incident
from nemesis.infrastructure.repositories import SqliteStore

log = logging.getLogger(__name__)

PROBLEM_STATES = (Status.WARNING, Status.CRITICAL)


class IncidentService:
    """Abre un incidente cuando un equipo falla N ciclos seguidos y lo cierra al recuperarse.

    El estado se rehidrata desde la base al iniciar, así un reinicio del colector no
    duplica ni pierde incidentes abiertos.
    """

    def __init__(self, store: SqliteStore, bus: EventBus, confirm_cycles: int = 2):
        self._store = store
        self._bus = bus
        self._confirm = max(1, confirm_cycles)
        self._lock = threading.Lock()
        self._streak: dict[str, int] = defaultdict(int)
        self._first_fail: dict[str, datetime] = {}   # primer chequeo fallido de la racha actual
        self._last_ok: dict[str, datetime] = {}      # último chequeo OK (para acotar el momento de la caída)
        self._open: dict[str, Incident] = {i.device_id: i for i in store.open_incidents()}
        bus.subscribe(CycleCompleted, self.on_cycle)

    def on_cycle(self, event: CycleCompleted) -> None:
        with self._lock:
            for result in event.results:
                self._process(result)

    def _process(self, result: HealthResult) -> None:
        device_id = result.device.id
        current = self._open.get(device_id)

        if result.status in PROBLEM_STATES:
            self._streak[device_id] += 1
            self._first_fail.setdefault(device_id, result.timestamp)
            if current is None and self._streak[device_id] >= self._confirm:
                self._open_incident(result)
            elif current is not None and result.status.severity > current.status.severity:
                current.status, current.message = result.status, result.message
                self._store.escalate_incident(current.id, current.status, current.message)
                self._bus.publish(IncidentEscalated(current))
            return

        self._streak[device_id] = 0
        self._first_fail.pop(device_id, None)
        if result.status == Status.HEALTHY:
            self._last_ok[device_id] = result.timestamp
        if current is not None and result.status == Status.HEALTHY:
            current.ended_at = result.timestamp
            self._store.close_incident(current.id, current.ended_at)
            del self._open[device_id]
            log.info("Incidente cerrado: %s (%.0fs)", current.device_name, current.duration_seconds())
            self._bus.publish(IncidentClosed(current))

    def _open_incident(self, result: HealthResult) -> None:
        d = result.device
        # La caída se fecha en el PRIMER chequeo fallido (no en el que la confirma), para auditoría.
        started = self._first_fail.get(d.id, result.timestamp)
        incident = Incident(d.id, d.name, d.site, d.type, result.status, started, message=result.message,
                            last_ok_at=self._last_ok.get(d.id))
        incident.id = self._store.open_incident(incident)
        self._open[d.id] = incident
        log.warning("Incidente abierto: %s [%s] %s", d.name, result.status.value, result.message)
        self._bus.publish(IncidentOpened(incident))

    @property
    def open_incidents(self) -> list[Incident]:
        with self._lock:
            return list(self._open.values())
