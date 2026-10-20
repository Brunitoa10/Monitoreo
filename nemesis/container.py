"""Composition Root: el único lugar donde se instancian y conectan las dependencias (DI manual).

El resto del código recibe sus dependencias por constructor, lo que permite
reemplazar cualquier pieza (ej. probes simulados en tests) sin tocar la lógica.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Sequence

from nemesis.config import Settings, load_settings
from nemesis.core.events import EventBus
from nemesis.core.logging_setup import configure_logging
from nemesis.domain.device_types import TypeCatalog
from nemesis.domain.status_policy import ThresholdStatusPolicy
from nemesis.domain.validation import default_validator
from nemesis.infrastructure.probes import (Probe, SimulatedPingProbe, SimulatedTracer, SystemPingProbe, SystemTracer,
                                           TcpProbe)
from nemesis.infrastructure.repositories import (InventoryRepository, JsonDeviceRepository,
                                                 SqliteInventoryRepository, SqliteStore)
from nemesis.monitors import build_registry
from nemesis.reporting import ReportService
from nemesis.services.admin import AdminAuthenticator, InventoryAdminService
from nemesis.services.incidents import IncidentService
from nemesis.services.insights import InsightEngine
from nemesis.services.metrics import MetricsService
from nemesis.services.monitoring import MonitoringService
from nemesis.services.notifications import LogNotifier, NotificationService, Notifier, WebhookNotifier
from nemesis.services.scheduler import CollectorScheduler
from nemesis.services.traceroute import TracerouteService

log = logging.getLogger(__name__)


class Container:
    def __init__(self, settings: Settings):
        self.settings = s = settings
        configure_logging(s.paths.logs_dir)
        self.simulated = s.probe.mode.lower() == "simulated"

        # --- infraestructura
        self.store = SqliteStore(s.paths.database)
        self.catalog = TypeCatalog.from_settings(s.type_definitions)
        self.devices: InventoryRepository = self.inventory_repository(s.inventory.backend)
        self.bus = EventBus()

        # --- dominio / monitoreo
        self.policy = ThresholdStatusPolicy(s.default_thresholds, s.type_thresholds)
        self._ping: Probe = (SimulatedPingProbe(s.probe.ping_count) if self.simulated
                             else SystemPingProbe(s.probe.ping_count, s.probe.ping_timeout_ms))
        self._tcp_cache: dict[str, list[Probe]] = {}
        self.registry = build_registry(self._probes_for, self.policy, self.catalog)
        self.validator = default_validator(self.catalog.names, s.site_aliases)

        # --- servicios
        self.monitoring = MonitoringService(self.devices, self.registry, self.store, self.bus, s.collector.max_workers)
        self.incidents = IncidentService(self.store, self.bus, s.collector.confirm_cycles)
        notifiers: list[Notifier] = [LogNotifier()]
        if s.notifications.webhook_url:
            notifiers.append(WebhookNotifier(s.notifications.webhook_url))
        self.notifications = NotificationService(self.bus, notifiers, s.notifications.notify_on_open,
                                                 s.notifications.notify_on_close)
        tracer = SimulatedTracer() if self.simulated else SystemTracer(s.probe.traceroute_max_hops,
                                                                       s.probe.traceroute_timeout_ms)
        self.traceroute = TracerouteService(self.devices, tracer, self.store, s.probe.traceroute_interval_minutes,
                                            s.probe.traceroute_enabled)
        self.scheduler = CollectorScheduler(self.monitoring, self.traceroute, self.store,
                                            s.collector.interval_seconds, s.collector.retention_days)
        self.metrics = MetricsService(self.store)
        self.insights = InsightEngine()
        self.admin = InventoryAdminService(self.devices, self.validator, self.catalog)
        self.auth = AdminAuthenticator(s.paths.admin_file)
        self.reports = ReportService(self.metrics, self.insights, s.paths.reports_dir, s.app.name, s.app.organization,
                                     s.default_thresholds.latency_warning_ms, issues_provider=self.admin.validate_all)

    def inventory_repository(self, backend: str) -> InventoryRepository:
        """Factory del backend de inventario (json | sqlite)."""
        if backend.lower() in ("sqlite", "db", "base", "bd"):
            return SqliteInventoryRepository(self.settings.paths.database, self.catalog)
        return JsonDeviceRepository(self.settings.paths.devices_dir, self.settings.paths.backups_dir, self.catalog)

    def _probes_for(self, device_type: str) -> Sequence[Probe]:
        key = device_type.lower()
        if key not in self._tcp_cache:
            ports = next((p for t, p in self.settings.tcp_ports.items() if t.lower() == key), ())
            self._tcp_cache[key] = [self._ping] + [TcpProbe(port) for port in ports if not self.simulated]
        return self._tcp_cache[key]


@lru_cache(maxsize=1)
def get_container(settings_path: str | None = None) -> Container:
    return Container(load_settings(settings_path))
