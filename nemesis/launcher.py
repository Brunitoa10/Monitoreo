"""Lanzador local de Nemesis Monitor.

Modos:
  app  -> ventana de escritorio propia (pywebview si está instalado; si no, Edge en modo --app).
          Al cerrar la ventana se apaga el servidor.
  web  -> servidor en localhost y se abre el navegador por defecto. Se corta con Ctrl+C.

Por defecto escucha SOLO en 127.0.0.1: nadie de la red corporativa puede entrar y
Windows no pide permiso de firewall. Para exponerlo en la LAN: --lan (o host en settings.toml).
"""
from __future__ import annotations

import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from nemesis.config import PROJECT_ROOT, load_settings

log = logging.getLogger("nemesis.launcher")
DASHBOARD = PROJECT_ROOT / "dashboard.py"

EDGE_PATHS = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
]
CHROME_PATHS = [
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
]


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _pick_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 50):
        if _port_free(host, port):
            return port
    raise RuntimeError(f"No hay puertos libres entre {preferred} y {preferred + 49}")


def _already_running(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/_stcore/health", timeout=1) as r:
            return r.status == 200
    except OSError:
        return False


def _wait_ready(url: str, server: subprocess.Popen, timeout: float = 240, log_file: Path | None = None) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if server.poll() is not None:
            detail = ""
            if log_file and log_file.exists():
                lines = log_file.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
                detail = lines[-1] if lines else ""
            raise RuntimeError(f"El servidor se cerró al iniciar. {detail} (ver {log_file or 'launcher.log'})")
        if _already_running(url):
            return
        time.sleep(0.4)
    raise TimeoutError(f"El servidor no respondió en {timeout:.0f}s")


def start_server(host: str, port: int, log_file: Path, idle_exit: bool = False) -> subprocess.Popen:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "nemesis.serve", str(DASHBOARD),
        "--server.address", host,
        "--server.port", str(port),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
        "--global.developmentMode", "false",
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    out = open(log_file, "a", encoding="utf-8")
    # El servidor vigila este PID y se apaga solo si el lanzador muere (ej. se cierra la consola).
    env = {**os.environ, "NEMESIS_PARENT_PID": str(os.getpid()), "NEMESIS_IDLE_EXIT": "1" if idle_exit else "0"}
    return subprocess.Popen(cmd, cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                            creationflags=flags, env=env)


def _install_signal_handlers() -> None:
    """Cerrar la consola (SIGBREAK en Windows) o SIGTERM se tratan como Ctrl+C -> apagado limpio."""
    def handler(*_):
        raise KeyboardInterrupt
    for name in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), handler)


def stop_server(server: subprocess.Popen) -> None:
    if server.poll() is None:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


# ------------------------------------------------------------ ventanas
LOADING_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
font-family:Segoe UI,sans-serif;background:#f8fafc;color:#0f172a}
.b{text-align:center}.t{font-size:22px;font-weight:700;margin-bottom:6px}.s{color:#64748b;font-size:13px}
.sp{width:34px;height:34px;border:3px solid #e2e8f0;border-top-color:#1e3a8a;border-radius:50%;
margin:0 auto 16px;animation:r 0.9s linear infinite}@keyframes r{to{transform:rotate(360deg)}}
</style></head><body><div class="b"><div class="sp"></div><div class="t">%TITLE%</div>
<div class="s">Iniciando… la primera vez puede tardar unos segundos</div></div></body></html>"""


def _open_native_window(title: str, url_when_ready, storage: Path) -> bool:
    """Ventana nativa de Windows (pywebview + WebView2, incluido en Windows 10/11).

    Se abre al instante con una pantalla de carga y navega a la app cuando el servidor
    está listo. Bloquea hasta que el usuario cierra la ventana. False si no se puede usar.
    """
    try:
        if os.name == "nt":
            dll = Path(sys.executable).parent / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
            if dll.exists():
                os.environ.setdefault("PYTHONNET_PYDLL", str(dll))
        import webview
    except Exception as exc:  # pywebview/pythonnet no disponibles
        log.warning("Ventana nativa no disponible: %s", exc)
        return False

    window = webview.create_window(title, html=LOADING_HTML.replace("%TITLE%", title), width=1440, height=900,
                                   min_size=(1000, 650), text_select=True)

    def navigate() -> None:
        try:
            window.load_url(url_when_ready())
        except Exception as exc:
            log.exception("No se pudo iniciar el servidor")
            window.load_html(f"<h3 style='font-family:Segoe UI'>No se pudo iniciar: {exc}</h3>"
                             "<p style='font-family:Segoe UI'>Revisá Logs/app.log</p>")

    storage.mkdir(parents=True, exist_ok=True)
    try:
        kwargs = {"private_mode": False, "storage_path": str(storage)}
        if os.name == "nt":
            kwargs["gui"] = "edgechromium"
        webview.start(navigate, **kwargs)
        return True
    except Exception as exc:
        log.warning("No se pudo abrir la ventana nativa (¿falta WebView2 Runtime?): %s", exc)
        return False


def _open_app_browser(url: str, profile_dir: Path) -> bool:
    """Abre Edge/Chrome en modo aplicación (sin pestañas) con un perfil propio, sin esperar al proceso."""
    exe = next((p for p in EDGE_PATHS + CHROME_PATHS if p.exists()), None)
    exe = exe or (Path(shutil.which("msedge")) if shutil.which("msedge") else None)
    if not exe:
        return False
    profile_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([
        str(exe), f"--app={url}", f"--user-data-dir={profile_dir}",
        "--no-first-run", "--no-default-browser-check", "--window-size=1440,900",
    ])
    _log(f"Ventana abierta con {exe.name} ({url})")
    return True


def _log(msg: str) -> None:
    if sys.stdout:
        print(msg)
    log.info(msg)


def _setup_file_log(logs_dir: Path) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(logs_dir / "app.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def run(mode: str = "app", lan: bool = False, port: int | None = None) -> int:
    settings = load_settings()
    _setup_file_log(settings.paths.logs_dir)
    host = "0.0.0.0" if lan else settings.ui.host
    port = port or settings.ui.port
    browse_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    log_file = settings.paths.logs_dir / "launcher.log"

    existing = f"http://{browse_host}:{port}"
    if _already_running(existing):
        # Ya hay una instancia: sólo abrimos otra ventana/pestaña hacia ella.
        print(f"Nemesis ya está corriendo en {existing}")
        if mode == "app" and (_open_native_window(settings.app.name, lambda: existing,
                                                  settings.paths.database.parent / "webview")
                              or _open_app_browser(existing, settings.paths.database.parent / f"app-profile-{port}")):
            return 0
        webbrowser.open(existing)
        return 0

    _install_signal_handlers()
    port = _pick_port(host if host != "0.0.0.0" else "127.0.0.1", port)
    url = f"http://{browse_host}:{port}"
    data_dir = settings.paths.database.parent
    server = start_server(host, port, log_file, idle_exit=(mode == "app"))
    try:
        log.info("Iniciando %s en %s (modo %s)", settings.app.name, url, mode)
        print(f"Iniciando {settings.app.name} en {url} ...")
        if lan:
            print(f"Accesible en la red: http://{socket.gethostname()}:{port}")

        if mode == "app":
            def ready_url() -> str:
                _wait_ready(url, server, log_file=log_file)
                return url
            if _open_native_window(settings.app.name, ready_url, data_dir / "webview"):
                return 0  # el usuario cerró la ventana -> finally apaga el servidor
            _wait_ready(url, server, log_file=log_file)
            if _open_app_browser(url, data_dir / f"app-profile-{port}"):
                print("Ventana abierta en modo aplicación de Edge. Al cerrarla se apaga sola.")
                while server.poll() is None:
                    time.sleep(1)
                return 0

        _wait_ready(url, server, log_file=log_file)
        webbrowser.open(url)
        print(f"Dashboard en {url}. Dejá esta ventana abierta; Ctrl+C para salir.")
        while server.poll() is None:
            time.sleep(1)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        stop_server(server)
        print("Servidor detenido.")


def parent_alive(pid: int) -> bool:
    """Chequea si un proceso existe sin matarlo (en Windows os.kill(pid, 0) lo terminaría)."""
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start_parent_watchdog(interval: float = 3.0) -> None:
    """Se ejecuta dentro del servidor Streamlit: si el lanzador desaparece, se apaga."""
    import threading
    pid = os.environ.get("NEMESIS_PARENT_PID")
    if not pid or not pid.isdigit():
        return

    def watch() -> None:
        while True:
            time.sleep(interval)
            if not parent_alive(int(pid)):
                log.info("Lanzador cerrado: apagando servidor")
                os._exit(0)

    threading.Thread(target=watch, name="nemesis-parent-watchdog", daemon=True).start()


def _active_sessions() -> int | None:
    """Ventanas conectadas. NO importa streamlit desde este hilo: sólo lee módulos ya cargados.
    (Importarlo en paralelo con el hilo principal provocaba un import circular al arrancar.)"""
    mod = sys.modules.get("streamlit.runtime")
    runtime_cls = getattr(mod, "Runtime", None) if mod else None
    if runtime_cls is None:
        return None
    try:
        if not runtime_cls.exists():
            return None
        return runtime_cls.instance()._session_mgr.num_active_sessions()
    except Exception:
        return None


def start_idle_watchdog(grace_seconds: float = 15, first_connect_timeout: float = 180) -> None:
    """Modo app: el servidor se apaga solo cuando no queda ninguna ventana conectada.

    No dependemos del proceso de Edge (msedge.exe suele delegar en otro proceso y
    terminar enseguida). Se espera hasta 3 min a la primera conexión y, una vez
    conectada, 15 s sin ventanas abiertas (tolera recargas de página).
    """
    import threading
    if os.environ.get("NEMESIS_IDLE_EXIT") != "1":
        return

    def watch() -> None:
        start = time.time()
        seen = False
        idle_since: float | None = None
        while True:
            time.sleep(2)
            n = _active_sessions()
            if n is None:
                continue
            if n > 0:
                seen, idle_since = True, None
                continue
            now = time.time()
            if not seen and now - start > first_connect_timeout:
                log.info("Ninguna ventana se conectó: apagando servidor")
                os._exit(0)
            if seen:
                idle_since = idle_since or now
                if now - idle_since > grace_seconds:
                    log.info("Ventana cerrada: apagando servidor")
                    os._exit(0)

    threading.Thread(target=watch, name="nemesis-idle-watchdog", daemon=True).start()
