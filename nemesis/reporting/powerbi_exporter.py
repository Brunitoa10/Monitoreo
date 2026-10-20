"""Exportación para Power BI: modelo estrella en CSV + guía con relaciones y medidas DAX."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

from nemesis.domain.enums import Status
from nemesis.reporting.base import ReportDataset, ReportExporter
from nemesis.reporting.formatting import LEVEL_LABEL, kpi_rows, status_label

MONTHS = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre",
          "Noviembre", "Diciembre"]
RAW_LIMIT = 300_000
DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

GUIDE = """# Nemesis Monitor → Power BI

## Archivos (modelo estrella)
| Tabla | Tipo | Clave |
|---|---|---|
| dim_dispositivo.csv | Dimensión | device_id |
| dim_fecha.csv | Dimensión (calendario) | fecha |
| fact_mediciones_hora.csv | Hechos (equipo × hora) — tabla principal | device_id, fecha |
| fact_mediciones.csv | Hechos crudos (sólo si el período es chico) | device_id, fecha |
| fact_incidentes.csv | Hechos | device_id, fecha_inicio |
| fact_traceroute.csv | Hechos (saltos) | device_id, fecha |
| auditoria_fallas.csv | Una fila por falla: fecha y hora (con segundos) de caída y recuperación, duración | N° |
| recomendaciones.csv / kpis.csv | Tablas de apoyo para la portada | — |

Formato: UTF-8, separador coma, decimal punto. Al importar elegí
**Configuración regional: Inglés (Estados Unidos)** para que los decimales no se lean mal.

## Cómo cargarlo
1. Power BI Desktop → Obtener datos → **Carpeta** → seleccionar `reports/powerbi/latest`
   (o Texto/CSV archivo por archivo).
2. Relaciones (Vista de modelo):
   - `dim_dispositivo[device_id]` 1 → * `fact_mediciones_hora[device_id]`
   - `dim_dispositivo[device_id]` 1 → * `fact_incidentes[device_id]`
   - `dim_dispositivo[device_id]` 1 → * `fact_traceroute[device_id]`
   - `dim_fecha[fecha]` 1 → * `fact_mediciones_hora[fecha]`
   - `dim_fecha[fecha]` 1 → * `fact_incidentes[fecha_inicio]`
3. Marcar `dim_fecha` como tabla de fechas.
4. Cada vez que generes la exportación desde el dashboard (o con
   `python -m nemesis report --format powerbi`), la carpeta `latest` se actualiza: sólo tocás **Actualizar**.

## Medidas DAX sugeridas
```DAX
Disponibilidad % =
DIVIDE ( SUM ( fact_mediciones_hora[disponibles] ), SUM ( fact_mediciones_hora[mediciones] ) ) * 100

Latencia Prom (ms) =
DIVIDE ( SUMX ( fact_mediciones_hora, fact_mediciones_hora[latencia_prom_ms] * fact_mediciones_hora[disponibles] ),
         SUM ( fact_mediciones_hora[disponibles] ) )

Latencia P95 (ms) = PERCENTILEX.INC ( FILTER ( fact_mediciones_hora, NOT ISBLANK ( fact_mediciones_hora[latencia_p95_ms] ) ), fact_mediciones_hora[latencia_p95_ms], 0.95 )

Pérdida Prom % = AVERAGE ( fact_mediciones_hora[perdida_prom_pct] )

Jitter Prom (ms) = AVERAGE ( fact_mediciones_hora[jitter_prom_ms] )

Incidentes = COUNTROWS ( fact_incidentes )

Incidentes Abiertos = CALCULATE ( COUNTROWS ( fact_incidentes ), fact_incidentes[abierto] = 1 )

MTTR (min) = CALCULATE ( AVERAGE ( fact_incidentes[duracion_min] ), fact_incidentes[abierto] = 0 )

Downtime (h) = DIVIDE ( SUM ( fact_incidentes[duracion_min] ), 60 )

Saltos Prom = AVERAGE ( fact_traceroute[saltos] )

Equipos con fallas = DISTINCTCOUNT ( fact_incidentes[device_id] )

Tiempo con falla (h) = DIVIDE ( SUM ( fact_incidentes[duracion_s] ), 3600 )
```

## Visuales recomendados (página ejecutiva)
- Tarjetas: Disponibilidad %, Incidentes, MTTR, Latencia P95, Equipos con fallas, Tiempo con falla (h).
- Barras: Disponibilidad % por `dim_dispositivo[sitio]` y por `tipo`.
- Tabla de auditoría: `auditoria_fallas` (fecha/hora de caída y de recuperación con segundos, duración).
- Línea: Disponibilidad % y Latencia Prom por `fact_mediciones_hora[fecha_hora]`.
- Matriz: dim_fecha[dia_semana] × fact_mediciones_hora[hora] con Disponibilidad % (mapa de calor de fallas).
- Tabla: equipos ordenados por Downtime (h) con formato condicional.
"""


class PowerBiExporter(ReportExporter):
    key = "powerbi"
    label = "Power BI (modelo estrella CSV)"
    extension = "zip"
    mime = "application/zip"

    def tables(self, data: ReportDataset) -> dict[str, pd.DataFrame]:
        checks = data.checks.copy()
        tables: dict[str, pd.DataFrame] = {}

        dev = data.devices[["device_id", "equipo", "tipo", "sitio", "ip"]].copy() if not data.devices.empty else \
            pd.DataFrame(columns=["device_id", "equipo", "tipo", "sitio", "ip"])
        tables["dim_dispositivo"] = dev

        days = pd.date_range(data.filter.start.date(), data.filter.end.date(), freq="D")
        tables["dim_fecha"] = pd.DataFrame({
            "fecha": days.date,
            "anio": days.year,
            "mes": days.month,
            "mes_nombre": [MONTHS[m - 1] for m in days.month],
            "dia": days.day,
            "dia_semana": [DAYS[d] for d in days.dayofweek],
            "dia_semana_nro": days.dayofweek + 1,
            "semana_iso": days.isocalendar().week.values,
        })

        hourly = data.hourly.copy()
        if not hourly.empty:
            hourly.insert(1, "fecha", hourly["fecha_hora"].dt.date)
            hourly.insert(2, "hora", hourly["fecha_hora"].dt.hour)
            hourly = hourly.drop(columns=["equipo", "tipo", "sitio"])
        tables["fact_mediciones_hora"] = hourly

        # Detalle crudo sólo si es manejable; para períodos largos alcanza con la tabla horaria.
        if not checks.empty and len(checks) <= RAW_LIMIT:
            raw = pd.DataFrame({
                "fecha_hora": checks["ts"],
                "fecha": checks["ts"].dt.date,
                "hora": checks["ts"].dt.hour,
                "device_id": checks["device_id"],
                "estado": checks["status"].map(status_label),
                "monitoreado": (~checks["status"].isin([Status.AVAILABLE.value, Status.UNKNOWN.value])).astype(int),
                "disponible": checks["status"].isin([Status.HEALTHY.value, Status.WARNING.value]).astype(int),
                "latencia_ms": checks["latency_ms"],
                "jitter_ms": checks["jitter_ms"],
                "perdida_pct": checks["loss_pct"],
                "saltos": checks["hops"],
            })
            tables["fact_mediciones"] = raw[raw["monitoreado"] == 1].drop(columns=["monitoreado"])

        inc = data.incidents
        tables["fact_incidentes"] = pd.DataFrame({
            "incidente_id": inc.get("id", pd.Series(dtype=int)),
            "device_id": inc.get("device_id", pd.Series(dtype=str)),
            "severidad": inc.get("status", pd.Series(dtype=str)).map(status_label),
            "inicio": inc.get("started_at", pd.Series(dtype="datetime64[ns]")),
            "fin": inc.get("ended_at", pd.Series(dtype="datetime64[ns]")),
            "fecha_inicio": pd.to_datetime(inc.get("started_at", pd.Series(dtype="datetime64[ns]"))).dt.date,
            "duracion_min": inc.get("duration_min", pd.Series(dtype=float)),
            "duracion_s": inc.get("duration_s", pd.Series(dtype=float)),
            "ultimo_ok": inc.get("last_ok_at", pd.Series(dtype="datetime64[ns]")),
            "abierto": inc.get("is_open", pd.Series(dtype=bool)).astype(int),
            "detalle": inc.get("message", pd.Series(dtype=str)),
        })

        tr = data.traceroutes
        tables["fact_traceroute"] = pd.DataFrame({
            "fecha_hora": tr.get("ts", pd.Series(dtype="datetime64[ns]")),
            "fecha": pd.to_datetime(tr.get("ts", pd.Series(dtype="datetime64[ns]"))).dt.date,
            "device_id": tr.get("device_id", pd.Series(dtype=str)),
            "ip": tr.get("ip", pd.Series(dtype=str)),
            "llega_destino": tr.get("reached", pd.Series(dtype=int)),
            "saltos": tr.get("hop_count", pd.Series(dtype=int)),
            "rtt_prom_ms": tr.get("avg_rtt_ms", pd.Series(dtype=float)),
        })

        tables["auditoria_fallas"] = data.audit
        tables["recomendaciones"] = pd.DataFrame([
            {"nivel": LEVEL_LABEL[i.level], "hallazgo": i.title, "detalle": i.detail, "recomendacion": i.recommendation}
            for i in data.insights
        ])
        tables["kpis"] = pd.DataFrame(kpi_rows(data.kpis), columns=["indicador", "valor"])
        return tables

    @staticmethod
    def _csv(df: pd.DataFrame) -> bytes:
        return df.to_csv(index=False, date_format="%Y-%m-%d %H:%M:%S").encode("utf-8-sig")

    def export(self, data: ReportDataset) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, df in self.tables(data).items():
                zf.writestr(f"{name}.csv", self._csv(df))
            zf.writestr("LEEME_PowerBI.md", GUIDE)
        return buf.getvalue()

    def export_folder(self, data: ReportDataset, folder: Path) -> Path:
        """Carpeta fija (reports/powerbi/latest) para que Power BI sólo tenga que 'Actualizar'."""
        folder.mkdir(parents=True, exist_ok=True)
        for name, df in self.tables(data).items():
            (folder / f"{name}.csv").write_bytes(self._csv(df))
        (folder / "LEEME_PowerBI.md").write_text(GUIDE, encoding="utf-8")
        return folder
