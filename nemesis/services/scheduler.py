"""Colector en segundo plano: ciclos periódicos, traceroute y purga de histórico."""
from __future__ import annotations

import logging
import os
import socket
import threading
import uuid
from datetime import datetime, timedelta

from nemesis.infrastructure.repositories import SqliteStore
from nemesis.services.monitoring import MonitoringService
from nemesis.services.traceroute import TracerouteService

log = logging.getLogger(__name__)
LEASE_NAME = "collector"


class CollectorScheduler:
    def __init__(self, monitoring: MonitoringService, traceroute: TracerouteService, store: SqliteStore,
                 interval_seconds: int = 30, retention_days: int = 90):
        self._monitoring = monitoring
        self._traceroute = traceroute
        self._store = store
        self._interval = max(5, interval_seconds)
        self._retention = timedelta(days=max(1, retention_days))
        self._owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._trace_thread: threading.Thread | None = None
        self._last_purge: datetime | None = None
        self.is_leader = False

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self.run_forever, name="nemesis-collector", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._store.release_lease(LEASE_NAME, self._owner)

    def run_forever(self) -> None:
        log.info("Colector iniciado (cada %ss) id=%s", self._interval, self._owner)
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self._interval)

    def tick(self) -> None:
        # Sólo un colector activo por base de datos (el otro queda en espera).
        self.is_leader = self._store.try_acquire_lease(LEASE_NAME, self._owner, ttl_seconds=self._interval * 3)
        if not self.is_leader:
            return
        try:
            self._monitoring.run_cycle()
            self._maybe_traceroute()
            self._maybe_purge()
        except Exception:
            log.exception("Error en ciclo del colector")

    def _maybe_traceroute(self) -> None:
        busy = self._trace_thread is not None and self._trace_thread.is_alive()
        if not busy and self._traceroute.is_due():
            self._trace_thread = threading.Thread(target=self._traceroute.trace_all, name="nemesis-trace", daemon=True)
            self._trace_thread.start()

    def _maybe_purge(self) -> None:
        now = datetime.now()
        if self._last_purge and now - self._last_purge < timedelta(hours=12):
            return
        removed = self._store.purge(now - self._retention)
        self._last_purge = now
        if removed:
            log.info("Purga de histórico: %d mediciones eliminadas", removed)
