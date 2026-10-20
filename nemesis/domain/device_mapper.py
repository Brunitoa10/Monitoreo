"""Traduce los registros JSON (estructura original) a entidades Device.

Estructura soportada (igual a la de Config/Sites):
    { "Name": "...", "Site": "...", "IPAddress": "...", "Type": "Switch" }
    { "Name": "...", "Site": "...", "IPAddress_Padre": "...", "IPAddress_Hijo": "...", "Type": "Enlace" }

Cualquier clave "IPAddress_<Rol>" se convierte en un extremo a monitorear, así que
se pueden sumar tipos multi-extremo sin tocar código (Open/Closed).
"""
from __future__ import annotations

from typing import Any, Mapping

from nemesis.domain.models import PRIMARY_ROLE, Device, Target

IP_KEY = "IPAddress"
IP_ROLE_PREFIX = "IPAddress_"
CANONICAL_KEYS = ("Name", "Site", "IPAddress", "Type")


class DeviceMappingError(ValueError):
    pass


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def extract_targets(record: Mapping[str, Any]) -> tuple[Target, ...]:
    targets: list[Target] = []
    primary = _clean(record.get(IP_KEY))
    if primary:
        targets.append(Target(PRIMARY_ROLE, primary))
    for key, value in record.items():
        if key.startswith(IP_ROLE_PREFIX) and _clean(value):
            targets.append(Target(key[len(IP_ROLE_PREFIX):], _clean(value)))
    return tuple(targets)


def to_device(record: Mapping[str, Any], source_file: str = "") -> Device:
    name = _clean(record.get("Name"))
    dev_type = _clean(record.get("Type"))
    if not name:
        raise DeviceMappingError("Falta 'Name'")
    if not dev_type:
        raise DeviceMappingError(f"'{name}': falta 'Type'")
    targets = extract_targets(record)
    if not targets:
        raise DeviceMappingError(f"'{name}': no tiene IPAddress")
    return Device(
        name=name,
        site=_clean(record.get("Site")) or "Sin sitio",
        type=dev_type,
        targets=targets,
        source_file=source_file,
        raw=dict(record),
    )


def ordered_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Ordena las claves como el JSON original para que el archivo quede prolijo."""
    ordered = {k: record[k] for k in CANONICAL_KEYS if k in record}
    ordered.update({k: v for k, v in record.items() if k not in ordered})
    return ordered
