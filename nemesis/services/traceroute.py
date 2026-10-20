"""Medición de saltos reales (traceroute) por dispositivo."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Sequence

from nemesis.domain.models import Device, TracerouteResult
from nemesis.infrastructure.probes.base import Tracer
from nemesis.infrastructure.repositories import InventoryRepository, SqliteStore

log = logging.getLogger(__name__)


class TracerouteService:
    def __init__(self, devices: InventoryRepository, tracer: Tracer, store: SqliteStore,
                 interval_minutes: int = 60, enabled: bool = True, max_workers: int = 16):
        self._devices = devices
        self._tracer = tracer
        self._store = store
        self._interval = timedelta(minutes=max(5, interval_minutes))
        self._enabled = enabled
        self._max_workers = max_workers

    def is_due(self, now: datetime | None = None) -> bool:
        if not self._enabled:
            return False
        last = self._store.last_traceroute_ts()
        return last is None or (now or datetime.now()) - last >= self._interval

    def trace_device(self, device: Device, persist: bool = True) -> list[TracerouteResult]:
        results = []
        for target in device.targets:
            hops, reached = self._tracer.trace(target.ip)
            result = TracerouteResult(device.id, f"{device.name} [{target.role}]" if len(device.targets) > 1 else device.name,
                                      target.ip, datetime.now().replace(microsecond=0), tuple(hops), reached)
            if persist:
                self._store.save_traceroute(result)
            results.append(result)
        return results

    def trace_all(self, devices: Sequence[Device] | None = None) -> int:
        if devices is None:
            devices, _ = self._devices.get_all()
        devices = [d for d in devices if not d.is_reserved]
        log.info("Traceroute de %d equipos...", len(devices))
        done = 0
        with ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="trace") as pool:
            for results in pool.map(self._safe_trace, devices):
                done += len(results)
        log.info("Traceroute finalizado (%d rutas)", done)
        return done

    def _safe_trace(self, device: Device) -> list[TracerouteResult]:
        try:
            return self.trace_device(device)
        except Exception:
            log.exception("Traceroute falló para %s", device.name)
            return []
