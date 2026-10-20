"""Notificaciones de incidentes (Observer + Strategy por canal)."""
from __future__ import annotations

import json
import logging
import urllib.request
from abc import ABC, abstractmethod
from typing import Sequence

from nemesis.core.events import EventBus, IncidentClosed, IncidentEscalated, IncidentOpened
from nemesis.domain.models import Incident

log = logging.getLogger(__name__)


class Notifier(ABC):
    @abstractmethod
    def send(self, title: str, text: str) -> None:
        ...


class LogNotifier(Notifier):
    def send(self, title: str, text: str) -> None:
        log.warning("%s | %s", title, text)


class WebhookNotifier(Notifier):
    """Compatible con Incoming Webhooks de Microsoft Teams y Slack (campo "text")."""

    def __init__(self, url: str, timeout: float = 5.0):
        self._url = url
        self._timeout = timeout

    def send(self, title: str, text: str) -> None:
        body = json.dumps({"title": title, "text": f"**{title}**\n\n{text}"}).encode()
        req = urllib.request.Request(self._url, data=body, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=self._timeout).close()
        except OSError as exc:
            log.error("No se pudo enviar webhook: %s", exc)


def _describe(incident: Incident) -> str:
    return f"{incident.device_name} ({incident.type} · {incident.site}) — {incident.message}"


class NotificationService:
    def __init__(self, bus: EventBus, notifiers: Sequence[Notifier], on_open: bool = True, on_close: bool = True):
        self._notifiers = list(notifiers)
        if on_open:
            bus.subscribe(IncidentOpened, lambda e: self._send(f"🔴 {e.incident.status.label}", _describe(e.incident)))
            bus.subscribe(IncidentEscalated, lambda e: self._send(f"🔴 Escalado a {e.incident.status.label}", _describe(e.incident)))
        if on_close:
            bus.subscribe(IncidentClosed, self._on_closed)

    def _on_closed(self, event: IncidentClosed) -> None:
        minutes = event.incident.duration_seconds() / 60
        self._send("🟢 Recuperado", f"{event.incident.device_name} ({event.incident.site}) tras {minutes:.1f} min")

    def _send(self, title: str, text: str) -> None:
        for notifier in self._notifiers:
            notifier.send(title, text)
