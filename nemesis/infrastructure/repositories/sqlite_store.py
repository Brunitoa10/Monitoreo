"""Persistencia del histórico en SQLite.

- Lado escritura: recibe objetos de dominio (HealthResult, Incident, TracerouteResult).
- Lado lectura: devuelve DataFrames listos para métricas y reportes (CQRS liviano).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional, Sequence

import pandas as pd

from nemesis.domain.enums import Status
from nemesis.domain.models import HealthResult, Incident, TracerouteResult

TS_FORMAT = "%Y-%m-%d %H:%M:%S"

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    device_id   TEXT NOT NULL,
    device_name TEXT NOT NULL,
    site        TEXT,
    type        TEXT,
    ip          TEXT,
    status      TEXT NOT NULL,
    online      INTEGER NOT NULL,
    latency_ms  REAL,
    jitter_ms   REAL,
    loss_pct    REAL,
    hops        INTEGER,
    message     TEXT
);
CREATE INDEX IF NOT EXISTS ix_checks_ts ON checks(ts);
CREATE INDEX IF NOT EXISTS ix_checks_device_ts ON checks(device_id, ts);

CREATE TABLE IF NOT EXISTS probes (
    check_id   INTEGER NOT NULL REFERENCES checks(id) ON DELETE CASCADE,
    role       TEXT,
    ip         TEXT,
    method     TEXT,
    online     INTEGER,
    rtt_avg_ms REAL,
    rtt_min_ms REAL,
    rtt_max_ms REAL,
    jitter_ms  REAL,
    loss_pct   REAL,
    ttl        INTEGER,
    hops       INTEGER
);
CREATE INDEX IF NOT EXISTS ix_probes_check ON probes(check_id);

CREATE TABLE IF NOT EXISTS incidents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   TEXT NOT NULL,
    device_name TEXT,
    site        TEXT,
    type        TEXT,
    status      TEXT,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    message     TEXT
);
CREATE INDEX IF NOT EXISTS ix_incidents_device ON incidents(device_id, ended_at);

CREATE TABLE IF NOT EXISTS traceroutes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    device_id   TEXT NOT NULL,
    device_name TEXT,
    ip          TEXT,
    reached     INTEGER,
    hop_count   INTEGER,
    avg_rtt_ms  REAL,
    path_json   TEXT
);
CREATE INDEX IF NOT EXISTS ix_traceroutes_device_ts ON traceroutes(device_id, ts);

CREATE TABLE IF NOT EXISTS cycles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    duration_s  REAL,
    devices     INTEGER,
    errors      INTEGER
);

CREATE TABLE IF NOT EXISTS leases (
    name      TEXT PRIMARY KEY,
    owner     TEXT NOT NULL,
    heartbeat TEXT NOT NULL
);
"""


def fmt(ts: datetime) -> str:
    return ts.strftime(TS_FORMAT)


def parse(ts: Optional[str]) -> Optional[datetime]:
    return datetime.strptime(ts, TS_FORMAT) if ts else None


class SqliteStore:
    def __init__(self, db_path: Path):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(SCHEMA)
            self._migrate(con)

    @staticmethod
    def _migrate(con: sqlite3.Connection) -> None:
        """Migraciones simples de esquema (bases creadas por versiones anteriores)."""
        cols = {r[1] for r in con.execute("PRAGMA table_info(incidents)")}
        if "last_ok_at" not in cols:
            con.execute("ALTER TABLE incidents ADD COLUMN last_ok_at TEXT")

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self._path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    # ================================================================ escritura
    def save_cycle(self, results: Sequence[HealthResult], duration_s: float, errors: int) -> None:
        if not results:
            return
        with self._connect() as con:
            for r in results:
                cur = con.execute(
                    """INSERT INTO checks (ts, device_id, device_name, site, type, ip, status, online,
                                           latency_ms, jitter_ms, loss_pct, hops, message)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (fmt(r.timestamp), r.device.id, r.device.name, r.device.site, r.device.type,
                     r.device.ip_display, r.status.value, int(r.online), r.latency_ms, r.jitter_ms,
                     r.loss_pct, r.hops, r.message),
                )
                con.executemany(
                    """INSERT INTO probes (check_id, role, ip, method, online, rtt_avg_ms, rtt_min_ms,
                                           rtt_max_ms, jitter_ms, loss_pct, ttl, hops)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [(cur.lastrowid, p.role, p.ip, p.method, int(p.online), p.rtt_avg_ms, p.rtt_min_ms,
                      p.rtt_max_ms, p.jitter_ms, p.loss_pct, p.ttl, p.hops) for p in r.probes],
                )
            con.execute(
                "INSERT INTO cycles (ts, duration_s, devices, errors) VALUES (?,?,?,?)",
                (fmt(results[0].timestamp), round(duration_s, 2), len(results), errors),
            )

    def open_incident(self, incident: Incident) -> int:
        with self._connect() as con:
            cur = con.execute(
                """INSERT INTO incidents (device_id, device_name, site, type, status, started_at, message, last_ok_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (incident.device_id, incident.device_name, incident.site, incident.type,
                 incident.status.value, fmt(incident.started_at), incident.message,
                 fmt(incident.last_ok_at) if incident.last_ok_at else None),
            )
            return int(cur.lastrowid)

    def escalate_incident(self, incident_id: int, status: Status, message: str) -> None:
        with self._connect() as con:
            con.execute("UPDATE incidents SET status=?, message=? WHERE id=?", (status.value, message, incident_id))

    def close_incident(self, incident_id: int, ended_at: datetime) -> None:
        with self._connect() as con:
            con.execute("UPDATE incidents SET ended_at=? WHERE id=?", (fmt(ended_at), incident_id))

    def open_incidents(self) -> list[Incident]:
        with self._connect() as con:
            rows = con.execute("SELECT * FROM incidents WHERE ended_at IS NULL").fetchall()
        return [
            Incident(
                device_id=r["device_id"], device_name=r["device_name"], site=r["site"], type=r["type"],
                status=Status(r["status"]), started_at=parse(r["started_at"]), message=r["message"] or "",
                id=r["id"], last_ok_at=parse(r["last_ok_at"]) if "last_ok_at" in r.keys() else None,
            )
            for r in rows
        ]

    def save_traceroute(self, result: TracerouteResult) -> None:
        path = [{"hop": h.number, "ip": h.ip, "rtt_ms": h.rtt_ms} for h in result.hops]
        with self._connect() as con:
            con.execute(
                """INSERT INTO traceroutes (ts, device_id, device_name, ip, reached, hop_count, avg_rtt_ms, path_json)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (fmt(result.timestamp), result.device_id, result.device_name, result.ip,
                 int(result.reached), result.hop_count, result.avg_rtt_ms, json.dumps(path)),
            )

    def try_acquire_lease(self, name: str, owner: str, ttl_seconds: int) -> bool:
        """Evita que dos colectores (dashboard + servicio) midan a la vez."""
        now = datetime.now()
        expired = fmt(now - timedelta(seconds=ttl_seconds))
        with self._connect() as con:
            con.execute(
                """INSERT INTO leases (name, owner, heartbeat) VALUES (?,?,?)
                   ON CONFLICT(name) DO UPDATE SET owner=excluded.owner, heartbeat=excluded.heartbeat
                   WHERE leases.owner = excluded.owner OR leases.heartbeat < ?""",
                (name, owner, fmt(now), expired),
            )
            row = con.execute("SELECT owner FROM leases WHERE name=?", (name,)).fetchone()
        return bool(row and row["owner"] == owner)

    def release_lease(self, name: str, owner: str) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM leases WHERE name=? AND owner=?", (name, owner))

    def purge(self, older_than: datetime) -> int:
        cutoff = fmt(older_than)
        with self._connect() as con:
            n = con.execute("DELETE FROM checks WHERE ts < ?", (cutoff,)).rowcount
            con.execute("DELETE FROM probes WHERE check_id NOT IN (SELECT id FROM checks)")
            con.execute("DELETE FROM traceroutes WHERE ts < ?", (cutoff,))
            con.execute("DELETE FROM cycles WHERE ts < ?", (cutoff,))
            con.execute("DELETE FROM incidents WHERE ended_at IS NOT NULL AND ended_at < ?", (cutoff,))
        return n

    # ================================================================== lectura
    def _df(self, sql: str, params: Sequence = ()) -> pd.DataFrame:
        with self._connect() as con:
            df = pd.read_sql_query(sql, con, params=list(params))
        for col in ("latency_ms", "jitter_ms", "loss_pct", "hops", "rtt_avg_ms", "rtt_min_ms", "rtt_max_ms",
                    "avg_rtt_ms", "hop_count", "ttl"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        for col in ("ts", "started_at", "ended_at", "last_ok_at"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], format=TS_FORMAT, errors="coerce")
        return df

    def checks(self, start: datetime, end: datetime) -> pd.DataFrame:
        return self._df(
            "SELECT * FROM checks WHERE ts BETWEEN ? AND ? ORDER BY ts", (fmt(start), fmt(end))
        )

    def probes_for_device(self, device_id: str, start: datetime, end: datetime) -> pd.DataFrame:
        return self._df(
            """SELECT c.ts, p.* FROM probes p JOIN checks c ON c.id = p.check_id
               WHERE c.device_id = ? AND c.ts BETWEEN ? AND ? ORDER BY c.ts""",
            (device_id, fmt(start), fmt(end)),
        )

    def latest_checks(self) -> pd.DataFrame:
        """Último estado conocido de cada dispositivo."""
        return self._df(
            """SELECT c.* FROM checks c
               JOIN (SELECT device_id, MAX(id) AS max_id FROM checks GROUP BY device_id) last
                 ON last.max_id = c.id"""
        )

    def incidents(self, start: datetime, end: datetime) -> pd.DataFrame:
        """Incidentes que se solapan con el período (incluye los abiertos)."""
        return self._df(
            """SELECT * FROM incidents
               WHERE started_at <= ? AND (ended_at IS NULL OR ended_at >= ?)
               ORDER BY started_at DESC""",
            (fmt(end), fmt(start)),
        )

    def traceroutes(self, start: datetime, end: datetime, device_id: str | None = None) -> pd.DataFrame:
        sql = "SELECT * FROM traceroutes WHERE ts BETWEEN ? AND ?"
        params: list = [fmt(start), fmt(end)]
        if device_id:
            sql += " AND device_id = ?"
            params.append(device_id)
        return self._df(sql + " ORDER BY ts", params)

    def last_traceroute_ts(self) -> Optional[datetime]:
        with self._connect() as con:
            row = con.execute("SELECT MAX(ts) AS ts FROM traceroutes").fetchone()
        return parse(row["ts"]) if row and row["ts"] else None

    def cycles(self, start: datetime, end: datetime) -> pd.DataFrame:
        return self._df("SELECT * FROM cycles WHERE ts BETWEEN ? AND ? ORDER BY ts", (fmt(start), fmt(end)))

    def last_cycle(self) -> Optional[dict]:
        with self._connect() as con:
            row = con.execute("SELECT * FROM cycles ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        data = dict(row)
        data["ts"] = parse(data["ts"])
        return data

    def data_range(self) -> tuple[Optional[datetime], Optional[datetime]]:
        with self._connect() as con:
            row = con.execute("SELECT MIN(ts) AS a, MAX(ts) AS b FROM checks").fetchone()
        return parse(row["a"]), parse(row["b"])

    def stats(self) -> dict:
        with self._connect() as con:
            counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in ("checks", "probes", "incidents", "traceroutes", "cycles")}
        counts["size_mb"] = round(self._path.stat().st_size / 1_048_576, 2) if self._path.exists() else 0
        return counts
