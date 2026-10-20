"""Casos de uso del panel de administración: inventario JSON y autenticación."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from nemesis.domain.device_mapper import IP_KEY, IP_ROLE_PREFIX, ordered_record
from nemesis.domain.device_types import TypeCatalog
from nemesis.domain.enums import IssueSeverity
from nemesis.domain.models import ValidationIssue
from nemesis.domain.record_normalizer import normalize_record, parse_json_bytes
from nemesis.domain.validation import DeviceValidator
from nemesis.infrastructure.repositories.inventory import (ORIGIN, ConflictPolicy, ImportResult, InventoryRepository,
                                                          Record, clean)

log = logging.getLogger(__name__)
FILE_NAME_RE = re.compile(r"^[\w\-. /]+\.json$")


@dataclass
class SaveResult:
    saved: bool
    issues: list[ValidationIssue]
    backups: list[str] = field(default_factory=list)
    destination: str = ""


@dataclass
class ImportPreview:
    result: ImportResult
    parsed: int
    warnings: list[str]
    issues: list[ValidationIssue]

    @property
    def blocking(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == IssueSeverity.ERROR]


def clean_records(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Quita celdas vacías/NaN y filas vacías que agrega el editor de tablas (conserva _origen)."""
    cleaned = []
    for rec in records:
        item: dict[str, Any] = {}
        for k, v in rec.items():
            if v is None or (isinstance(v, float) and v != v):
                continue
            text = str(v).strip()
            if text:
                item[str(k)] = text
        if any(k in item for k in ("Name", IP_KEY)) or any(k.startswith(IP_ROLE_PREFIX) for k in item):
            cleaned.append(item)
    return cleaned


class InventoryAdminService:
    """Casos de uso del inventario, independientes de dónde se guarde (JSON o base)."""

    def __init__(self, repo: InventoryRepository, validator: DeviceValidator, catalog: TypeCatalog):
        self._repo = repo
        self._validator = validator
        self.catalog = catalog

    @property
    def repo(self) -> InventoryRepository:
        return self._repo

    # ------------------------------------------------------------------ lectura
    def records(self) -> list[Record]:
        recs, _ = self._repo.records()
        self.catalog.extend(r.get("Type") for r in recs)
        return recs

    def sectors(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.records():
            counts[r.get("Type", "Otro")] = counts.get(r.get("Type", "Otro"), 0) + 1
        return dict(sorted(counts.items()))

    def validate_all(self, records: Sequence[Record] | None = None) -> list[ValidationIssue]:
        if records is None:
            groups, load_errors = self._repo.read_all_raw()
        else:
            groups, load_errors = {}, []
            for r in records:
                groups.setdefault(str(r.get(ORIGIN) or self._repo.backend), []).append(clean(r))
        issues = self._validator.validate(groups)
        issues += [ValidationIssue(IssueSeverity.ERROR, e.file, "*", "archivo", e.message) for e in load_errors]
        return issues

    # ---------------------------------------------------------------- escritura
    def _normalize(self, rows: Sequence[dict[str, Any]]) -> list[Record]:
        out = []
        for row in clean_records(rows):
            origin = row.pop(ORIGIN, None)
            row.pop("_id", None)
            rec = normalize_record(row, self.catalog).data
            if origin:
                rec[ORIGIN] = origin
            out.append(rec)
        return out

    def _route(self, records: list[Record]) -> list[Record]:
        """Asigna destino a los registros nuevos o a los que cambiaron de tipo (mueve de sector)."""
        routed: list[Record] = []
        for r in records:
            origin = r.get(ORIGIN)
            moved = origin and self._repo.backend == "json" and not self._origin_accepts(origin, r, records)
            if not origin or moved:
                r = {**r, ORIGIN: self._repo.destination_for(r, [x for x in records if x.get(ORIGIN) and x is not r])}
            routed.append(r)
        return routed

    def _origin_accepts(self, origin: str, record: Record, records: Sequence[Record]) -> bool:
        others = [x for x in records if x.get(ORIGIN) == origin and x is not record]
        return not others or any(self._repo.same_type(x.get("Type"), record.get("Type")) for x in others)

    def save_table(self, rows: Sequence[dict[str, Any]], force: bool = False) -> SaveResult:
        """Guarda la tabla completa editada en el panel (altas, bajas y modificaciones)."""
        records = self._route(self._normalize(rows))
        issues = self.validate_all(records)
        if DeviceValidator.has_errors(issues) and not force:
            return SaveResult(False, issues)
        return SaveResult(True, issues, self._repo.replace_all(records))

    def add_device(self, data: dict[str, Any], force: bool = False) -> SaveResult:
        """Alta manual: se normaliza, se valida contra todo el inventario y va al sector que corresponde."""
        rec = normalize_record(clean_records([data])[0] if clean_records([data]) else {}, self.catalog).data
        current = self.records()
        dest = self._repo.destination_for(rec, current)
        candidate = current + [{**rec, ORIGIN: dest}]
        issues = [i for i in self.validate_all(candidate) if rec.get("Name", "") in i.device or i.file == "*"]
        if DeviceValidator.has_errors(issues) and not force:
            return SaveResult(False, issues, destination=dest)
        backups = self._repo.replace_all(candidate)
        log.info("Alta manual: %s (%s) -> %s", rec.get("Name"), rec.get("Type"), dest)
        return SaveResult(True, issues, backups, dest)

    # --------------------------------------------------------------- importación
    def preview_import(self, files: Sequence[tuple[str, bytes]], on_conflict: ConflictPolicy = "update") -> ImportPreview:
        parsed: list[Record] = []
        warnings: list[str] = []
        for name, content in files:
            try:
                for p in parse_json_bytes(content, self.catalog, name):
                    parsed.append(p.data)
                    warnings += [f"{name} · {p.data.get('Name', '?')}: {w}" for w in p.warnings]
            except (ValueError, UnicodeDecodeError) as exc:
                warnings.append(f"{name}: JSON inválido ({exc})")
        result, final = self._repo.plan_import(parsed, on_conflict)
        new_names = {a.record.get("Name") for a in result.actions if a.action != "omite"}
        issues = [i for i in self.validate_all(final) if any(n and n in i.device for n in new_names) or i.file == "*"]
        return ImportPreview(result, len(parsed), warnings, issues)

    def apply_import(self, files: Sequence[tuple[str, bytes]], on_conflict: ConflictPolicy = "update",
                     force: bool = False) -> ImportPreview:
        preview = self.preview_import(files, on_conflict)
        if preview.blocking and not force:
            return preview
        parsed = [p.data for name, content in files for p in parse_json_bytes(content, self.catalog, name)]
        preview.result = self._repo.import_records(parsed, on_conflict)
        log.info("Importación: %d nuevos, %d actualizados, %d omitidos", preview.result.count("nuevo"),
                 preview.result.count("actualiza"), preview.result.count("omite"))
        return preview

    # ---------------------------------------------------------- exportar / migrar
    def export_json(self, sector: str | None = None) -> bytes:
        """Exporta agrupado por sector: {"Switch": [...], "UPS": [...]} (se puede reimportar tal cual)."""
        grouped: dict[str, list[Record]] = {}
        for r in self.records():
            if sector and not self._repo.same_type(r.get("Type"), sector):
                continue
            grouped.setdefault(str(r.get("Type", "Otro")), []).append(ordered_record(clean(r)))
        return json.dumps(grouped, ensure_ascii=False, indent=2).encode("utf-8")

    def copy_to(self, target: InventoryRepository) -> int:
        """Copia el inventario a otro backend (JSON -> base o base -> JSON)."""
        recs = [clean(r) for r in self.records()]
        target.replace_all([{**r, ORIGIN: target.destination_for(r, [])} if target.backend == "sqlite" else r for r in recs])
        return len(recs)


class AdminAuthenticator:
    """Usuario/clave guardados como hash PBKDF2-SHA256 con sal (nunca en texto plano)."""

    ITERATIONS = 200_000

    def __init__(self, file: Path):
        self._file = Path(file)

    @property
    def is_configured(self) -> bool:
        return self._file.exists()

    def _hash(self, password: str, salt: bytes) -> str:
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, self.ITERATIONS)
        return base64.b64encode(digest).decode()

    def set_credentials(self, user: str, password: str) -> None:
        if len(password) < 8:
            raise ValueError("La clave debe tener al menos 8 caracteres")
        salt = os.urandom(16)
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps({
            "user": user.strip(),
            "salt": base64.b64encode(salt).decode(),
            "hash": self._hash(password, salt),
            "iterations": self.ITERATIONS,
        }, indent=2), encoding="utf-8")
        log.info("Credenciales de administrador actualizadas para '%s'", user)

    def verify(self, user: str, password: str) -> bool:
        if not self.is_configured:
            return False
        data = json.loads(self._file.read_text(encoding="utf-8"))
        salt = base64.b64decode(data["salt"])
        ok_user = hmac.compare_digest(data["user"], user.strip())
        ok_pass = hmac.compare_digest(data["hash"], self._hash(password, salt))
        if not (ok_user and ok_pass):
            log.warning("Intento de login fallido para '%s'", user)
        return ok_user and ok_pass
