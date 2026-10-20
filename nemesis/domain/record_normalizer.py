"""Normaliza registros de inventario venidos de cualquier JSON (o del alta manual).

Acepta nombres de campo flexibles y en español/inglés:
    Name / nombre / equipo / hostname          -> Name
    Site / sitio / sector / ubicacion / planta -> Site
    IPAddress / ip / direccion_ip / host       -> IPAddress
    Type / tipo / categoria / clase            -> Type   (normalizado con TypeCatalog)
    IPAddress_Padre / ip_padre / padre         -> IPAddress_Padre (idem Hijo y cualquier rol)

Y estructuras de archivo variadas:
    [ {...}, {...} ]                     lista de equipos
    { ...un equipo... }                  un solo equipo
    { "switches": [...], "ups": [...] }  secciones: la clave define el tipo si el equipo no lo trae
    { "devices": [...] } / { "items": [...] }
Si un equipo no trae tipo, se infiere de la sección o del nombre del archivo (ej. ups_planta.json).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from nemesis.domain.device_types import TypeCatalog
from nemesis.domain.models import normalize

FIELD_ALIASES = {
    "Name": ("name", "nombre", "equipo", "hostname", "descripcion", "description", "dispositivo", "device"),
    "Site": ("site", "sitio", "sector", "ubicacion", "location", "planta", "sede", "area", "lugar"),
    "IPAddress": ("ipaddress", "ip", "ip address", "direccion ip", "direccion_ip", "ipv4", "address", "host", "ip_address"),
    "Type": ("type", "tipo", "categoria", "category", "clase", "kind", "devicetype", "device_type"),
}
ROLE_PREFIXES = ("ipaddress_", "ip_", "ip ")
CONTAINER_KEYS = ("devices", "dispositivos", "equipos", "items", "data", "inventario", "inventory")


def _norm_key(k: str) -> str:
    return normalize(k).replace("-", " ").replace("_", " ").strip()


_LOOKUP = {_norm_key(alias): canon for canon, aliases in FIELD_ALIASES.items() for alias in aliases}


@dataclass
class ParsedRecord:
    data: dict[str, Any]
    origin: str = ""                 # archivo/sección de donde vino
    warnings: list[str] = field(default_factory=list)


def normalize_record(raw: Mapping[str, Any], catalog: TypeCatalog, type_hint: Optional[str] = None) -> ParsedRecord:
    out: dict[str, Any] = {}
    warnings: list[str] = []
    for key, value in raw.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if isinstance(value, float) and value != value:  # NaN del editor de tablas
            continue
        if str(key).startswith("_"):  # metadatos internos (_origen, _id)
            out[key] = value
            continue
        nk = _norm_key(str(key))
        canon = _LOOKUP.get(nk)
        if canon:
            out[canon] = str(value).strip()
            continue
        role = None
        for prefix in ROLE_PREFIXES:
            if nk.startswith(prefix.replace("_", " ")):
                role = nk[len(prefix):].strip()
        if nk in ("padre", "hijo", "origen", "destino", "a", "b"):
            role = nk
        if role:
            out[f"IPAddress_{role[:1].upper()}{role[1:]}"] = str(value).strip()
        else:
            out[str(key)] = value.strip() if isinstance(value, str) else value

    raw_type = out.get("Type") or type_hint
    resolved = catalog.resolve(raw_type) if raw_type else None
    if not resolved:
        warnings.append("Sin tipo: se asigna 'Otro'")
        resolved = "Otro"
    elif out.get("Type") and normalize(out["Type"]) != normalize(resolved):
        warnings.append(f"Tipo '{out['Type']}' interpretado como '{resolved}'")
    out["Type"] = resolved
    return ParsedRecord(out, warnings=warnings)


def parse_payload(payload: Any, catalog: TypeCatalog, source_name: str = "") -> list[ParsedRecord]:
    """Convierte cualquier estructura JSON soportada en registros normalizados."""
    file_hint = catalog.infer_from_text(source_name)
    records: list[ParsedRecord] = []

    def visit(node: Any, hint: Optional[str], origin: str) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item, hint, origin)
        elif isinstance(node, Mapping):
            keys = {_norm_key(k) for k in node}
            looks_like_device = bool(keys & set(_LOOKUP)) or any(k.startswith("ip") for k in keys)
            if looks_like_device and not all(isinstance(v, (list, dict)) for v in node.values()):
                rec = normalize_record(node, catalog, hint)
                rec.origin = origin
                records.append(rec)
                return
            for key, value in node.items():
                if isinstance(value, (list, dict)):
                    section_hint = None if _norm_key(key) in CONTAINER_KEYS else (catalog.infer_from_text(key) or catalog.resolve(key, fuzzy=False))
                    visit(value, section_hint or hint, f"{origin}/{key}" if origin else str(key))

    visit(payload, file_hint, source_name)
    return records


def parse_json_bytes(content: bytes, catalog: TypeCatalog, source_name: str = "") -> list[ParsedRecord]:
    return parse_payload(json.loads(content.decode("utf-8-sig")), catalog, source_name)


def match_keys(record: Mapping[str, Any]) -> list[tuple]:
    """Claves para detectar si un equipo ya existe: (tipo, IP principal) y (tipo, sitio, nombre)."""
    t = normalize(record.get("Type"))
    ips = [str(v).strip() for k, v in record.items() if str(k).startswith("IPAddress") and v]
    keys: list[tuple] = []
    if ips:
        keys.append(("ip", t, ips[0]))
    if record.get("Name"):
        keys.append(("name", t, normalize(record.get("Site")), normalize(record.get("Name")), ips[0] if ips else ""))
    return keys


def iter_ips(record: Mapping[str, Any]) -> Iterable[str]:
    return (str(v).strip() for k, v in record.items() if str(k).startswith("IPAddress") and v)
