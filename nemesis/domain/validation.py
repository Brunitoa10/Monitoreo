"""Validación de calidad de datos del inventario JSON.

Cada regla es una clase independiente (Strategy / Chain of Responsibility):
para sumar una regla nueva se agrega una clase, sin modificar las demás.
"""
from __future__ import annotations

import difflib
import ipaddress
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

from nemesis.domain.device_mapper import IP_KEY, IP_ROLE_PREFIX
from nemesis.domain.enums import IssueSeverity
from nemesis.domain.models import ValidationIssue, normalize

Record = Mapping[str, Any]
FileRecords = Mapping[str, Sequence[Record]]  # archivo -> registros


def _ip_fields(record: Record) -> list[tuple[str, str]]:
    return [
        (k, str(v).strip())
        for k, v in record.items()
        if (k == IP_KEY or k.startswith(IP_ROLE_PREFIX)) and str(v or "").strip()
    ]


class ValidationRule(ABC):
    @abstractmethod
    def check(self, files: FileRecords) -> Iterable[ValidationIssue]:
        ...


class RequiredFieldsRule(ValidationRule):
    REQUIRED = ("Name", "Type", "Site")

    def check(self, files: FileRecords) -> Iterable[ValidationIssue]:
        for file, records in files.items():
            for idx, rec in enumerate(records, start=1):
                label = str(rec.get("Name") or f"fila {idx}")
                for key in self.REQUIRED:
                    if not str(rec.get(key) or "").strip():
                        yield ValidationIssue(IssueSeverity.ERROR, file, label, key, f"Falta el campo '{key}'")
                if not _ip_fields(rec):
                    yield ValidationIssue(IssueSeverity.ERROR, file, label, IP_KEY, "No tiene ninguna IP")


class IpFormatRule(ValidationRule):
    def check(self, files: FileRecords) -> Iterable[ValidationIssue]:
        for file, records in files.items():
            for rec in records:
                for key, value in _ip_fields(rec):
                    try:
                        ipaddress.ip_address(value)
                    except ValueError:
                        # Se permite hostname: sólo se avisa si parece una IP mal escrita.
                        if value.replace(".", "").isdigit():
                            yield ValidationIssue(
                                IssueSeverity.ERROR, file, str(rec.get("Name")), key, f"IP inválida: {value}"
                            )


class DuplicateIpRule(ValidationRule):
    """La misma IP en dos equipos suele ser un error de carga (o un equipo duplicado)."""

    def check(self, files: FileRecords) -> Iterable[ValidationIssue]:
        seen: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for file, records in files.items():
            for rec in records:
                for _, ip in _ip_fields(rec):
                    seen[ip].append((file, f"{rec.get('Name')} ({rec.get('Type')}, {rec.get('Site')})"))
        for ip, owners in seen.items():
            if len(owners) > 1:
                names = "; ".join(o[1] for o in owners)
                for file, label in owners:
                    yield ValidationIssue(
                        IssueSeverity.ERROR, file, label, IP_KEY, f"IP {ip} duplicada en {len(owners)} equipos: {names}"
                    )


class DuplicateNameRule(ValidationRule):
    def check(self, files: FileRecords) -> Iterable[ValidationIssue]:
        seen: dict[tuple[str, str, str], int] = defaultdict(int)
        for records in files.values():
            for rec in records:
                seen[(normalize(rec.get("Type")), normalize(rec.get("Site")), normalize(rec.get("Name")))] += 1
        for file, records in files.items():
            for rec in records:
                key = (normalize(rec.get("Type")), normalize(rec.get("Site")), normalize(rec.get("Name")))
                if seen[key] > 1:
                    yield ValidationIssue(
                        IssueSeverity.WARNING, file, str(rec.get("Name")), "Name",
                        "Nombre repetido en el mismo sitio y tipo: conviene diferenciarlo (ej. 'Backup 1', 'Backup 2')",
                    )


class ReservedWordTypoRule(ValidationRule):
    """'Diponible', 'Disponble'... -> 'Disponible' (palabra con significado especial en la app)."""

    def check(self, files: FileRecords) -> Iterable[ValidationIssue]:
        for file, records in files.items():
            for rec in records:
                for key in ("Name", "Site"):
                    value = normalize(rec.get(key))
                    if value and value != "disponible" and difflib.SequenceMatcher(None, value, "disponible").ratio() >= 0.85:
                        yield ValidationIssue(
                            IssueSeverity.INFO, file, str(rec.get("Name")), key,
                            f"Posible error de tipeo '{rec.get(key)}' → 'Disponible'",
                        )


class SiteConsistencyRule(ValidationRule):
    """Detecta el mismo sitio escrito de formas distintas, sin listas fijas (sirve para cualquier empresa):
    abreviaturas ('PLA' vs 'Planta'), prefijos ('Depo' vs 'Deposito') o nombres casi iguales.
    Se pueden declarar equivalencias conocidas en settings.toml ([validation] site_aliases)."""

    def __init__(self, aliases: dict[str, str] | None = None):
        self._aliases = {normalize(k): normalize(v) for k, v in (aliases or {}).items()}

    def check(self, files: FileRecords) -> Iterable[ValidationIssue]:
        sites = sorted({str(r.get("Site")).strip() for recs in files.values() for r in recs if r.get("Site")})
        norm = {s: normalize(s) for s in sites}
        reported: set[tuple[str, str]] = set()
        for i, a in enumerate(sites):
            for b in sites[i + 1:]:
                na, nb = norm[a], norm[b]
                if na == nb or normalize("disponible") in (na, nb):
                    continue
                short, long_ = sorted((na, nb), key=len)
                similar = (
                    self._aliases.get(na) == nb or self._aliases.get(nb) == na
                    or (len(short) >= 3 and long_.startswith(short))
                    or difflib.SequenceMatcher(None, na, nb).ratio() >= 0.85
                )
                if similar and (a, b) not in reported:
                    reported.add((a, b))
                    yield ValidationIssue(
                        IssueSeverity.WARNING, "*", "*", "Site",
                        f"¿'{a}' y '{b}' son el mismo sitio? Unificar el nombre para que las métricas por sitio sean correctas",
                    )


class KnownTypeRule(ValidationRule):
    def __init__(self, known_types: Iterable[str]):
        self._known = {t.lower() for t in known_types}

    def check(self, files: FileRecords) -> Iterable[ValidationIssue]:
        if not self._known:
            return
        for file, records in files.items():
            for rec in records:
                t = str(rec.get("Type") or "")
                if t and t.lower() not in self._known:
                    yield ValidationIssue(
                        IssueSeverity.INFO, file, str(rec.get("Name")), "Type",
                        f"Tipo '{t}' sin monitor específico: se usa el monitor genérico por ICMP",
                    )


class DeviceValidator:
    """Ejecuta todas las reglas y devuelve los hallazgos ordenados por severidad."""

    _ORDER = {IssueSeverity.ERROR: 0, IssueSeverity.WARNING: 1, IssueSeverity.INFO: 2}

    def __init__(self, rules: Sequence[ValidationRule]):
        self._rules = list(rules)

    def validate(self, files: FileRecords) -> list[ValidationIssue]:
        issues = [issue for rule in self._rules for issue in rule.check(files)]
        return sorted(issues, key=lambda i: (self._ORDER[i.severity], i.file, i.device))

    @staticmethod
    def has_errors(issues: Iterable[ValidationIssue]) -> bool:
        return any(i.severity == IssueSeverity.ERROR for i in issues)


def default_validator(known_types: Iterable[str] = (), site_aliases: dict[str, str] | None = None) -> DeviceValidator:
    return DeviceValidator([
        RequiredFieldsRule(),
        IpFormatRule(),
        DuplicateIpRule(),
        DuplicateNameRule(),
        ReservedWordTypoRule(),
        SiteConsistencyRule(site_aliases),
        KnownTypeRule(known_types),
    ])
