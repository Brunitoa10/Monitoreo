"""Contratos de los probes (Strategy). Los monitores dependen de estas abstracciones (DIP)."""
from __future__ import annotations

import subprocess
import sys
from abc import ABC, abstractmethod
from typing import Callable, Sequence

from nemesis.domain.models import ProbeResult, Target, TracerouteHop

IS_WINDOWS = sys.platform.startswith("win")

CommandRunner = Callable[[Sequence[str], float], str]


def run_command(args: Sequence[str], timeout: float) -> str:
    """Ejecuta un comando del sistema sin abrir ventanas y devuelve stdout+stderr.

    Se decodifica como latin-1 porque la consola de Windows en español usa cp850;
    sólo nos interesan números e IPs, que son ASCII.
    """
    kwargs = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            list(args), capture_output=True, timeout=timeout, check=False, **kwargs
        )
        return (completed.stdout + completed.stderr).decode("latin-1", errors="ignore")
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"") + (exc.stderr or b"")
        return out.decode("latin-1", errors="ignore")
    except FileNotFoundError:
        return ""


class Probe(ABC):
    """Mide un Target y devuelve un ProbeResult."""

    method: str = "icmp"

    @abstractmethod
    def probe(self, target: Target) -> ProbeResult:
        ...


class Tracer(ABC):
    """Calcula la ruta (saltos) hasta una IP."""

    @abstractmethod
    def trace(self, ip: str) -> tuple[list[TracerouteHop], bool]:
        ...
