"""Carga de configuración desde settings.toml (con valores por defecto seguros)."""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nemesis.domain.status_policy import Thresholds

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_FILE = PROJECT_ROOT / "settings.toml"


@dataclass(frozen=True)
class AppSettings:
    name: str = "Nemesis Monitor"
    organization: str = "Operaciones IT"


@dataclass(frozen=True)
class UiSettings:
    host: str = "127.0.0.1"   # sólo esta PC; "0.0.0.0" para la red
    port: int = 8501
    mode: str = "app"         # app (ventana propia) | web (navegador)


@dataclass(frozen=True)
class InventorySettings:
    backend: str = "json"     # json (archivos por sector) | sqlite (tabla en la base)


@dataclass(frozen=True)
class PathSettings:
    devices_dir: Path
    database: Path
    reports_dir: Path
    logs_dir: Path
    backups_dir: Path
    admin_file: Path


@dataclass(frozen=True)
class CollectorSettings:
    interval_seconds: int = 30
    max_workers: int = 32
    embedded: bool = True
    retention_days: int = 90
    confirm_cycles: int = 2


@dataclass(frozen=True)
class ProbeSettings:
    mode: str = "system"  # system | simulated
    ping_count: int = 3
    ping_timeout_ms: int = 800
    traceroute_enabled: bool = True
    traceroute_interval_minutes: int = 60
    traceroute_max_hops: int = 20
    traceroute_timeout_ms: int = 500


@dataclass(frozen=True)
class NotificationSettings:
    webhook_url: str = ""
    notify_on_open: bool = True
    notify_on_close: bool = True


@dataclass(frozen=True)
class Settings:
    app: AppSettings
    paths: PathSettings
    collector: CollectorSettings
    probe: ProbeSettings
    notifications: NotificationSettings
    ui: UiSettings
    inventory: InventorySettings
    default_thresholds: Thresholds
    type_thresholds: dict[str, Thresholds] = field(default_factory=dict)
    tcp_ports: dict[str, tuple[int, ...]] = field(default_factory=dict)
    type_definitions: dict[str, dict] = field(default_factory=dict)
    site_aliases: dict[str, str] = field(default_factory=dict)
    admin_session_minutes: int = 30
    source_file: Path | None = None
    overrides_file: Path | None = None


def _resolve(root: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (root / p)


def _pick(cls, data: dict[str, Any]):
    allowed = cls.__dataclass_fields__.keys()
    return cls(**{k: v for k, v in data.items() if k in allowed})


def _deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def overrides_path(root: Path | None = None) -> Path:
    """Ajustes hechos desde el panel admin (organización, intervalo, backend...). Pisan a settings.toml."""
    return (root or PROJECT_ROOT) / "data" / "overrides.json"


def read_overrides(root: Path | None = None) -> dict:
    path = overrides_path(root)
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        return {}


def save_overrides(changes: dict, path: Path | None = None) -> Path:
    path = Path(path or overrides_path())
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_deep_merge(current, changes), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_settings(path: str | Path | None = None) -> Settings:
    file = Path(path or os.environ.get("NEMESIS_SETTINGS") or DEFAULT_SETTINGS_FILE)
    data: dict[str, Any] = {}
    if file.exists():
        with file.open("rb") as fh:
            data = tomllib.load(fh)
    root = file.parent if file.exists() else PROJECT_ROOT
    data = _deep_merge(data, read_overrides(root))

    p = data.get("paths", {})
    paths = PathSettings(
        devices_dir=_resolve(root, p.get("devices_dir", "Config/Devices")),
        database=_resolve(root, os.environ.get("NEMESIS_DB") or p.get("database", "data/nemesis.db")),
        reports_dir=_resolve(root, p.get("reports_dir", "reports")),
        logs_dir=_resolve(root, p.get("logs_dir", "Logs/Python")),
        backups_dir=_resolve(root, p.get("backups_dir", "Config/_backups")),
        admin_file=_resolve(root, p.get("admin_file", "data/admin.json")),
    )

    probe_data = dict(data.get("probe", {}))
    if os.environ.get("NEMESIS_PROBE_MODE"):
        probe_data["mode"] = os.environ["NEMESIS_PROBE_MODE"]

    thresholds = data.get("thresholds", {})
    default_th = _pick(Thresholds, thresholds.get("default", {}))
    type_th = {
        name: _pick(Thresholds, {**thresholds.get("default", {}), **values})
        for name, values in thresholds.items()
        if name != "default" and isinstance(values, dict)
    }
    tcp_ports = {
        name: tuple(int(x) for x in cfg.get("tcp_ports", []))
        for name, cfg in data.get("types", {}).items()
        if isinstance(cfg, dict)
    }

    return Settings(
        app=_pick(AppSettings, data.get("app", {})),
        paths=paths,
        collector=_pick(CollectorSettings, data.get("collector", {})),
        probe=_pick(ProbeSettings, probe_data),
        notifications=_pick(NotificationSettings, data.get("notifications", {})),
        ui=_pick(UiSettings, data.get("ui", {})),
        inventory=_pick(InventorySettings, data.get("inventory", {})),
        default_thresholds=default_th,
        type_thresholds=type_th,
        tcp_ports=tcp_ports,
        type_definitions={k: v for k, v in data.get("types", {}).items() if isinstance(v, dict)},
        site_aliases=dict(data.get("validation", {}).get("site_aliases", {})),
        admin_session_minutes=int(data.get("admin", {}).get("session_minutes", 30)),
        source_file=file if file.exists() else None,
        overrides_file=overrides_path(root),
    )
