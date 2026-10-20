from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_CONFIGURED = False


def configure_logging(logs_dir: Path, level: int = logging.INFO) -> None:
    """Log diario rotado (30 días) + consola. Idempotente (Streamlit re-ejecuta scripts)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logs_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")

    file_handler = TimedRotatingFileHandler(
        logs_dir / "nemesis.log", when="midnight", backupCount=30, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)

    root = logging.getLogger("nemesis")
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console)
    root.propagate = False
    _CONFIGURED = True
