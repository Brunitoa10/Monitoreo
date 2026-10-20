"""Inventario guardado en la base SQLite (tabla devices), alternativa a los JSON."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Sequence

from nemesis.domain.device_types import TypeCatalog
from nemesis.infrastructure.repositories.inventory import ORIGIN, InventoryRepository, LoadError, Record, clean

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    type       TEXT NOT NULL,
    name       TEXT NOT NULL,
    site       TEXT,
    ip         TEXT,
    data_json  TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_devices_type ON devices(type);
CREATE INDEX IF NOT EXISTS ix_devices_ip ON devices(ip);
CREATE TABLE IF NOT EXISTS devices_backup (
    batch      TEXT NOT NULL,
    data_json  TEXT NOT NULL
);
"""
DB_ORIGIN = "base de datos"


class SqliteInventoryRepository(InventoryRepository):
    backend = "sqlite"

    def __init__(self, db_path: Path, catalog: TypeCatalog | None = None):
        super().__init__(catalog or TypeCatalog())
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self._path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def describe(self) -> str:
        return f"Base de datos {self._path} (tabla devices)"

    def records(self) -> tuple[list[Record], list[LoadError]]:
        out: list[Record] = []
        errors: list[LoadError] = []
        with self._connect() as con:
            for row in con.execute("SELECT id, data_json FROM devices ORDER BY type, site, name"):
                try:
                    out.append({**json.loads(row["data_json"]), ORIGIN: DB_ORIGIN, "_id": row["id"]})
                except ValueError as exc:
                    errors.append(LoadError(DB_ORIGIN, f"Registro {row['id']} dañado: {exc}"))
        return out, errors

    def destination_for(self, record: Record, current: Sequence[Record]) -> str:
        return DB_ORIGIN

    def replace_all(self, records: Sequence[Record]) -> list[str]:
        """Reemplazo transaccional; el estado anterior queda en devices_backup (último lote)."""
        batch = datetime.now().strftime("%Y%m%d-%H%M%S")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as con:
            con.execute("DELETE FROM devices_backup WHERE batch NOT IN "
                        "(SELECT DISTINCT batch FROM devices_backup ORDER BY batch DESC LIMIT 9)")
            con.execute("INSERT INTO devices_backup (batch, data_json) SELECT ?, data_json FROM devices", (batch,))
            con.execute("DELETE FROM devices")
            for r in records:
                data = clean(r)
                ip = next((str(v) for k, v in data.items() if str(k).startswith("IPAddress") and v), "")
                con.execute(
                    "INSERT INTO devices (type, name, site, ip, data_json, updated_at) VALUES (?,?,?,?,?,?)",
                    (data.get("Type", ""), data.get("Name", ""), data.get("Site", ""), ip,
                     json.dumps(data, ensure_ascii=False), now),
                )
        return [f"devices_backup lote {batch}"]
