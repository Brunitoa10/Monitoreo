"""Motor de hallazgos y recomendaciones automáticas para la vista ejecutiva.

Cada regla es independiente (Strategy). Para agregar una recomendación nueva se
crea una clase InsightRule y se suma a default_rules().
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import pandas as pd

from nemesis.domain.enums import InsightLevel, IssueSeverity
from nemesis.domain.models import Insight, ValidationIssue, format_duration
from nemesis.services.metrics import Kpis


@dataclass
class InsightContext:
    kpis: Kpis
    devices: pd.DataFrame
    by_site: pd.DataFrame
    by_type: pd.DataFrame
    incidents: pd.DataFrame
    hops: pd.DataFrame
    issues: Sequence[ValidationIssue] = field(default_factory=list)
    latency_warning_ms: float = 100.0


class InsightRule(ABC):
    @abstractmethod
    def evaluate(self, ctx: InsightContext) -> Iterable[Insight]:
        ...


def _names(df: pd.DataFrame, n: int = 5) -> str:
    items = [f"{r.equipo} ({r.sitio})" for r in df.head(n).itertuples()]
    extra = len(df) - n
    return ", ".join(items) + (f" y {extra} más" if extra > 0 else "")


class AvailabilityRule(InsightRule):
    """Resumen de disponibilidad del período (informativo, sin objetivo contractual)."""

    def evaluate(self, ctx):
        k = ctx.kpis
        if k.availability_pct is None:
            return
        level = InsightLevel.POSITIVE if k.incidents_total == 0 else InsightLevel.INFO
        yield Insight(level, f"Disponibilidad del período {k.availability_pct:.2f}%",
                      f"{k.incidents_total} fallas en {k.devices_with_failures} equipos · tiempo total con falla: "
                      f"{format_duration((k.downtime_min or 0) * 60)}.",
                      "El detalle de cada falla (fecha, hora de caída y de recuperación, duración) está en Auditoría.")


class MostDowntimeRule(InsightRule):
    """Equipos que más tiempo estuvieron con falla en el período."""

    def evaluate(self, ctx):
        d = ctx.devices
        if d.empty:
            return
        worst = d[d["downtime_min"] > 0].sort_values("downtime_min", ascending=False)
        if not worst.empty:
            top = "; ".join(f"{r.equipo} ({r.sitio}): {format_duration(r.downtime_min * 60)}" for r in worst.head(5).itertuples())
            yield Insight(InsightLevel.WARNING, f"{len(worst)} equipos con tiempo de falla en el período", top,
                          "Revisar primero los de mayor tiempo caído: energía/UPS, patcheo y logs del switch de acceso.")


class ChronicDownRule(InsightRule):
    def evaluate(self, ctx):
        d = ctx.devices
        if d.empty:
            return
        dead = d[(d["disponibilidad_pct"] < 50) & (d["mediciones"] >= 10)]
        if not dead.empty:
            yield Insight(InsightLevel.CRITICAL, f"{len(dead)} equipos caídos la mayor parte del período",
                          _names(dead),
                          "Verificar si siguen instalados. Si fueron retirados, marcarlos como 'Disponible' o darlos de baja en el panel admin para no distorsionar las métricas.")


class FlappingRule(InsightRule):
    THRESHOLD = 5

    def evaluate(self, ctx):
        d = ctx.devices
        if d.empty:
            return
        flapping = d[d["incidentes"] >= self.THRESHOLD].sort_values("incidentes", ascending=False)
        if not flapping.empty:
            yield Insight(InsightLevel.WARNING, f"Intermitencia (flapping) en {len(flapping)} equipos",
                          _names(flapping),
                          "Cortes cortos y repetidos suelen ser cableado/conector, PoE insuficiente, puerto con errores (CRC) o negociación de velocidad. Revisar contadores de interfaz.")


class LatencyRule(InsightRule):
    def evaluate(self, ctx):
        d = ctx.devices
        if d.empty:
            return
        slow = d[d["latencia_p95_ms"] > ctx.latency_warning_ms].sort_values("latencia_p95_ms", ascending=False)
        if not slow.empty:
            yield Insight(InsightLevel.WARNING, f"Latencia alta (p95 > {ctx.latency_warning_ms:.0f} ms) en {len(slow)} equipos",
                          _names(slow),
                          "En LAN la latencia debería ser < 5 ms. Revisar saturación de uplinks, enlaces inalámbricos (alineación / interferencia) y aplicar QoS si comparten tráfico de video.")


class PacketLossRule(InsightRule):
    def evaluate(self, ctx):
        d = ctx.devices
        if d.empty:
            return
        lossy = d[d["perdida_prom_pct"] > 2].sort_values("perdida_prom_pct", ascending=False)
        if not lossy.empty:
            yield Insight(InsightLevel.WARNING, f"Pérdida de paquetes > 2% en {len(lossy)} equipos",
                          _names(lossy),
                          "La pérdida sostenida degrada video/cartelería y sesiones. Revisar errores de interfaz, duplex mismatch y nivel de señal en radios.")


class SiteConcentrationRule(InsightRule):
    """Sitio con proporción de incidentes muy superior a su proporción de equipos."""

    def evaluate(self, ctx):
        s = ctx.by_site
        if s.empty or s["incidentes"].sum() < 5 or len(s) < 2:
            return
        s = s.assign(share_inc=s["incidentes"] / s["incidentes"].sum(), share_dev=s["equipos"] / s["equipos"].sum())
        s = s.assign(ratio=s["share_inc"] / s["share_dev"]).sort_values("ratio", ascending=False)
        top = s.iloc[0]
        if top["ratio"] >= 1.5 and top["incidentes"] >= 3:
            yield Insight(InsightLevel.WARNING,
                          f"El sitio {top['site']} tiene {top['ratio']:.1f}× más incidentes de lo esperable",
                          f"Concentra el {top['share_inc']:.0%} de los incidentes con el {top['share_dev']:.0%} de los equipos.",
                          "Revisar infraestructura común del sitio: switch de distribución, enlace troncal, UPS y climatización del rack.")


class LinkRule(InsightRule):
    def evaluate(self, ctx):
        d = ctx.devices
        if d.empty:
            return
        links = d[(d["tipo"].str.lower() == "enlace") & (d["incidentes"] > 0)]
        if not links.empty:
            yield Insight(InsightLevel.WARNING, f"{len(links)} enlaces punto a punto con fallas",
                          _names(links),
                          "Verificar alineación, nivel de señal (RSSI/SNR), fijación de mástil y alimentación PoE del extremo Hijo.")


class HopsRule(InsightRule):
    def evaluate(self, ctx):
        h = ctx.hops
        if h.empty or "rutas_distintas" not in h:
            return
        unstable = h[h["rutas_distintas"] > 1]
        if not unstable.empty:
            yield Insight(InsightLevel.INFO, f"Ruta inestable hacia {len(unstable)} equipos",
                          ", ".join(unstable["equipo"].head(5)),
                          "El camino cambió entre mediciones: puede ser failover, STP reconvergiendo o rutas asimétricas. Verificar topología STP/routing.")
        deep = h[h["saltos_traceroute"] > 6]
        if not deep.empty:
            yield Insight(InsightLevel.INFO, f"{len(deep)} equipos a más de 6 saltos",
                          ", ".join(deep["equipo"].head(5)),
                          "Muchos saltos suman latencia y puntos de falla. Evaluar si la segmentación/routing es la óptima.")


class MttrRule(InsightRule):
    def evaluate(self, ctx):
        k = ctx.kpis
        if k.mttr_min is None:
            return
        if k.mttr_min > 60:
            yield Insight(InsightLevel.WARNING, f"MTTR de {k.mttr_min:.0f} minutos",
                          "El tiempo medio de recuperación supera la hora.",
                          "Activar notificaciones por webhook (Teams) y definir guardia/escalamiento para reducir el tiempo de respuesta.")
        else:
            yield Insight(InsightLevel.POSITIVE, f"MTTR de {k.mttr_min:.0f} minutos",
                          "La recuperación promedio está dentro de la hora.", "Documentar las causas raíz para seguir bajándolo.")


class OpenIncidentsRule(InsightRule):
    def evaluate(self, ctx):
        k = ctx.kpis
        if k.down_now:
            yield Insight(InsightLevel.CRITICAL, f"{k.down_now} equipos caídos ahora mismo",
                          f"Hay {k.incidents_open} incidentes abiertos.",
                          "Atender primero los equipos de infraestructura (switches/enlaces): una caída aguas arriba explica varias alarmas aguas abajo.")


class DataQualityRule(InsightRule):
    def evaluate(self, ctx):
        errors = [i for i in ctx.issues if i.severity == IssueSeverity.ERROR]
        if errors:
            dup = sum("duplicada" in i.message for i in errors)
            yield Insight(InsightLevel.INFO, f"{len(errors)} problemas de calidad en el inventario",
                          f"Incluye {dup} registros con IP duplicada." if dup else "Ver panel de administración.",
                          "Corregir desde Administración → Calidad de datos. Las IP duplicadas hacen que un equipo caído aparezca como operativo.")


def default_rules() -> list[InsightRule]:
    return [OpenIncidentsRule(), AvailabilityRule(), ChronicDownRule(), MostDowntimeRule(), FlappingRule(), LinkRule(),
            LatencyRule(), PacketLossRule(), SiteConcentrationRule(), HopsRule(), MttrRule(), DataQualityRule()]


class InsightEngine:
    _ORDER = {InsightLevel.CRITICAL: 0, InsightLevel.WARNING: 1, InsightLevel.INFO: 2, InsightLevel.POSITIVE: 3}

    def __init__(self, rules: Sequence[InsightRule] | None = None):
        self._rules = list(rules or default_rules())

    def generate(self, ctx: InsightContext) -> list[Insight]:
        insights = [i for rule in self._rules for i in rule.evaluate(ctx)]
        return sorted(insights, key=lambda i: self._ORDER[i.level])
