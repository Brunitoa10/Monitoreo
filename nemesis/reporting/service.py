"""Arma el dataset del reporte y delega la exportación al formato elegido (Strategy + Registry)."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from nemesis.domain.models import ValidationIssue
from nemesis.reporting.base import ReportDataset, ReportExporter
from nemesis.reporting.excel_exporter import ExcelExporter
from nemesis.reporting.pdf_exporter import PdfExporter
from nemesis.reporting.powerbi_exporter import PowerBiExporter
from nemesis.services.insights import InsightContext, InsightEngine
from nemesis.services.metrics import MetricsService, ReportFilter

log = logging.getLogger(__name__)


class ReportService:
    def __init__(self, metrics: MetricsService, insights: InsightEngine, reports_dir: Path,
                 title: str, organization: str, latency_warning_ms: float = 100.0,
                 issues_provider=lambda: []):
        self._metrics = metrics
        self._insights = insights
        self._dir = Path(reports_dir)
        self._title = title
        self._org = organization
        self._latency_warning = latency_warning_ms
        self._issues_provider = issues_provider
        self._exporters: dict[str, ReportExporter] = {}
        for exporter in (PdfExporter(), ExcelExporter(), PowerBiExporter()):
            self.register(exporter)

    def register(self, exporter: ReportExporter) -> None:
        self._exporters[exporter.key] = exporter

    @property
    def exporters(self) -> list[ReportExporter]:
        return list(self._exporters.values())

    def exporter(self, key: str) -> ReportExporter:
        try:
            return self._exporters[key]
        except KeyError:
            raise ValueError(f"Formato no soportado: {key}. Opciones: {', '.join(self._exporters)}") from None

    def insight_context(self, f: ReportFilter, issues: list[ValidationIssue] | None = None) -> InsightContext:
        m = self._metrics
        return InsightContext(
            kpis=m.kpis(f), devices=m.device_metrics(f), by_site=m.by_group(f, "site"),
            by_type=m.by_group(f, "type"), incidents=m.incidents(f), hops=m.hops_summary(f),
            issues=issues if issues is not None else self._issues_provider(),
            latency_warning_ms=self._latency_warning,
        )

    def build_dataset(self, f: ReportFilter, include_raw: bool = True) -> ReportDataset:
        ctx = self.insight_context(f)
        m = self._metrics
        return ReportDataset(
            title=f"{self._title} — Reporte de disponibilidad",
            organization=self._org,
            filter=f,
            generated_at=datetime.now(),
            kpis=ctx.kpis,
            insights=self._insights.generate(ctx),
            by_site=ctx.by_site,
            by_type=ctx.by_type,
            devices=ctx.devices,
            incidents=ctx.incidents,
            hops=ctx.hops,
            availability_series=m.availability_series(f),
            latency_series=m.latency_series(f, by="type"),
            audit=m.audit_log(f),
            audit_summary=m.audit_summary(f),
            hourly=m.hourly_by_device(f) if include_raw else pd.DataFrame(),
            checks=m.checks(f) if include_raw else pd.DataFrame(),
            traceroutes=m.traceroutes(f),
        )

    def generate(self, key: str, f: ReportFilter, save: bool = True,
                 dataset: ReportDataset | None = None) -> tuple[str, bytes, Path | None]:
        exporter = self.exporter(key)
        data = dataset or self.build_dataset(f, include_raw=key != "pdf")
        content = exporter.export(data)
        name = exporter.filename(data)
        path = None
        if save:
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self._dir / name
            path.write_bytes(content)
            if isinstance(exporter, PowerBiExporter):
                exporter.export_folder(data, self._dir / "powerbi" / "latest")
            log.info("Reporte generado: %s", path)
        return name, content, path
