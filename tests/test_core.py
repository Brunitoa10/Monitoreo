"""Tests de dominio, parsers, incidentes, admin y reportes (sin red: usa probes falsos)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from nemesis.core.events import CycleCompleted, EventBus, IncidentClosed, IncidentOpened
from nemesis.domain.device_mapper import to_device
from nemesis.domain.enums import IssueSeverity, Status
from nemesis.domain.models import HealthResult, ProbeResult
from nemesis.domain.status_policy import Thresholds, ThresholdStatusPolicy
from nemesis.domain.validation import default_validator
from nemesis.infrastructure.probes.parsers import estimate_hops, parse_ping, parse_traceroute
from nemesis.infrastructure.repositories import JsonDeviceRepository, SqliteStore
from nemesis.services.admin import AdminAuthenticator, InventoryAdminService
from nemesis.services.incidents import IncidentService

WIN_ES = """
Haciendo ping a 192.168.10.1 con 32 bytes de datos:
Respuesta desde 192.168.10.1: bytes=32 tiempo=3ms TTL=254
Respuesta desde 192.168.10.1: bytes=32 tiempo<1m TTL=254
Respuesta desde 192.168.10.1: bytes=32 tiempo=5ms TTL=254
"""
WIN_UNREACHABLE = """
Respuesta desde 192.168.10.5: Host de destino inaccesible.
Tiempo de espera agotado para esta solicitud.
"""
LINUX = "64 bytes from 10.0.0.1: icmp_seq=1 ttl=63 time=12.4 ms\n64 bytes from 10.0.0.1: icmp_seq=2 ttl=63 time=10.2 ms"
TRACERT = """
Traza a la dirección 192.168.20.50 sobre un máximo de 20 saltos

  1    <1 ms    <1 ms    <1 ms  192.168.10.1
  2     2 ms     1 ms     2 ms  10.100.97.1
  3     *        *        *     Tiempo de espera agotado para esta solicitud.
  4     4 ms     3 ms     3 ms  192.168.20.50

Traza completa.
"""


def probe(online=True, rtt=2.0, role="Principal", loss_recv=3):
    return ProbeResult(role, "10.0.0.1", "icmp", online, 3, loss_recv if online else 0,
                       rtt if online else None, rtt, rtt, 0.5 if online else None, 64, 1)


def device(type_="Switch", **extra):
    return to_device({"Name": "SW1", "Site": "Sede", "IPAddress": "10.0.0.1", "Type": type_, **extra})


# ------------------------------------------------------------------ parsers
def test_parse_ping_windows_spanish():
    stats = parse_ping(WIN_ES)
    assert stats.received == 3 and stats.ttl == 254
    assert stats.minimum == 0.5 and stats.maximum == 5


def test_unreachable_is_not_a_reply():
    assert parse_ping(WIN_UNREACHABLE).received == 0


def test_parse_ping_linux():
    stats = parse_ping(LINUX)
    assert stats.received == 2 and stats.avg == 11.3 and stats.ttl == 63


def test_estimate_hops():
    assert estimate_hops(254) == 1
    assert estimate_hops(126) == 2
    assert estimate_hops(63) == 1
    assert estimate_hops(None) is None


def test_parse_tracert():
    hops, reached = parse_traceroute(TRACERT, "192.168.20.50")
    assert reached and len(hops) == 4 and hops[2].timed_out and hops[0].rtt_ms == 0.5


# ------------------------------------------------------------------- dominio
def test_link_targets_from_json():
    d = to_device({"Name": "E5", "Site": "Sede", "IPAddress_Padre": "1.1.1.1", "IPAddress_Hijo": "1.1.1.2", "Type": "Enlace"})
    assert [t.role for t in d.targets] == ["Padre", "Hijo"]


@pytest.mark.parametrize("probes,expected", [
    ([probe()], Status.HEALTHY),
    ([probe(online=False)], Status.CRITICAL),
    ([probe(rtt=500)], Status.WARNING),
    ([probe(loss_recv=1)], Status.WARNING),
    ([probe(role="Padre"), probe(online=False, role="Hijo")], Status.WARNING),
    ([], Status.UNKNOWN),
])
def test_status_policy(probes, expected):
    policy = ThresholdStatusPolicy(Thresholds(latency_warning_ms=100))
    assert policy.evaluate(device(), probes)[0] == expected


def test_reserved_device_never_critical():
    policy = ThresholdStatusPolicy(Thresholds())
    d = to_device({"Name": "Disponible", "Site": "Disponible", "IPAddress": "10.0.0.9", "Type": "Switch"})
    assert policy.evaluate(d, [probe(online=False)])[0] == Status.AVAILABLE


def test_validator_finds_duplicate_ip_and_missing_fields():
    files = {"a.json": [{"Name": "A", "Site": "Sede", "IPAddress": "10.0.0.1", "Type": "Switch"},
                        {"Name": "B", "Site": "Sede", "IPAddress": "10.0.0.1", "Type": "Switch"},
                        {"Name": "C", "IPAddress": "10.0.0.999", "Type": "Switch"}]}
    issues = default_validator(["switch"]).validate(files)
    msgs = " ".join(i.message for i in issues)
    assert "duplicada" in msgs and "Falta el campo 'Site'" in msgs and "IP inválida" in msgs


# ---------------------------------------------------------------- incidentes
def test_incident_lifecycle_with_confirmation(tmp_path):
    store = SqliteStore(tmp_path / "t.db")
    bus = EventBus()
    events = []
    bus.subscribe(IncidentOpened, events.append)
    bus.subscribe(IncidentClosed, events.append)
    IncidentService(store, bus, confirm_cycles=2)
    d = device()
    t0 = datetime(2026, 1, 1, 10, 0)

    def cycle(status, minutes):
        r = HealthResult(d, status, (probe(status != Status.CRITICAL),), t0 + timedelta(minutes=minutes))
        bus.publish(CycleCompleted([r], 0, 0))

    cycle(Status.HEALTHY, -1)
    cycle(Status.CRITICAL, 0)
    assert not events  # un solo fallo no abre incidente (anti-flapping)
    cycle(Status.CRITICAL, 1)
    assert isinstance(events[-1], IncidentOpened)
    inc = events[-1].incident
    assert inc.started_at == t0                               # fechado en el PRIMER chequeo fallido
    assert inc.last_ok_at == t0 - timedelta(minutes=1)        # último OK antes de la caída
    cycle(Status.HEALTHY, 5)
    assert isinstance(events[-1], IncidentClosed)
    assert events[-1].incident.duration_seconds() == 300
    assert store.open_incidents() == []


def test_audit_log_has_exact_times(tmp_path):
    from nemesis.domain.models import Incident, format_duration
    from nemesis.services.metrics import MetricsService, ReportFilter
    store = SqliteStore(tmp_path / "a.db")
    t0 = datetime.now().replace(microsecond=0) - timedelta(hours=2)
    inc = Incident("x", "SW Core", "Sede", "Switch", Status.CRITICAL, t0, message="Sin respuesta",
                   last_ok_at=t0 - timedelta(seconds=30))
    inc.id = store.open_incident(inc)
    store.close_incident(inc.id, t0 + timedelta(minutes=12, seconds=34))
    log = MetricsService(store).audit_log(ReportFilter.last(hours=3))
    row = log.iloc[0]
    assert row["Hora caída"] == t0.strftime("%H:%M:%S")
    assert row["Hora recuperación"] == (t0 + timedelta(minutes=12, seconds=34)).strftime("%H:%M:%S")
    assert row["Duración"] == "12 min 34 s" and row["Estado"] == "Recuperado" and row["Severidad"] == "Caída"
    assert format_duration(90061) == "1 d 01 h 01 min 01 s"


# --------------------------------------------------------------------- admin
from nemesis.domain.device_types import TypeCatalog
from nemesis.infrastructure.repositories import SqliteInventoryRepository


def _json_admin(tmp_path):
    root, backups = tmp_path / "Sites", tmp_path / "bk"
    (root / "Planta").mkdir(parents=True)
    (root / "Planta" / "switches.json").write_text(json.dumps(
        [{"Name": "A", "Site": "Sede", "IPAddress": "10.0.0.1", "Type": "Switch"}]))
    cat = TypeCatalog()
    repo = JsonDeviceRepository(root, backups, cat)
    return InventoryAdminService(repo, default_validator(cat.names), cat), repo, root


def test_type_catalog_tolerates_typos():
    cat = TypeCatalog()
    assert cat.resolve("swicht") == "Switch"
    assert cat.resolve("Switches") == "Switch"
    assert cat.resolve("cartelería") == "Carteleria"
    assert cat.resolve("Impresora") == "Printer"
    assert cat.resolve("radioenlace") == "Enlace"
    assert cat.resolve("Reloj fichaje") == "Reloj fichaje"   # tipo nuevo: se respeta
    assert cat.infer_from_text("ups_planta_norte.json") == "UPS"


def test_save_table_blocks_errors_and_backs_up(tmp_path):
    admin, repo, _ = _json_admin(tmp_path)
    bad = admin.save_table([{"Name": "A", "Site": "Sede", "IPAddress": "10.0.0.1", "Type": "Switch"},
                            {"Name": "B", "Site": "Sede", "IPAddress": "10.0.0.1", "Type": "Switch"}])
    assert not bad.saved and any(i.severity == IssueSeverity.ERROR for i in bad.issues)
    ok = admin.save_table([{"Name": "A", "Site": "Sede", "IPAddress": "10.0.0.1", "Type": "Switch", "_origen": "Planta/switches.json"},
                           {"Name": "B", "Site": "Sede", "IPAddress": "10.0.0.2", "Type": "Switch", "Extra": None}])
    assert ok.saved and ok.backups
    devices, errors = repo.get_all()
    assert len(devices) == 2 and not errors
    assert all(d.source_file == "Planta/switches.json" for d in devices)  # el nuevo fue al archivo existente del sector


def test_manual_add_goes_to_its_sector(tmp_path):
    admin, repo, root = _json_admin(tmp_path)
    r1 = admin.add_device({"Type": "ups", "Name": "UPS rack", "Site": "DC", "IPAddress": "10.0.9.1"})
    r2 = admin.add_device({"Type": "SW", "Name": "SW2", "Site": "Sede", "IPAddress": "10.0.0.2"})
    assert r1.saved and r1.destination == "ups.json" and (root / "ups.json").exists()
    assert r2.saved and r2.destination == "Planta/switches.json"
    dup = admin.add_device({"Type": "Switch", "Name": "Otro", "Site": "Sede", "IPAddress": "10.0.0.2"})
    assert not dup.saved  # IP duplicada bloquea


def test_import_routes_by_type_and_updates_existing(tmp_path):
    admin, repo, root = _json_admin(tmp_path)
    payload = json.dumps({
        "switches": [{"nombre": "A", "sitio": "Sede", "ip": "10.0.0.1", "Modelo": "C2960"}],   # existente -> actualiza
        "equipos": [
            {"nombre": "Pantalla hall", "ubicacion": "Sede", "ip": "10.0.5.1", "tipo": "cartelería"},
            {"nombre": "Enlace norte", "tipo": "radioenlace", "ip_padre": "10.0.1.1", "ip_hijo": "10.0.1.2", "sitio": "Norte"},
        ],
    }).encode()
    preview = admin.preview_import([("export.json", payload)])
    assert preview.result.count("nuevo") == 2 and preview.result.count("actualiza") == 1
    assert not (root / "carteleria.json").exists()           # el preview no escribe
    done = admin.apply_import([("export.json", payload)])
    assert done.result.applied
    files = repo.list_files()
    assert "carteleria.json" in files and "enlaces.json" in files
    link = [d for d in repo.get_all()[0] if d.type == "Enlace"][0]
    assert [t.role for t in link.targets] == ["Padre", "Hijo"]
    assert repo.read_raw("Planta/switches.json")[0]["Modelo"] == "C2960"
    # importar de nuevo lo mismo no duplica
    again = admin.apply_import([("export.json", payload)])
    assert again.result.count("nuevo") == 0


def test_sqlite_backend_and_migration(tmp_path):
    admin, repo, _ = _json_admin(tmp_path)
    admin.add_device({"Type": "Printer", "Name": "Imp 1", "Site": "Sede", "IPAddress": "10.0.7.1"})
    db = SqliteInventoryRepository(tmp_path / "inv.db", admin.catalog)
    assert admin.copy_to(db) == 2
    db_admin = InventoryAdminService(db, default_validator(), admin.catalog)
    assert db_admin.add_device({"Type": "camara", "Name": "Cam 1", "Site": "Sede", "IPAddress": "10.0.8.1"}).saved
    devices, _ = db.get_all()
    assert sorted(d.type for d in devices) == ["Camara", "Printer", "Switch"]
    assert json.loads(db_admin.export_json())["Camara"][0]["Name"] == "Cam 1"
    # misma identidad de equipo en ambos backends (el histórico no se pierde al migrar)
    assert {d.id for d in repo.get_all()[0]} <= {d.id for d in devices}


def test_generic_site_consistency():
    files = {"x.json": [{"Name": "a", "Site": "PLA", "IPAddress": "1.1.1.1", "Type": "Switch"},
                        {"Name": "b", "Site": "Planta", "IPAddress": "1.1.1.2", "Type": "Switch"},
                        {"Name": "c", "Site": "Oficina Central", "IPAddress": "1.1.1.3", "Type": "Switch"}]}
    msgs = [i.message for i in default_validator().validate(files)]
    assert any("PLA" in m and "Planta" in m for m in msgs)
    assert not any("Oficina Central" in m for m in msgs)


def test_authenticator(tmp_path):
    auth = AdminAuthenticator(tmp_path / "admin.json")
    auth.set_credentials("admin", "clave-segura")
    assert auth.verify("admin", "clave-segura")
    assert not auth.verify("admin", "otra")
    assert "clave-segura" not in Path(tmp_path / "admin.json").read_text()


# ------------------------------------------------------------- end-to-end
def test_end_to_end_simulated(tmp_path, monkeypatch):
    sites = tmp_path / "Config" / "Devices" / "X"
    sites.mkdir(parents=True)
    (sites / "sw.json").write_text(json.dumps([
        {"Name": f"SW{i}", "Site": "X", "IPAddress": f"10.9.0.{i}", "Type": "Switch"} for i in range(1, 6)
    ] + [{"Name": "Link", "Site": "X", "IPAddress_Padre": "10.9.1.1", "IPAddress_Hijo": "10.9.1.2", "Type": "Enlace"}]))
    (tmp_path / "settings.toml").write_text('[probe]\nmode="simulated"\n[collector]\nembedded=false\n')
    from nemesis.config import load_settings
    from nemesis.container import Container
    from nemesis.demo import generate_demo_history
    from nemesis.services.metrics import ReportFilter

    c = Container(load_settings(tmp_path / "settings.toml"))
    report = c.monitoring.run_cycle()
    assert len(report.results) == 6
    generate_demo_history(c, days=1, step_minutes=30)
    f = ReportFilter.last(hours=30)
    k = c.metrics.kpis(f)
    assert k.checks_total > 0 and k.availability_pct is not None
    for key in ("pdf", "excel", "powerbi"):
        name, content, path = c.reports.generate(key, f)
        assert content and path.exists()
    assert (tmp_path / "reports" / "powerbi" / "latest" / "fact_mediciones_hora.csv").exists()
