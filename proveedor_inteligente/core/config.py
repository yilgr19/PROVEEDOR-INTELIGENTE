"""Rutas locales: datos solo en el equipo (sin hosting)."""
from __future__ import annotations

import os
from pathlib import Path

_APP_NAME = "ProveedorInteligente"

# Carpeta del paquete proveedor_inteligente/
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
# Carpeta del repositorio (donde están run.py, requirements.txt…)
PROJECT_ROOT = _PACKAGE_ROOT.parent


def get_app_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        d = Path(base) / _APP_NAME
    else:
        d = Path.home() / f".{_APP_NAME.lower()}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_db_path() -> Path:
    return get_app_dir() / "datos_empresa.db"


def get_flet_cache_dir() -> Path:
    """Caché del cliente Flet en el proyecto (evita ~/.flet no escribible)."""
    d = PROJECT_ROOT / ".flet_cache" / "client"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_app_icon_path() -> Path | None:
    """Icono de ventana (Windows: .ico en la raíz del repo, carpeta assets/)."""
    p = PROJECT_ROOT / "assets" / "app_icon.ico"
    return p if p.is_file() else None
