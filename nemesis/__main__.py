"""CLI de Nemesis Monitor.

    python -m nemesis app                   # ventana de escritorio (localhost, sin pestañas)
    python -m nemesis web [--lan]           # dashboard en el navegador
    python -m nemesis check                 # un ciclo y tabla en consola
    python -m nemesis collect               # colector continuo (sin dashboard)
    python -m nemesis traceroute [--ip IP]  # saltos de todos o de un equipo
    python -m nemesis report --format pdf|excel|powerbi --days 7
    python -m nemesis validate              # calidad de datos del inventario JSON
    python -m nemesis set-admin             # crea/cambia usuario del panel admin
    python -m nemesis demo-data --days 7 --db data/demo.db
"""
from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys

from nemesis.domain.enums import Status

ANSI = {
    Status.HEALTHY: "\033[32m", Status.WARNING: "\033[33m", Status.CRITICAL: "\033[31m",
    Status.AVAILABLE: "\033[90m", Status.UNKNOWN: "\033[90m",
}
RESET = "\033[0m"


def _container(args):
    if getattr(args, "db", None):
        os.environ["NEMESIS_DB"] = args.db
    if getattr(args, "simulated", False):
        os.environ["NEMESIS_PROBE_MODE"] = "simulated"
    from nemesis.container import get_container
    return get_container(args.settings)


def cmd_check(args) -> int:
    c = _container(args)
    report = c.monitoring.run_cycle(persist=not args.no_save)
    if os.name == "nt":
        os.system("")  # habilita colores ANSI en la consola de Windows
    header = f"{'TIPO':<11} {'SITIO':<11} {'EQUIPO':<30} {'IP':<34} {'ESTADO':<10} {'LAT':>8} {'PÉRD':>6} {'SALTOS':>6}  DETALLE"
    print(header)
    print("-" * len(header))
    for r in report.results:
        lat = f"{r.latency_ms:.1f}" if r.latency_ms is not None else "-"
        color = ANSI.get(r.status, "")
        print(f"{color}{r.device.type:<11} {r.device.site[:11]:<11} {r.device.name[:30]:<30} {r.device.ip_display[:34]:<34} "
              f"{r.status.label:<10} {lat:>8} {r.loss_pct:>5.0f}% {r.hops if r.hops is not None else '-':>6}  {r.message}{RESET}")
    print(f"\n{len(report.results)} equipos en {report.duration_s:.1f}s · Operativos {report.count(Status.HEALTHY)} · "
          f"Degradados {report.count(Status.WARNING)} · Caídos {report.count(Status.CRITICAL)}")
    return 0


def cmd_collect(args) -> int:
    c = _container(args)
    print(f"Colector en marcha cada {c.settings.collector.interval_seconds}s. Ctrl+C para salir.")
    try:
        c.scheduler.run_forever()
    except KeyboardInterrupt:
        c.scheduler.stop()
    return 0


def cmd_traceroute(args) -> int:
    c = _container(args)
    devices, _ = c.devices.get_all()
    if args.ip:
        devices = [d for d in devices if any(t.ip == args.ip for t in d.targets)]
        if not devices:
            print(f"No hay equipos con IP {args.ip}")
            return 1
        for d in devices:
            for res in c.traceroute.trace_device(d):
                print(f"\n{res.device_name} → {res.ip} ({'alcanzado' if res.reached else 'NO alcanzado'})")
                for h in res.hops:
                    print(f"  {h.number:>2}  {h.ip or '*':<16} {h.rtt_ms if h.rtt_ms is not None else '*'} ms")
        return 0
    print(f"{c.traceroute.trace_all(devices)} rutas medidas.")
    return 0


def cmd_report(args) -> int:
    from nemesis.services.metrics import ReportFilter
    c = _container(args)
    f = ReportFilter.last(hours=args.days * 24, sites=args.site or (), types=args.type or ())
    for fmt in args.format:
        _, _, path = c.reports.generate(fmt, f)
        print(f"[OK] {fmt}: {path}")
    return 0


def cmd_validate(args) -> int:
    c = _container(args)
    issues = c.admin.validate_all()
    for i in issues:
        print(f"[{i.severity.value:<7}] {i.file:<25} {i.device[:40]:<40} {i.message}")
    print(f"\n{len(issues)} observaciones.")
    return 1 if any(i.severity.value == "ERROR" for i in issues) else 0


def cmd_set_admin(args) -> int:
    c = _container(args)
    user = input("Usuario: ").strip() or "admin"
    pwd = getpass.getpass("Clave (mín. 8): ")
    if pwd != getpass.getpass("Repetir clave: "):
        print("Las claves no coinciden")
        return 1
    c.auth.set_credentials(user, pwd)
    print("Credenciales guardadas.")
    return 0


def cmd_app(args) -> int:
    from nemesis.launcher import run
    return run(mode=args.mode, lan=args.lan, port=args.port)


def cmd_demo(args) -> int:
    if not args.db and not args.force:
        print("Por seguridad indicá una base aparte: --db data/demo.db (o --force para usar la real).")
        return 1
    c = _container(args)
    logging.getLogger("nemesis.services").setLevel(logging.ERROR)
    from nemesis.demo import generate_demo_history
    n = generate_demo_history(c, days=args.days, step_minutes=args.step)
    print(f"{n} ciclos generados en {c.store.path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nemesis", description="Nemesis Monitor")
    p.add_argument("--settings", help="ruta a settings.toml")
    p.add_argument("--db", help="base SQLite alternativa (ej. data/demo.db)")
    p.add_argument("--simulated", action="store_true", help="usar probes simulados (sin red)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("check", help="ejecuta un ciclo y muestra el resultado")
    s.add_argument("--no-save", action="store_true", help="no guardar en el histórico")
    s.set_defaults(func=cmd_check)

    sub.add_parser("collect", help="colector continuo").set_defaults(func=cmd_collect)

    s = sub.add_parser("traceroute", help="mide saltos")
    s.add_argument("--ip")
    s.set_defaults(func=cmd_traceroute)

    s = sub.add_parser("report", help="genera reportes")
    s.add_argument("--format", nargs="+", default=["pdf"], choices=["pdf", "excel", "powerbi"])
    s.add_argument("--days", type=float, default=7)
    s.add_argument("--site", nargs="*")
    s.add_argument("--type", nargs="*")
    s.set_defaults(func=cmd_report)

    for name, mode, desc in (("app", "app", "abre la app en una ventana propia"),
                             ("web", "web", "abre el dashboard en el navegador (localhost)")):
        s = sub.add_parser(name, help=desc)
        s.add_argument("--lan", action="store_true", help="aceptar conexiones de otras PCs de la red")
        s.add_argument("--port", type=int)
        s.set_defaults(func=cmd_app, mode=mode)

    sub.add_parser("validate", help="valida el inventario JSON").set_defaults(func=cmd_validate)
    sub.add_parser("set-admin", help="configura usuario del panel admin").set_defaults(func=cmd_set_admin)

    s = sub.add_parser("demo-data", help="genera histórico simulado")
    s.add_argument("--days", type=int, default=7)
    s.add_argument("--step", type=int, default=5, help="minutos entre ciclos simulados")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
