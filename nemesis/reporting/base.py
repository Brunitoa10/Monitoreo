"""Contrato común de los exportadores (Strategy) y el dataset que consumen."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from nemesis.domain.models import Insight
from nemesis.services.metrics import Kpis, ReportFilter


@dataclass
class ReportDataset:
    """Todo lo que un reporte necesita, ya calculado (los exporters no consultan la base)."""

    title: str
    organization: str
    filter: ReportFilter
    generated_at: datetime
    kpis: Kpis
    insights: list[Insight]
    by_site: pd.DataFrame
    by_type: pd.DataFrame
    devices: pd.DataFrame
    incidents: pd.DataFrame
    hops: pd.DataFrame
    availability_series: pd.DataFrame
    latency_series: pd.DataFrame
    audit: pd.DataFrame = field(default_factory=pd.DataFrame)          # una fila por falla (auditoría)
    audit_summary: pd.DataFrame = field(default_factory=pd.DataFrame)  # totales por equipo
    hourly: pd.DataFrame = field(default_factory=pd.DataFrame)
    checks: pd.DataFrame = field(default_factory=pd.DataFrame)
    traceroutes: pd.DataFrame = field(default_factory=pd.DataFrame)


class ReportExporter(ABC):
    key: str
    label: str
    extension: str
    mime: str

    @abstractmethod
    def export(self, data: ReportDataset) -> bytes:
        ...

    def filename(self, data: ReportDataset) -> str:
        return f"nemesis_reporte_{data.generated_at:%Y%m%d_%H%M}.{self.extension}"
