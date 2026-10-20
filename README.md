# Nemesis Monitor 2.0 (Python)

Monitoreo de switches, enlaces, cartelería, impresoras y UPS a partir de los mismos JSON de
`Config/Sites`, con histórico, métricas ejecutivas, incidentes, saltos de red y reportes
PDF / Excel / Power BI. La versión PowerShell sigue en la carpeta (no se tocó).

## Uso (100% portable, sin instalar nada)

La carpeta incluye su propio Python 3.12.9 (distribución embebible oficial, binarios firmados por la
Python Software Foundation) con todas las librerías. No se instala nada, no requiere administrador,
no toca el registro ni el perfil del usuario: todo (datos, reportes, logs, caché) queda dentro de la carpeta.
Se puede copiar a otra PC o a un pendrive y funciona igual. Requiere Windows 10/11 de 64 bits.

| Archivo | Para qué |
|---|---|
| `abrir_app.bat` | **Modo app**: ventana nativa de Windows (WebView2, ya incluido en Windows 10/11), sin consola ni navegador. Cerrar la ventana apaga todo. Si WebView2 no está disponible usa Edge en modo aplicación |
| `abrir_web.bat` | **Modo web**: `http://localhost:8501` en el navegador. `abrir_web.bat --lan` lo expone a la red |
| `nemesis.bat` | Consola: `nemesis.bat check`, `validate`, `report --format pdf excel powerbi --days 7`, `traceroute --ip X` |
| `colector.bat` | Sólo mide, sin interfaz (Programador de tareas) |
| `crear_acceso_directo.bat` | Acceso directo "Nemesis Monitor" en el Escritorio |

`_entorno.bat` descomprime cada `runtime_pkg\runtime-XX.zip` una sola vez en `runtime\` (con el `tar` que trae
Windows); si se agrega una parte nueva, la incorpora sola. Una vez descomprimido se puede borrar `runtime_pkg`.

Todo corre en `127.0.0.1` (sólo esta PC, sin pedir firewall). Puerto y modo en `settings.toml` → `[ui]`.


Para desarrollo (opcional) sigue sirviendo `requirements.txt` con un Python propio.

## Primer uso: inventario vacío

El proyecto se entrega **sin ninguna IP ni nombre de equipo**. Al abrir `abrir_app.bat` el monitoreo arranca
vacío; los equipos se cargan desde **Administración**:
- **Alta manual**: tipo, nombre, sitio e IP (o IP Padre/Hijo para enlaces).
- **Importar JSON**: uno o varios archivos con cualquier estructura (ver formatos aceptados en la misma pantalla).

## Inventario: JSON, base de datos o carga manual

Sirve para cualquier empresa: nada está atado a nombres de sitios ni de equipos.

- **Origen**: archivos JSON (uno por sector) o base de datos SQLite local. Se elige en
  Administración → Organización y se pueden copiar los datos de uno al otro.
- **Alta manual** (perfil administrador): tipo, nombre, sitio e IP (o IP Padre/Hijo para enlaces).
  El equipo va solo al sector que corresponde.
- **Importar JSON**: uno o varios archivos, con vista previa antes de confirmar. Cada equipo se ubica en
  su sector según el tipo, tolerando variantes y errores ("swicht", "Switches", "cartelería",
  "impresora", "radioenlace"...). Si no trae tipo se deduce de la sección (`{"ups": [...]}`) o del nombre
  del archivo (`ups_planta.json`). Campos aceptados: Name/nombre/equipo, Site/sitio/sector/ubicacion,
  IPAddress/ip/direccion_ip/host, Type/tipo/categoria, ip_padre/ip_hijo. Si el equipo ya existe
  (mismo tipo e IP, o mismo nombre y sitio) se actualiza, se omite o se duplica, a elección.
  Un tipo desconocido crea su propio sector.
- **Edición en tabla** por sector, con validación (IP duplicada/ inválida, sitios escritos distinto) y
  respaldo automático antes de cada cambio. **Exportar** el inventario completo o por sector.
- Tipos, alias y archivos por sector se pueden ampliar en `settings.toml` → `[types.<Tipo>]`.
- Nombre de la app, organización e intervalo se personalizan desde el panel (`data\overrides.json`).

## Auditoría de fallas

Página **Auditoría** (y hoja/sección en Excel, PDF y Power BI): una fila por falla con
**fecha y hora (hh:mm:ss) de caída**, **fecha y hora de recuperación**, **duración** (d h min s),
**último chequeo OK** antes de la caída, severidad (caída / degradación) y estado (recuperado / sin recuperar).
Incluye totales por equipo (cantidad de fallas, tiempo total con falla, falla más larga) y exportación a Excel/CSV.
La precisión es el intervalo de chequeo: el corte ocurrió entre «Último OK» y «Hora caída».

## Qué mide

| Métrica | Cómo |
|---|---|
| Disponibilidad | % de chequeos en que respondió (Operativo o Degradado) |
| Latencia prom / p95 / máx | `ping -n 3` por equipo (y por extremo Padre/Hijo en enlaces) |
| Jitter | desvío estándar del RTT de los 3 paquetes |
| Pérdida | paquetes perdidos cuando el equipo responde |
| Saltos | estimados por TTL en cada ciclo + `tracert -d` real cada 60 min (y a demanda) |
| Incidentes, MTTR, MTBF, tiempo con falla | se confirma tras 2 ciclos fallidos seguidos (anti-flapping), pero se fecha en el **primer** chequeo fallido |
| Health score | 0–100 combinando disponibilidad, pérdida y equipos caídos |

Estados: **Operativo**, **Degradado** (latencia/pérdida/jitter sobre umbral o enlace con un solo extremo),
**Caído**, **Disponible** (equipos con nombre/sitio "Disponible": no cuentan en la disponibilidad).

## CLI

```
python -m nemesis check | collect | traceroute [--ip IP] | validate | set-admin
python -m nemesis report --format pdf excel powerbi --days 7 [--site "Casa Central"] [--type Switch]
python -m nemesis demo-data --days 7 --db data\demo.db
```

## Arquitectura

```
nemesis/
  domain/            reglas puras, sin I/O
    models.py          Device, Target, ProbeResult, HealthResult, Incident, Insight...
    device_mapper.py   JSON original -> Device (cualquier "IPAddress_<Rol>" es un extremo)
    status_policy.py   Strategy: cómo se decide el estado según umbrales
    validation.py      reglas de calidad de datos (una clase por regla)
  infrastructure/
    probes/            Strategy: ping, tcp, traceroute (reales y simulados) + parsers ES/EN
    repositories/      Repository: JSON (inventario, escritura atómica + backup) y SQLite (histórico)
  monitors.py        Template Method + Registry/Factory por tipo de equipo
  core/events.py     Observer: CycleCompleted, IncidentOpened/Escalated/Closed
  services/          casos de uso: monitoring (Facade), incidents, notifications (Teams/Slack),
                     traceroute, scheduler (lease para un solo colector), metrics, insights, admin
  reporting/         Strategy por formato: PdfExporter, ExcelExporter, PowerBiExporter
  container.py       Composition Root (inyección de dependencias manual)
  ui/                Streamlit: resumen ejecutivo, en vivo, por equipo, incidentes, reportes, admin
```

SOLID en concreto:
- **S**: cada clase hace una cosa (medir, decidir estado, persistir, notificar, exportar).
- **O**: nuevo tipo de equipo = registrarlo en `build_registry`; nuevo formato = otro `ReportExporter`;
  nueva recomendación = otra `InsightRule`; nueva validación = otra `ValidationRule`.
- **L**: todos los `Probe`, `Monitor`, `Notifier` y `ReportExporter` son intercambiables.
- **I**: contratos chicos (`probe()`, `trace()`, `send()`, `export()`).
- **D**: los servicios reciben abstracciones por constructor; sólo `container.py` conoce las clases concretas.

## Configuración

Todo en `settings.toml`: intervalo, paralelismo, umbrales por tipo, puertos TCP opcionales
(ej. 9100 en impresoras), retención, traceroute y webhook de Teams/Slack.
Para verlo desde otras PCs: `abrir_web.bat --lan` o `host = "0.0.0.0"` en `[ui]`.

## Tests

```bat
python -m pytest -q        (con un Python de desarrollo + requirements.txt)
```
