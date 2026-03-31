"""Rutas locales: datos solo en el equipo (sin hosting)."""
from pathlib import Path
import os

_APP_NAME = "ProveedorInteligente"


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
