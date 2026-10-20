"""Caso de uso principal: ejecutar un ciclo de monitoreo sobre todo el inventario (Facade)."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

from nemesis.core.events import CycleCompleted, EventBus
from nemesis.domain.enums import Status
from nemesis.domain.models import Device, HealthResult
from nemesis.infrastructure.repositories import InventoryRepository, SqliteStore
from nemesis.infrastructure.repositories.json_devices import LoadError
from nemesis.monitors import MonitorRegistry

log = logging.getLogger(__name__)


@dataclass
class CycleReport:
    results: list[HealthResult]
    duration_s: float
    errors: list[str] = field(default_factory=list)
    load_errors: list[LoadError] = field(default_factory=list)

    def count(self, status: Status) -> int:
        return sum(1 for r in self.results if r.status == status)


class MonitoringService:
    def __init__(
        self,
        devices: InventoryRepository,
        registry: MonitorRegistry,
        store: SqliteStore,
        bus: EventBus,
        max_workers: int = 32,
    ):
        self._devices = devices
        self._registry = registry
        self._store = store
        self._bus = bus
        self._max_workers = max_workers

    def run_cycle(self, persist: bool = True) -> CycleReport:
        start = time.perf_counter()
        devices, load_errors = self._devices.get_all()
        for err in load_errors:
            log.warning("Inventario: %s - %s", err.file, err.message)
        if not devices:
            log.warning("No hay dispositivos cargados (%s)", self._devices.describe())
            return CycleReport([], 0.0, load_errors=load_errors)

        results, errors = self.check_many(devices)
        duration = time.perf_counter() - start
        if persist:
            self._store.save_cycle(results, duration, len(errors))
            self._bus.publish(CycleCompleted(results, duration, len(errors)))
        log.info(
            "Ciclo: %d equipos en %.1fs | OK %d | Degradado %d | Caído %d",
            len(results), duration,
            sum(r.status == Status.HEALTHY for r in results),
            sum(r.status == Status.WARNING for r in results),
            sum(r.status == Status.CRITICAL for r in results),
        )
        return CycleReport(results, duration, errors, load_errors)

    def check_many(self, devices: Sequence[Device]) -> tuple[list[HealthResult], list[str]]:
        results: list[HealthResult] = []
        errors: list[str] = []
        workers = max(1, min(self._max_workers, len(devices)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="probe") as pool:
            futures = {pool.submit(self._registry.for_device(d).check, d): d for d in devices}
            for future in as_completed(futures):
                device = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # un equipo con error no corta el ciclo
                    log.exception("Error chequeando %s", device.name)
                    errors.append(f"{device.name}: {exc}")
                    results.append(HealthResult(device, Status.UNKNOWN, (), datetime.now().replace(microsecond=0), str(exc)))
        results.sort(key=lambda r: (r.device.type, r.device.site, r.device.name))
        return results, errors

    def check_one(self, device: Device) -> HealthResult:
        return self._registry.for_device(device).check(device)
