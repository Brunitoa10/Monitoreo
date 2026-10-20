"""Catálogo de tipos de dispositivo (sectores) con alias tolerantes a errores de tipeo.

"swicht", "Switches", "SW" -> Switch ; "cartelería", "pantalla" -> Carteleria ; etc.
Es configurable desde settings.toml ([types.<Tipo>] aliases = [...], file = "...") para
adaptarlo a cualquier empresa sin tocar código. Un tipo desconocido se acepta tal cual
(con mayúscula inicial) y crea su propio sector.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

from nemesis.domain.models import normalize


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", normalize(text)).strip("_") or "otros"


@dataclass(frozen=True)
class DeviceType:
    name: str                      # nombre canónico que se guarda en "Type"
    label: str                     # nombre para mostrar (sector)
    file: str                      # archivo JSON por defecto del sector
    aliases: tuple[str, ...] = ()
    multi_target: tuple[str, ...] = ()  # roles de IP (ej. Padre/Hijo para enlaces)


DEFAULT_TYPES: tuple[DeviceType, ...] = (
    DeviceType("Switch", "Switches", "switches.json",
               ("switch", "switches", "swicht", "swich", "swith", "sw", "conmutador", "core", "l2", "l3")),
    DeviceType("Carteleria", "Cartelería", "carteleria.json",
               ("carteleria", "cartelera", "señaletica", "senaletica", "signage", "pantalla", "pantallas",
                "digital signage", "tv", "monitor carteleria")),
    DeviceType("Printer", "Impresoras", "printers.json",
               ("printer", "printers", "impresora", "impresoras", "imp", "mfp", "multifuncion", "plotter")),
    DeviceType("UPS", "UPS", "ups.json", ("ups", "upss", "sai", "nobreak", "no-break")),
    DeviceType("Enlace", "Enlaces", "enlaces.json",
               ("enlace", "enlaces", "radioenlace", "radio enlace", "ptp", "link", "antena", "wireless bridge"),
               ("Padre", "Hijo")),
    DeviceType("Router", "Routers", "routers.json", ("router", "routers", "gateway", "firewall", "fw", "mikrotik")),
    DeviceType("AP", "Access Points", "access_points.json",
               ("ap", "aps", "access point", "access points", "wifi", "wi-fi", "punto de acceso")),
    DeviceType("Camara", "Cámaras", "camaras.json", ("camara", "camaras", "cctv", "ipcam", "camera", "nvr", "dvr")),
    DeviceType("Servidor", "Servidores", "servidores.json", ("servidor", "servidores", "server", "srv", "host", "vm")),
    DeviceType("PC", "PCs", "pcs.json", ("pc", "pcs", "desktop", "notebook", "laptop", "puesto", "estacion")),
)


@dataclass
class TypeCatalog:
    types: list[DeviceType] = field(default_factory=lambda: list(DEFAULT_TYPES))

    def __post_init__(self) -> None:
        self._index: dict[str, DeviceType] = {}
        for t in self.types:
            for key in (t.name, t.label, *t.aliases):
                self._index[normalize(key)] = t
            self._index[slugify(t.file.removesuffix(".json"))] = t

    # ---------------------------------------------------------------- consulta
    @property
    def names(self) -> list[str]:
        return [t.name for t in self.types]

    def get(self, name: str) -> Optional[DeviceType]:
        return self._index.get(normalize(name))

    def resolve(self, raw: str | None, fuzzy: bool = True) -> Optional[str]:
        """Devuelve el tipo canónico; tolera plurales, acentos y errores de tipeo."""
        if not raw or not str(raw).strip():
            return None
        key = normalize(raw)
        hit = self._index.get(key) or self._index.get(key.rstrip("s")) or self._index.get(slugify(key))
        if hit:
            return hit.name
        if fuzzy:
            match = difflib.get_close_matches(key, list(self._index), n=1, cutoff=0.8)
            if match:
                return self._index[match[0]].name
        return str(raw).strip()[:1].upper() + str(raw).strip()[1:]  # tipo nuevo: se respeta

    def infer_from_text(self, text: str | None) -> Optional[str]:
        """Detecta el tipo a partir de un nombre de archivo o de sección (ej. 'switches_planta.json')."""
        if not text:
            return None
        words = re.split(r"[^a-z0-9]+", normalize(re.sub(r"\.json$", "", str(text), flags=re.I)))
        for w in words:
            if w and (t := self._index.get(w) or self._index.get(w.rstrip("s"))):
                return t.name
        return None

    def label(self, name: str) -> str:
        t = self.get(name)
        return t.label if t else name

    def file_for(self, name: str) -> str:
        t = self.get(name)
        return t.file if t else f"{slugify(name)}.json"

    def roles_for(self, name: str) -> tuple[str, ...]:
        t = self.get(name)
        return t.multi_target if t else ()

    # ------------------------------------------------------------- construcción
    @classmethod
    def from_settings(cls, overrides: Mapping[str, Mapping] | None) -> "TypeCatalog":
        """Combina los tipos por defecto con los de settings.toml ([types.<Nombre>])."""
        by_name = {t.name.lower(): t for t in DEFAULT_TYPES}
        for name, cfg in (overrides or {}).items():
            if not isinstance(cfg, Mapping):
                continue
            base = by_name.get(name.lower())
            aliases = tuple(cfg.get("aliases", ())) + (base.aliases if base else ())
            by_name[name.lower()] = DeviceType(
                name=base.name if base else name,
                label=cfg.get("label") or (base.label if base else name),
                file=cfg.get("file") or (base.file if base else f"{slugify(name)}.json"),
                aliases=aliases,
                multi_target=tuple(cfg.get("roles", ())) or (base.multi_target if base else ()),
            )
        return cls(list(by_name.values()))

    def extend(self, names: Iterable[str]) -> None:
        """Registra tipos nuevos descubiertos en el inventario (para listas desplegables)."""
        for n in names:
            if n and not self.get(n):
                t = DeviceType(n, n, f"{slugify(n)}.json")
                self.types.append(t)
                self._index[normalize(n)] = t
