"""Contrato del inventario de dispositivos (patrón Repository).

Dos implementaciones intercambiables (LSP): JsonDeviceRepository (archivos por sector)
y SqliteInventoryRepository (tabla en la base). El resto de la app sólo conoce esta interfaz.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from nemesis.domain.device_mapper import DeviceMappingError, to_device
from nemesis.domain.device_types import TypeCatalog
from nemesis.domain.models import Device, normalize
from nemesis.domain.record_normalizer import match_keys

Record = dict[str, Any]
ORIGIN = "_origen"      # archivo (json) o "db" de donde viene el registro
ConflictPolicy = Literal["update", "skip", "duplicate"]


@dataclass(frozen=True)
class LoadError:
    file: str
    message: str


@dataclass
class ImportAction:
    action: str          # nuevo | actualiza | omite
    record: Record
    destination: str
    reason: str = ""


@dataclass
class ImportResult:
    actions: list[ImportAction] = field(default_factory=list)
    applied: bool = False
    backups: list[str] = field(default_factory=list)

    def count(self, action: str) -> int:
        return sum(1 for a in self.actions if a.action == action)

    @property
    def by_type(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for a in self.actions:
            out[a.record.get("Type", "?")][a.action] += 1
        return {k: dict(v) for k, v in out.items()}


def clean(record: Record) -> Record:
    return {k: v for k, v in record.items() if not str(k).startswith("_")}


class InventoryRepository(ABC):
    backend: str = ""

    def __init__(self, catalog: TypeCatalog):
        self.catalog = catalog

    # ---- primitivas que implementa cada backend
    @abstractmethod
    def records(self) -> tuple[list[Record], list[LoadError]]:
        """Todos los registros, con metadato ORIGIN."""

    @abstractmethod
    def replace_all(self, records: Sequence[Record]) -> list[str]:
        """Reemplaza el inventario completo. Devuelve backups generados."""

    @abstractmethod
    def describe(self) -> str:
        ...

    @abstractmethod
    def destination_for(self, record: Record, current: Sequence[Record]) -> str:
        """Dónde quedaría guardado un registro nuevo (archivo del sector o 'base de datos')."""

    # ---- operaciones comunes (Template Method sobre las primitivas)
    def get_all(self) -> tuple[list[Device], list[LoadError]]:
        recs, errors = self.records()
        devices: list[Device] = []
        for idx, rec in enumerate(recs, start=1):
            try:
                devices.append(to_device(clean(rec), source_file=str(rec.get(ORIGIN, ""))))
            except DeviceMappingError as exc:
                errors.append(LoadError(str(rec.get(ORIGIN, "")), f"Registro {idx}: {exc}"))
        return devices, errors

    def read_all_raw(self) -> tuple[dict[str, list[Record]], list[LoadError]]:
        """Agrupado por origen (para el validador de calidad de datos)."""
        recs, errors = self.records()
        groups: dict[str, list[Record]] = defaultdict(list)
        for r in recs:
            groups[str(r.get(ORIGIN) or self.backend)].append(clean(r))
        return dict(groups), errors

    def types_in_use(self) -> list[str]:
        recs, _ = self.records()
        return sorted({str(r.get("Type")) for r in recs if r.get("Type")})

    def plan_import(self, incoming: Sequence[Record], on_conflict: ConflictPolicy = "update") -> tuple[ImportResult, list[Record]]:
        """Calcula qué pasaría al importar (sin escribir). Devuelve el resultado y el inventario final."""
        current, _ = self.records()
        final = [dict(r) for r in current]
        index: dict[tuple, int] = {}
        for i, r in enumerate(final):
            for k in match_keys(r):
                index.setdefault(k, i)
        result = ImportResult()
        for rec in incoming:
            rec = {k: v for k, v in rec.items() if k != ORIGIN}
            hit = next((index[k] for k in match_keys(rec) if k in index), None)
            if hit is not None and on_conflict != "duplicate":
                dest = str(final[hit].get(ORIGIN, ""))
                if on_conflict == "skip":
                    result.actions.append(ImportAction("omite", rec, dest, "ya existe"))
                    continue
                before = clean(final[hit])
                merged = {**before, **rec, ORIGIN: final[hit].get(ORIGIN)}
                changed = clean(merged) != before
                final[hit] = merged
                result.actions.append(ImportAction("actualiza" if changed else "omite", rec, dest,
                                                   "datos actualizados" if changed else "sin cambios"))
                continue
            dest = self.destination_for(rec, final)
            final.append({**rec, ORIGIN: dest})
            for k in match_keys(rec):
                index.setdefault(k, len(final) - 1)
            result.actions.append(ImportAction("nuevo", rec, dest))
        return result, final

    def import_records(self, incoming: Sequence[Record], on_conflict: ConflictPolicy = "update",
                       dry_run: bool = False) -> ImportResult:
        result, final = self.plan_import(incoming, on_conflict)
        if not dry_run and (result.count("nuevo") or result.count("actualiza")):
            result.backups = self.replace_all(final)
            result.applied = True
        return result

    def add(self, record: Record) -> str:
        current, _ = self.records()
        dest = self.destination_for(record, current)
        self.replace_all(current + [{**record, ORIGIN: dest}])
        return dest

    def find_ip(self, ip: str) -> list[Record]:
        recs, _ = self.records()
        return [r for r in recs if any(str(v).strip() == ip for k, v in r.items() if str(k).startswith("IPAddress"))]

    @staticmethod
    def same_type(a: Any, b: Any) -> bool:
        return normalize(a) == normalize(b)
