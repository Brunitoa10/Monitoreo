"""Inventario en archivos JSON, un archivo por sector (tipo de equipo).

- Lee recursivamente todos los *.json de la carpeta (sirve la estructura que ya tengas,
  ej. Config/Sites/<planta>/switches.json).
- Al agregar/importar, cada equipo va al archivo que YA contiene equipos de su tipo; si no
  existe ninguno, se crea el archivo del sector (switches.json, ups.json, ...).
- Escritura atómica + backup automático antes de cada cambio.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from nemesis.domain.device_mapper import ordered_record
from nemesis.domain.device_types import TypeCatalog
from nemesis.domain.record_normalizer import parse_payload
from nemesis.infrastructure.repositories.inventory import ORIGIN, InventoryRepository, LoadError, Record, clean

log = logging.getLogger(__name__)


class JsonDeviceRepository(InventoryRepository):
    backend = "json"

    def __init__(self, root: Path, backups_dir: Path, catalog: TypeCatalog | None = None):
        super().__init__(catalog or TypeCatalog())
        self._root = Path(root)
        self._backups = Path(backups_dir)

    @property
    def root(self) -> Path:
        return self._root

    def describe(self) -> str:
        return f"Archivos JSON en {self._root}"

    # ------------------------------------------------------------------ lectura
    def list_files(self) -> list[str]:
        if not self._root.exists():
            return []
        backups = self._backups.resolve()
        return sorted(
            p.relative_to(self._root).as_posix()
            for p in self._root.rglob("*.json")
            if backups not in p.resolve().parents
        )

    def _path(self, relative: str) -> Path:
        path = (self._root / relative).resolve()
        if self._root.resolve() not in path.parents:
            raise ValueError(f"Ruta fuera de la carpeta de inventario: {relative}")
        return path

    def read_raw(self, relative: str) -> list[dict[str, Any]]:
        text = self._path(relative).read_text(encoding="utf-8-sig").strip()
        if not text:
            return []
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise ValueError(f"{relative}: se esperaba una lista de dispositivos")
        return [r for r in data if isinstance(r, dict)]

    def records(self) -> tuple[list[Record], list[LoadError]]:
        out: list[Record] = []
        errors: list[LoadError] = []
        for rel in self.list_files():
            try:
                text = self._path(rel).read_text(encoding="utf-8-sig").strip()
                if not text:
                    continue
                # Lectura tolerante: alias de campos, secciones y tipo inferido del nombre del archivo.
                parsed = parse_payload(json.loads(text), self.catalog, rel)
                out.extend({**p.data, ORIGIN: rel} for p in parsed)
            except (OSError, ValueError) as exc:
                errors.append(LoadError(rel, f"JSON inválido: {exc}"))
                log.error("No se pudo leer %s: %s", rel, exc)
        return out, errors

    # ------------------------------------------------------------------ ruteo
    def destination_for(self, record: Record, current: Sequence[Record]) -> str:
        """Archivo donde predomina ese tipo; si no hay, el archivo propio del sector."""
        t = record.get("Type", "")
        counts = Counter(str(r.get(ORIGIN)) for r in current if self.same_type(r.get("Type"), t) and r.get(ORIGIN))
        if counts:
            return counts.most_common(1)[0][0]
        return self.catalog.file_for(str(t))

    # ---------------------------------------------------------------- escritura
    def backup(self, relative: str, stamp: str | None = None) -> Path | None:
        src = self._path(relative)
        if not src.exists():
            return None
        stamp = stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = self._backups / stamp / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return dest

    @staticmethod
    def serialize(records: Sequence[dict[str, Any]]) -> str:
        """Un objeto por línea: legible y fácil de comparar."""
        lines = [json.dumps(ordered_record(clean(r)), ensure_ascii=False) for r in records]
        return "[\n  " + ",\n  ".join(lines) + "\n]\n" if lines else "[]\n"

    def write_raw(self, relative: str, records: Sequence[dict[str, Any]], stamp: str | None = None) -> Path | None:
        path = self._path(relative)
        backup = self.backup(relative, stamp)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(self.serialize(records))
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        log.info("Inventario actualizado: %s (%d registros)", relative, len(records))
        return backup

    def replace_all(self, records: Sequence[Record]) -> list[str]:
        """Reescribe sólo los archivos que cambian. Los registros sin origen se rutean por tipo."""
        current, _ = self.records()
        before: dict[str, list[Record]] = defaultdict(list)
        for r in current:
            before[str(r[ORIGIN])].append(clean(r))
        after: dict[str, list[Record]] = defaultdict(list)
        routed: list[Record] = []
        for r in records:
            origin = r.get(ORIGIN)
            if not origin:
                origin = self.destination_for(r, routed + list(records))
            routed.append({**r, ORIGIN: origin})
            after[str(origin)].append(clean(r))

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backups: list[str] = []
        for rel in sorted(set(before) | set(after)):
            if before.get(rel, []) == after.get(rel, []):
                continue
            b = self.write_raw(rel, after.get(rel, []), stamp)
            if b:
                backups.append(str(b))
        return backups

    def delete_file(self, relative: str) -> Path | None:
        backup = self.backup(relative)
        self._path(relative).unlink(missing_ok=True)
        return backup
