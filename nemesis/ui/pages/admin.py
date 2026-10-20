"""Panel de administración: login, inventario (JSON o base), alta manual, importación
inteligente por sector, calidad de datos, organización y sistema."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from nemesis.config import save_overrides
from nemesis.container import Container
from nemesis.domain.device_mapper import CANONICAL_KEYS
from nemesis.domain.enums import IssueSeverity
from nemesis.domain.models import ValidationIssue
from nemesis.infrastructure.repositories.inventory import ORIGIN
from nemesis.services.metrics import ReportFilter
from nemesis.ui import components as ui
from nemesis.ui.context import reload_app

SESSION_KEY = "admin_until"
SEVERITY_ICON = {IssueSeverity.ERROR: "⛔", IssueSeverity.WARNING: "⚠️", IssueSeverity.INFO: "ℹ️"}
ACTION_ICON = {"nuevo": "🆕 nuevo", "actualiza": "✏️ actualiza", "omite": "⏭️ omite"}
BACKENDS = {"json": "Archivos JSON (un archivo por sector)", "sqlite": "Base de datos (SQLite local)"}


# ======================================================================= login
def _logged_in() -> bool:
    until = st.session_state.get(SESSION_KEY)
    return bool(until and until > datetime.now())


def _login(c: Container) -> None:
    ui.header("Administración", "Acceso restringido")
    auth = c.auth
    with st.container(border=True):
        if not auth.is_configured:
            st.info("Primer ingreso: creá el usuario administrador.")
            with st.form("setup"):
                user = st.text_input("Usuario", value="admin")
                p1 = st.text_input("Clave (mín. 8 caracteres)", type="password")
                p2 = st.text_input("Repetir clave", type="password")
                if st.form_submit_button("Crear administrador", type="primary"):
                    if p1 != p2:
                        st.error("Las claves no coinciden")
                    else:
                        try:
                            auth.set_credentials(user, p1)
                            st.success("Administrador creado. Ingresá con tus credenciales.")
                        except ValueError as exc:
                            st.error(str(exc))
            return
        with st.form("login"):
            user = st.text_input("Usuario")
            pwd = st.text_input("Clave", type="password")
            if st.form_submit_button("Ingresar", type="primary"):
                if auth.verify(user, pwd):
                    st.session_state[SESSION_KEY] = datetime.now() + timedelta(minutes=c.settings.admin_session_minutes)
                    st.rerun()
                else:
                    time.sleep(1)  # frena fuerza bruta
                    st.error("Usuario o clave incorrectos")


# ===================================================================== helpers
def _issues_df(issues: list[ValidationIssue]) -> pd.DataFrame:
    return pd.DataFrame([{"": SEVERITY_ICON[i.severity], "Severidad": i.severity.value, "Origen": i.file,
                          "Equipo": i.device, "Campo": i.field, "Detalle": i.message} for i in issues])


def _show_issues(issues: list[ValidationIssue], only_problems: bool = True) -> None:
    shown = [i for i in issues if not only_problems or i.severity != IssueSeverity.INFO]
    if shown:
        st.dataframe(_issues_df(shown), hide_index=True, width="stretch", height=min(400, 36 * len(shown) + 40))


def _type_options(c: Container) -> list[str]:
    c.admin.records()  # registra tipos nuevos encontrados en el inventario
    return c.catalog.names


# ================================================================== inventario
def _inventory(c: Container) -> None:
    records = c.admin.records()
    sectors = c.admin.sectors()
    st.caption(f"📦 {c.devices.describe()} · {len(records)} equipos en {len(sectors)} sectores")

    if sectors:
        cols = st.columns(min(6, len(sectors)))
        for i, (t, n) in enumerate(sectors.items()):
            with cols[i % len(cols)]:
                ui.kpi(c.catalog.label(t), str(n), t)
    st.write("")

    choice = st.radio("Sector", ["Todos"] + list(sectors), horizontal=True,
                      format_func=lambda t: t if t == "Todos" else c.catalog.label(t))
    df = pd.DataFrame(records) if records else pd.DataFrame(columns=list(CANONICAL_KEYS) + [ORIGIN])
    for key in ("Type", "Name", "Site", "IPAddress", ORIGIN):
        if key not in df.columns:
            df[key] = None
    df = df.drop(columns=["_id"], errors="ignore")
    visible = df if choice == "Todos" else df[df["Type"] == choice]
    hidden = df.drop(visible.index)
    if choice != "Todos" and not c.catalog.roles_for(choice):
        empty_cols = [col for col in visible.columns if col.startswith("IPAddress_") and visible[col].isna().all()]
        visible = visible.drop(columns=empty_cols)
    role_cols = sorted((col for col in visible.columns if col.startswith("IPAddress_")),
                       key=lambda col: (col != "IPAddress_Padre", col))
    order = ["Type", "Name", "Site", "IPAddress"] + role_cols
    order += [col for col in visible.columns if col not in order and col != ORIGIN] + [ORIGIN]
    visible = visible[[col for col in order if col in visible.columns]]

    st.caption("Editá celdas, agregá filas al final (se ubican solas en su sector según el Tipo) o seleccioná "
               "filas y borralas con Supr. Si cambiás el Tipo de un equipo, se mueve de sector.")
    edited = st.data_editor(
        visible, num_rows="dynamic", width="stretch", hide_index=True, key=f"inv_{choice}",
        column_config={
            "Type": st.column_config.SelectboxColumn("Tipo / sector", options=_type_options(c), required=True),
            "Name": st.column_config.TextColumn("Nombre", required=True, width="medium"),
            "Site": st.column_config.TextColumn("Sitio"),
            "IPAddress": st.column_config.TextColumn("IP / host"),
            ORIGIN: st.column_config.TextColumn("Guardado en", disabled=True,
                                                help="Archivo o base donde está el equipo (automático)"),
        },
        height=min(620, 36 * (len(visible) + 2) + 40),
    )
    a, b, _ = st.columns([1, 1.4, 2])
    force = b.checkbox("Guardar aunque haya errores", key="inv_force",
                       help="Útil si los errores ya existían y los vas corrigiendo de a poco")
    if a.button("💾 Guardar cambios", type="primary", width="stretch"):
        rows = pd.concat([hidden, edited], ignore_index=True).to_dict("records")
        result = c.admin.save_table(rows, force=force)
        if result.saved:
            st.success(f"Inventario guardado ({len(result.backups)} respaldos). El monitoreo lo toma en el próximo ciclo.")
        else:
            st.error("No se guardó: hay errores. Corregilos o marcá 'Guardar aunque haya errores'.")
        _show_issues(result.issues)

    st.divider()
    e1, e2 = st.columns(2)
    e1.download_button("⬇️ Exportar todo el inventario (JSON por sector)", c.admin.export_json(),
                       file_name=f"inventario_{datetime.now():%Y%m%d}.json", mime="application/json", width="stretch")
    if choice != "Todos":
        e2.download_button(f"⬇️ Exportar sólo {c.catalog.label(choice)}", c.admin.export_json(choice),
                           file_name=c.catalog.file_for(choice), mime="application/json", width="stretch")


# ================================================================ alta manual
def _manual(c: Container) -> None:
    st.caption("El equipo se guarda automáticamente en el sector que corresponde a su tipo.")
    types = _type_options(c)
    t = st.selectbox("Tipo / sector", types + ["➕ Otro (nuevo sector)"], key="new_type")
    if t.startswith("➕"):
        t = st.text_input("Nombre del nuevo tipo", placeholder="Ej: Reloj de fichaje, Sensor, NVR...")
    roles = c.catalog.roles_for(t) if t else ()
    with st.form("alta", clear_on_submit=True):
        c1, c2 = st.columns(2)
        name = c1.text_input("Nombre *", placeholder="Ej: Hall planta baja")
        site = c2.text_input("Sitio / ubicación *", placeholder="Ej: Sede central")
        ips = {}
        if roles:
            cols = st.columns(len(roles))
            for col, role in zip(cols, roles):
                ips[f"IPAddress_{role}"] = col.text_input(f"IP {role} *")
        else:
            ips["IPAddress"] = st.text_input("IP o hostname *", placeholder="10.0.0.10")
        extra = st.text_area("Datos adicionales (opcional, uno por línea: Campo=Valor)", placeholder="Modelo=Cisco 2960\nSerie=FOC123")
        force = st.checkbox("Guardar aunque haya advertencias de error (ej. IP duplicada)")
        if st.form_submit_button("➕ Agregar equipo", type="primary"):
            if not (t and name and site and all(ips.values())):
                st.error("Completá los campos obligatorios (*)")
                return
            data = {"Type": t, "Name": name, "Site": site, **ips}
            for line in extra.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    data[k.strip()] = v.strip()
            result = c.admin.add_device(data, force=force)
            if result.saved:
                st.success(f"'{name}' agregado al sector {c.catalog.label(t)} → {result.destination}")
            else:
                st.error("No se agregó por errores de validación:")
            _show_issues(result.issues)


# ================================================================ importación
def _import(c: Container) -> None:
    st.caption("Subí uno o varios JSON (de cualquier empresa o formato). Cada equipo se ubica solo en su sector "
               "según el campo Tipo (tolera 'swicht', 'Switches', 'cartelería', 'impresora'...). Si no trae tipo, "
               "se deduce de la sección o del nombre del archivo (ej. ups_planta.json).")
    with st.expander("Formatos aceptados"):
        st.code('''[ {"Name": "SW Core", "Site": "Sede", "IPAddress": "10.0.0.1", "Type": "Switch"} ]

{ "switches": [ {"nombre": "SW1", "sitio": "Sede", "ip": "10.0.0.2"} ],
  "ups":      [ {"nombre": "UPS rack", "ubicacion": "DC", "ip": "10.0.0.3"} ] }

{"nombre": "Enlace Norte", "tipo": "radioenlace", "ip_padre": "10.0.1.1", "ip_hijo": "10.0.1.2"}''', language="json")
    files = st.file_uploader("Archivos JSON", type=["json"], accept_multiple_files=True, key="imp_files")
    policy = st.radio("Si el equipo ya existe (mismo tipo e IP, o mismo nombre y sitio)",
                      ["update", "skip", "duplicate"], horizontal=True,
                      format_func={"update": "Actualizar datos", "skip": "Dejar como está",
                                   "duplicate": "Agregar igual (duplicar)"}.get)
    if not files:
        return
    payload = [(f.name, f.getvalue()) for f in files]
    preview = c.admin.preview_import(payload, policy)
    r = preview.result
    cols = st.columns(4)
    with cols[0]:
        ui.kpi("Leídos", str(preview.parsed), f"{len(files)} archivo(s)")
    with cols[1]:
        ui.kpi("Nuevos", str(r.count("nuevo")), "", "ok" if r.count("nuevo") else "")
    with cols[2]:
        ui.kpi("Actualizados", str(r.count("actualiza")), "", "warn" if r.count("actualiza") else "")
    with cols[3]:
        ui.kpi("Sin cambios / omitidos", str(r.count("omite")), "")

    st.markdown("**Por sector**")
    st.dataframe(pd.DataFrame([{"Sector": c.catalog.label(t), "Tipo": t, **counts} for t, counts in r.by_type.items()]).fillna(0),
                 hide_index=True, width="stretch")
    detail = pd.DataFrame([{
        "Acción": ACTION_ICON.get(a.action, a.action), "Tipo": a.record.get("Type"), "Nombre": a.record.get("Name"),
        "Sitio": a.record.get("Site"), "IP": a.record.get("IPAddress") or a.record.get("IPAddress_Padre"),
        "Destino": a.destination, "Motivo": a.reason,
    } for a in r.actions])
    st.dataframe(detail, hide_index=True, width="stretch", height=min(420, 36 * len(detail) + 40))
    if preview.warnings:
        with st.expander(f"ℹ️ {len(preview.warnings)} interpretaciones automáticas"):
            st.write("\n".join(f"- {w}" for w in preview.warnings[:200]))
    if any(i.severity != IssueSeverity.INFO for i in preview.issues):
        st.markdown("**Validación**")
        _show_issues(preview.issues)

    force = st.checkbox("Importar aunque haya errores de validación", key="imp_force")
    disabled = not (r.count("nuevo") or r.count("actualiza")) or (bool(preview.blocking) and not force)
    if st.button("📥 Confirmar importación", type="primary", disabled=disabled):
        done = c.admin.apply_import(payload, policy, force=force)
        st.success(f"Importado: {done.result.count('nuevo')} nuevos, {done.result.count('actualiza')} actualizados. "
                   f"Respaldo previo: {', '.join(done.result.backups) or 'no hizo falta'}")


# ==================================================================== calidad
def _quality(c: Container) -> None:
    issues = c.admin.validate_all()
    if not issues:
        st.success("Inventario sin observaciones. ✅")
        return
    errors = sum(i.severity == IssueSeverity.ERROR for i in issues)
    warnings = sum(i.severity == IssueSeverity.WARNING for i in issues)
    cols = st.columns(3)
    with cols[0]:
        ui.kpi("Errores", str(errors), "IP duplicadas / inválidas, campos faltantes", "bad" if errors else "ok")
    with cols[1]:
        ui.kpi("Advertencias", str(warnings), "nombres repetidos, sitios parecidos", "warn" if warnings else "ok")
    with cols[2]:
        ui.kpi("Info", str(len(issues) - errors - warnings), "posibles errores de tipeo / tipos nuevos")
    st.dataframe(_issues_df(issues), hide_index=True, width="stretch", height=min(600, 36 * len(issues) + 40))


# ======================================================= organización / sistema
def _organization(c: Container) -> None:
    s = c.settings
    st.markdown("#### Organización")
    st.caption("Personalizá la app para tu empresa. Se guarda en data/overrides.json (portable, dentro de la carpeta).")
    with st.form("org"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Nombre de la aplicación", value=s.app.name)
        org = c2.text_input("Organización / área (aparece en reportes)", value=s.app.organization)
        interval = c1.number_input("Intervalo de chequeo (segundos)", 10, 3600, int(s.collector.interval_seconds), 5)
        if st.form_submit_button("💾 Guardar", type="primary"):
            save_overrides({"app": {"name": name, "organization": org},
                            "collector": {"interval_seconds": int(interval)}}, s.overrides_file)
            reload_app()

    st.markdown("#### Dónde se guarda el inventario")
    current = s.inventory.backend if s.inventory.backend in BACKENDS else "json"
    st.caption(f"Actual: **{BACKENDS[current]}** — {c.devices.describe()}")
    target = st.radio("Origen de datos", list(BACKENDS), index=list(BACKENDS).index(current),
                      format_func=BACKENDS.get, horizontal=True)
    if target != current:
        copy = st.checkbox(f"Copiar los {len(c.admin.records())} equipos actuales al nuevo origen", value=True,
                           help="Si no se copia, el nuevo origen arranca con lo que ya tenga.")
        if st.button(f"Cambiar a {BACKENDS[target]}", type="primary"):
            if copy:
                n = c.admin.copy_to(c.inventory_repository(target))
                st.success(f"{n} equipos copiados")
            save_overrides({"inventory": {"backend": target}}, s.overrides_file)
            reload_app()


def _system(c: Container) -> None:
    s = c.settings
    stats = c.store.stats()
    first, last = c.store.data_range()
    cols = st.columns(4)
    with cols[0]:
        ui.kpi("Mediciones", f"{stats['checks']:,}", f"{stats['size_mb']} MB en disco")
    with cols[1]:
        ui.kpi("Incidentes", f"{stats['incidents']:,}", "")
    with cols[2]:
        ui.kpi("Traceroutes", f"{stats['traceroutes']:,}", f"cada {s.probe.traceroute_interval_minutes} min")
    with cols[3]:
        ui.kpi("Histórico", f"{(last - first).days if first and last else 0} días", f"retención {s.collector.retention_days} días")

    st.write("")
    a, b, d = st.columns(3)
    if a.button("🛰️ Traceroute de todo el inventario", width="stretch"):
        with st.spinner("Midiendo saltos (puede tardar)..."):
            n = c.traceroute.trace_all()
        st.success(f"{n} rutas medidas")
    if b.button("🧹 Purgar histórico vencido", width="stretch"):
        n = c.store.purge(datetime.now() - timedelta(days=s.collector.retention_days))
        st.success(f"{n} mediciones eliminadas")
    if d.button("🔒 Cerrar sesión", width="stretch"):
        st.session_state.pop(SESSION_KEY, None)
        st.rerun()

    with st.expander("Cambiar clave de administrador"):
        with st.form("chg"):
            user = st.text_input("Usuario", value="admin")
            p1 = st.text_input("Nueva clave", type="password")
            p2 = st.text_input("Repetir", type="password")
            if st.form_submit_button("Actualizar"):
                if p1 != p2:
                    st.error("No coinciden")
                else:
                    try:
                        c.auth.set_credentials(user, p1)
                        st.success("Clave actualizada")
                    except ValueError as exc:
                        st.error(str(exc))

    with st.expander("Configuración activa"):
        st.caption(f"settings.toml: {s.source_file or 'valores por defecto'} · ajustes del panel: {s.overrides_file}")
        st.json({
            "inventario": s.inventory.__dict__, "collector": s.collector.__dict__, "probe": s.probe.__dict__,
            "umbrales_default": s.default_thresholds.__dict__,
            "umbrales_por_tipo": {k: v.__dict__ for k, v in s.type_thresholds.items()},
            "tipos": {t.name: {"sector": t.label, "archivo": t.file, "alias": list(t.aliases)[:8]} for t in c.catalog.types},
            "tcp_ports": s.tcp_ports,
            "webhook": "configurado" if s.notifications.webhook_url else "desactivado",
            "rutas": {k: str(v) for k, v in s.paths.__dict__.items()},
        })


def render(c: Container, f: ReportFilter) -> None:
    if not _logged_in():
        _login(c)
        return
    until = st.session_state[SESSION_KEY]
    ui.header("Administración", f"Sesión activa hasta {until:%H:%M}")
    tabs = st.tabs(["📋 Inventario", "➕ Alta manual", "📥 Importar JSON", "🔎 Calidad de datos",
                    "🏢 Organización", "⚙️ Sistema"])
    with tabs[0]:
        _inventory(c)
    with tabs[1]:
        _manual(c)
    with tabs[2]:
        _import(c)
    with tabs[3]:
        _quality(c)
    with tabs[4]:
        _organization(c)
    with tabs[5]:
        _system(c)
