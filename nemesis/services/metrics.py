"""Cálculo de KPIs, estadísticas y series para dashboard y reportes."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Sequence

import numpy as np
import pandas as pd

from nemesis.domain.enums import Status
from nemesis.infrastructure.repositories import SqliteStore

NOT_MONITORED = (Status.AVAILABLE.value, Status.UNKNOWN.value)
UP_STATES = (Status.HEALTHY.value, Status.WARNING.value)


@dataclass(frozen=True)
class ReportFilter:
    start: datetime
    end: datetime
    sites: tuple[str, ...] = ()
    types: tuple[str, ...] = ()

    @classmethod
    def last(cls, hours: float = 24, sites: Sequence[str] = (), types: Sequence[str] = ()) -> "ReportFilter":
        end = datetime.now().replace(microsecond=0)
        return cls(end - timedelta(hours=hours), end, tuple(sites), tuple(types))

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600

    @property
    def label(self) -> str:
        return f"{self.start:%d/%m/%Y %H:%M} – {self.end:%d/%m/%Y %H:%M}"

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        if self.sites:
            df = df[df["site"].isin(self.sites)]
        if self.types:
            df = df[df["type"].isin(self.types)]
        return df


@dataclass
class Kpis:
    devices_total: int = 0
    devices_monitored: int = 0
    up_now: int = 0
    degraded_now: int = 0
    down_now: int = 0
    reserved_now: int = 0
    availability_pct: Optional[float] = None
    devices_with_failures: int = 0
    latency_avg_ms: Optional[float] = None
    latency_p95_ms: Optional[float] = None
    jitter_avg_ms: Optional[float] = None
    loss_avg_pct: Optional[float] = None
    hops_avg: Optional[float] = None
    incidents_total: int = 0
    incidents_open: int = 0
    mttr_min: Optional[float] = None
    mtbf_h: Optional[float] = None
    downtime_min: float = 0.0
    checks_total: int = 0
    cycle_avg_s: Optional[float] = None
    last_check: Optional[datetime] = None
    period_label: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def health_score(self) -> Optional[float]:
        """Índice 0-100 para la vista ejecutiva: disponibilidad + calidad (latencia/pérdida)."""
        if self.availability_pct is None:
            return None
        score = self.availability_pct
        if self.loss_avg_pct:
            score -= min(10, self.loss_avg_pct * 2)
        if self.devices_monitored:
            score -= 15 * (self.down_now / self.devices_monitored)
        return round(max(0.0, min(100.0, score)), 1)


def _round(df: pd.DataFrame, digits: int = 2) -> pd.DataFrame:
    numeric = df.select_dtypes("number").columns
    return df.round({c: digits for c in numeric})


def _r(value, digits: int = 2) -> Optional[float]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return round(float(value), digits)


class MetricsService:
    CACHE_TTL_S = 20

    def __init__(self, store: SqliteStore):
        self._store = store
        self._cache: dict[tuple, tuple[float, pd.DataFrame]] = {}
        self._cache_lock = threading.Lock()

    def _cached_checks(self, start: datetime, end: datetime) -> pd.DataFrame:
        """Evita releer la misma ventana varias veces al armar un dashboard o reporte."""
        key = (start, end)
        now = time.monotonic()
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < self.CACHE_TTL_S:
                return hit[1]
        df = self._store.checks(start, end)
        # La pérdida se mide sólo cuando el equipo responde (la caída ya se refleja en disponibilidad).
        df["loss_pct"] = df["loss_pct"].where(df["online"] == 1)
        with self._cache_lock:
            self._cache = {k: v for k, v in self._cache.items() if now - v[0] < self.CACHE_TTL_S}
            self._cache[key] = (now, df)
        return df

    # ------------------------------------------------------------ datos base
    def checks(self, f: ReportFilter) -> pd.DataFrame:
        return f.apply(self._cached_checks(f.start, f.end))

    def monitored_checks(self, f: ReportFilter) -> pd.DataFrame:
        df = self.checks(f)
        return df[~df["status"].isin(NOT_MONITORED)] if not df.empty else df

    def current_status(self, f: ReportFilter | None = None) -> pd.DataFrame:
        df = self._store.latest_checks()
        return f.apply(df) if f else df

    def incidents(self, f: ReportFilter) -> pd.DataFrame:
        df = f.apply(self._store.incidents(f.start, f.end))
        if df.empty:
            return df.assign(duration_min=pd.Series(dtype=float), duration_s=pd.Series(dtype=float),
                             is_open=pd.Series(dtype=bool))
        now = pd.Timestamp(datetime.now())
        start = df["started_at"].clip(lower=f.start)
        end = df["ended_at"].fillna(now).clip(upper=f.end)
        df = df.assign(
            is_open=df["ended_at"].isna(),
            # duración dentro del período (para métricas) y duración real completa (para auditoría)
            duration_min=((end - start).dt.total_seconds() / 60).clip(lower=0).round(1),
            duration_s=(df["ended_at"].fillna(now) - df["started_at"]).dt.total_seconds().clip(lower=0).round(0),
        )
        return df

    def audit_log(self, f: ReportFilter) -> pd.DataFrame:
        """Registro de auditoría de fallas: una fila por evento, con fecha y hora exactas."""
        from nemesis.domain.models import format_duration
        inc = self.incidents(f)
        cols = ["N°", "Equipo", "Tipo", "Sitio", "Severidad", "Último OK", "Fecha caída", "Hora caída",
                "Fecha recuperación", "Hora recuperación", "Duración", "Duración (s)", "Estado", "Detalle"]
        if inc.empty:
            return pd.DataFrame(columns=cols)
        inc = inc.sort_values("started_at", ascending=False)
        labels = {Status.CRITICAL.value: "Caída", Status.WARNING.value: "Degradación"}

        def d(ts):  # fecha
            return "" if pd.isna(ts) else ts.strftime("%d/%m/%Y")

        def h(ts):  # hora con segundos
            return "" if pd.isna(ts) else ts.strftime("%H:%M:%S")

        rows = []
        for r in inc.itertuples():
            last_ok = getattr(r, "last_ok_at", None)
            rows.append({
                "N°": int(r.id),
                "Equipo": r.device_name, "Tipo": r.type, "Sitio": r.site,
                "Severidad": labels.get(r.status, r.status),
                "Último OK": "" if last_ok is None or pd.isna(last_ok) else last_ok.strftime("%d/%m/%Y %H:%M:%S"),
                "Fecha caída": d(r.started_at), "Hora caída": h(r.started_at),
                "Fecha recuperación": d(r.ended_at) if not r.is_open else "",
                "Hora recuperación": h(r.ended_at) if not r.is_open else "",
                "Duración": format_duration(r.duration_s) + (" (en curso)" if r.is_open else ""),
                "Duración (s)": int(r.duration_s),
                "Estado": "Sin recuperar" if r.is_open else "Recuperado",
                "Detalle": r.message or "",
            })
        return pd.DataFrame(rows, columns=cols)

    def audit_summary(self, f: ReportFilter) -> pd.DataFrame:
        """Totales por equipo para auditoría: cantidad de fallas y tiempo total con falla."""
        from nemesis.domain.models import format_duration
        inc = self.incidents(f)
        if inc.empty:
            return pd.DataFrame(columns=["Equipo", "Tipo", "Sitio", "Fallas", "Caídas", "Tiempo total con falla",
                                         "Falla más larga", "Primera falla", "Última falla", "Segundos"])
        inc = inc.assign(is_down=inc["status"] == Status.CRITICAL.value)
        g = inc.groupby(["device_id", "device_name", "type", "site"]).agg(
            fallas=("id", "count"), caidas=("is_down", "sum"), total_s=("duration_s", "sum"),
            max_s=("duration_s", "max"), primera=("started_at", "min"), ultima=("started_at", "max"),
        ).reset_index().sort_values("total_s", ascending=False)
        return pd.DataFrame({
            "Equipo": g["device_name"], "Tipo": g["type"], "Sitio": g["site"],
            "Fallas": g["fallas"].astype(int), "Caídas": g["caidas"].astype(int),
            "Tiempo total con falla": g["total_s"].map(format_duration),
            "Falla más larga": g["max_s"].map(format_duration),
            "Primera falla": g["primera"].dt.strftime("%d/%m/%Y %H:%M:%S"),
            "Última falla": g["ultima"].dt.strftime("%d/%m/%Y %H:%M:%S"),
            "Segundos": g["total_s"].astype(int),
        })

    def traceroutes(self, f: ReportFilter, device_id: str | None = None) -> pd.DataFrame:
        return self._store.traceroutes(f.start, f.end, device_id)

    # ------------------------------------------------------------------ KPIs
    def kpis(self, f: ReportFilter) -> Kpis:
        k = Kpis(period_label=f.label)
        current = self.current_status(f)
        if not current.empty:
            k.devices_total = len(current)
            k.up_now = int((current["status"] == Status.HEALTHY.value).sum())
            k.degraded_now = int((current["status"] == Status.WARNING.value).sum())
            k.down_now = int((current["status"] == Status.CRITICAL.value).sum())
            k.reserved_now = int(current["status"].isin(NOT_MONITORED).sum())
            k.devices_monitored = k.devices_total - k.reserved_now
            k.last_check = current["ts"].max().to_pydatetime()

        df = self.monitored_checks(f)
        if not df.empty:
            k.checks_total = len(df)
            k.availability_pct = _r(100 * df["status"].isin(UP_STATES).mean(), 3)
            lat = df["latency_ms"].dropna()
            k.latency_avg_ms = _r(lat.mean()) if not lat.empty else None
            k.latency_p95_ms = _r(lat.quantile(0.95)) if not lat.empty else None
            k.jitter_avg_ms = _r(df["jitter_ms"].dropna().mean())
            k.loss_avg_pct = _r(df["loss_pct"].dropna().mean())
            k.hops_avg = _r(df["hops"].dropna().mean(), 1)

        inc = self.incidents(f)
        if not inc.empty:
            k.incidents_total = len(inc)
            k.incidents_open = int(inc["is_open"].sum())
            k.devices_with_failures = int(inc["device_id"].nunique())
            closed = inc[~inc["is_open"]]
            k.mttr_min = _r(closed["duration_min"].mean(), 1) if not closed.empty else None
            k.downtime_min = _r(inc["duration_min"].sum(), 1) or 0.0
            if k.devices_monitored:
                device_hours = k.devices_monitored * f.hours
                k.mtbf_h = _r(device_hours / len(inc), 1)

        cycles = self._store.cycles(f.start, f.end)
        if not cycles.empty:
            k.cycle_avg_s = _r(cycles["duration_s"].mean(), 1)
        return k

    # --------------------------------------------------------- agrupaciones
    def by_group(self, f: ReportFilter, column: str) -> pd.DataFrame:
        df = self.monitored_checks(f)
        if df.empty:
            return pd.DataFrame(columns=[column, "equipos", "disponibilidad_pct", "latencia_prom_ms",
                                         "latencia_p95_ms", "perdida_prom_pct", "incidentes", "downtime_min"])
        df = df.assign(up=df["status"].isin(UP_STATES).astype(float))
        g = df.groupby(column)
        grouped = g.agg(
            equipos=("device_id", "nunique"),
            mediciones=("id", "count"),
            disponibilidad_pct=("up", "mean"),
            latencia_prom_ms=("latency_ms", "mean"),
            perdida_prom_pct=("loss_pct", "mean"),
        )
        grouped["disponibilidad_pct"] = (grouped["disponibilidad_pct"] * 100).round(3)
        grouped["latencia_p95_ms"] = g["latency_ms"].quantile(0.95)
        grouped = grouped.reset_index()
        inc = self.incidents(f)
        if not inc.empty:
            inc_g = inc.groupby(column).agg(incidentes=("id", "count"), downtime_min=("duration_min", "sum")).reset_index()
            grouped = grouped.merge(inc_g, on=column, how="left")
        else:
            grouped["incidentes"], grouped["downtime_min"] = 0, 0.0
        grouped[["incidentes", "downtime_min"]] = grouped[["incidentes", "downtime_min"]].fillna(0)
        grouped["incidentes"] = grouped["incidentes"].astype(int)
        return _round(grouped).sort_values("disponibilidad_pct")

    def device_metrics(self, f: ReportFilter) -> pd.DataFrame:
        df = self.checks(f)
        cols = ["device_id", "equipo", "tipo", "sitio", "ip", "estado_actual", "mediciones", "disponibilidad_pct",
                "latencia_prom_ms", "latencia_p95_ms", "latencia_max_ms", "jitter_prom_ms", "perdida_prom_pct",
                "saltos", "incidentes", "downtime_min", "mttr_min"]
        if df.empty:
            return pd.DataFrame(columns=cols)
        monitored = df[~df["status"].isin(NOT_MONITORED)]
        monitored = monitored.assign(up=monitored["status"].isin(UP_STATES).astype(float))
        g = monitored.groupby("device_id")
        agg = g.agg(
            mediciones=("id", "count"),
            disponibilidad_pct=("up", "mean"),
            latencia_prom_ms=("latency_ms", "mean"),
            latencia_max_ms=("latency_ms", "max"),
            jitter_prom_ms=("jitter_ms", "mean"),
            perdida_prom_pct=("loss_pct", "mean"),
            saltos=("hops", "median"),
        )
        agg["disponibilidad_pct"] = (agg["disponibilidad_pct"] * 100).round(3)
        agg["latencia_p95_ms"] = g["latency_ms"].quantile(0.95)
        last = df.sort_values("ts").groupby("device_id").last()
        info = last[["device_name", "type", "site", "ip", "status"]].rename(
            columns={"device_name": "equipo", "type": "tipo", "site": "sitio", "status": "estado_actual"}
        )
        out = info.join(agg, how="left")

        inc = self.incidents(f)
        if not inc.empty:
            closed = inc[~inc["is_open"]]
            inc_g = inc.groupby("device_id").agg(incidentes=("id", "count"), downtime_min=("duration_min", "sum"))
            mttr = closed.groupby("device_id")["duration_min"].mean().rename("mttr_min")
            out = out.join(inc_g, how="left").join(mttr, how="left")
        else:
            out["incidentes"], out["downtime_min"], out["mttr_min"] = 0, 0.0, np.nan
        out["incidentes"] = out["incidentes"].fillna(0).astype(int)
        out["downtime_min"] = out["downtime_min"].fillna(0)

        trace = self._store.traceroutes(f.start, f.end)
        if not trace.empty:
            last_trace = trace.sort_values("ts").groupby("device_id")["hop_count"].last()
            out["saltos"] = last_trace.reindex(out.index).fillna(out["saltos"])
        out = out.reset_index()
        return _round(out[cols]).sort_values(["disponibilidad_pct", "latencia_p95_ms"], ascending=[True, False])

    # ---------------------------------------------------------------- series
    @staticmethod
    def _freq(f: ReportFilter) -> str:
        h = f.hours
        return "5min" if h <= 6 else "15min" if h <= 48 else "1h" if h <= 24 * 8 else "6h"

    def availability_series(self, f: ReportFilter, by: str | None = None) -> pd.DataFrame:
        df = self.monitored_checks(f)
        if df.empty:
            return pd.DataFrame(columns=["ts", "disponibilidad_pct"])
        df = df.assign(up=df["status"].isin(UP_STATES).astype(float))
        keys = [pd.Grouper(key="ts", freq=self._freq(f))] + ([by] if by else [])
        s = df.groupby(keys)["up"].mean().mul(100).round(2).rename("disponibilidad_pct").reset_index()
        return s.dropna()

    def latency_series(self, f: ReportFilter, by: str | None = "type") -> pd.DataFrame:
        df = self.monitored_checks(f).dropna(subset=["latency_ms"])
        if df.empty:
            return pd.DataFrame(columns=["ts", "latencia_prom_ms", "latencia_p95_ms"])
        keys = [pd.Grouper(key="ts", freq=self._freq(f))] + ([by] if by else [])
        g = df.groupby(keys)["latency_ms"]
        out = pd.DataFrame({"latencia_prom_ms": g.mean(), "latencia_p95_ms": g.quantile(0.95)}).round(2)
        return out.reset_index().dropna()

    def hourly_by_device(self, f: ReportFilter) -> pd.DataFrame:
        """Mediciones agregadas por equipo y hora: liviano para Excel y Power BI."""
        df = self.monitored_checks(f)
        cols = ["fecha_hora", "device_id", "equipo", "tipo", "sitio", "mediciones", "disponibles",
                "disponibilidad_pct", "latencia_prom_ms", "latencia_p95_ms", "latencia_max_ms",
                "jitter_prom_ms", "perdida_prom_pct", "saltos"]
        if df.empty:
            return pd.DataFrame(columns=cols)
        df = df.assign(up=df["status"].isin(UP_STATES).astype(int), fecha_hora=df["ts"].dt.floor("h"))
        g = df.groupby(["fecha_hora", "device_id"])
        out = g.agg(
            equipo=("device_name", "last"), tipo=("type", "last"), sitio=("site", "last"),
            mediciones=("id", "count"), disponibles=("up", "sum"),
            latencia_prom_ms=("latency_ms", "mean"),
            latencia_max_ms=("latency_ms", "max"),
            jitter_prom_ms=("jitter_ms", "mean"),
            perdida_prom_pct=("loss_pct", "mean"),
            saltos=("hops", "median"),
        )
        out["latencia_p95_ms"] = g["latency_ms"].quantile(0.95)
        out = out.reset_index()
        out["disponibilidad_pct"] = (100 * out["disponibles"] / out["mediciones"]).round(2)
        return _round(out[cols])

    def failure_heatmap(self, f: ReportFilter) -> pd.DataFrame:
        """% de mediciones con falla por día de semana × hora (para detectar patrones)."""
        df = self.monitored_checks(f)
        if df.empty:
            return pd.DataFrame()
        df = df.assign(fail=(df["status"] == Status.CRITICAL.value).astype(float),
                       dia=df["ts"].dt.dayofweek, hora=df["ts"].dt.hour)
        pivot = df.pivot_table(index="dia", columns="hora", values="fail", aggfunc="mean").mul(100).round(2)
        pivot.index = [["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"][i] for i in pivot.index]
        return pivot

    def hops_summary(self, f: ReportFilter) -> pd.DataFrame:
        """Saltos por equipo: real (traceroute) vs estimado (TTL) y estabilidad de la ruta."""
        checks = self.monitored_checks(f)
        trace = self._store.traceroutes(f.start, f.end)
        cols = ["device_id", "equipo", "tipo", "sitio", "saltos_estimados_ttl", "saltos_traceroute",
                "rutas_distintas", "llega_destino", "rtt_ruta_ms", "ultimo_traceroute"]
        if checks.empty and trace.empty:
            return pd.DataFrame(columns=cols)
        base = checks.sort_values("ts").groupby("device_id").agg(
            equipo=("device_name", "last"), tipo=("type", "last"), sitio=("site", "last"),
            saltos_estimados_ttl=("hops", "median"))
        if not trace.empty:
            t = trace.sort_values("ts").groupby("device_id").agg(
                saltos_traceroute=("hop_count", "last"),
                rutas_distintas=("path_json", lambda s: s.map(_path_signature).nunique()),
                llega_destino=("reached", "last"),
                rtt_ruta_ms=("avg_rtt_ms", "last"),
                ultimo_traceroute=("ts", "last"),
            )
            base = base.join(t, how="left")
        for c in cols[1:]:
            if c not in base.columns:
                base[c] = np.nan
        base = base.reset_index()
        return base[cols]


def _path_signature(path_json: str) -> str:
    import json
    try:
        return "-".join(str(h.get("ip")) for h in json.loads(path_json))
    except (TypeError, ValueError):
        return ""
