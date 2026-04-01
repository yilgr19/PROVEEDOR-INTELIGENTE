"""Rutas locales: datos solo en el equipo (sin hosting)."""
from __future__ import annotations

from pathlib import Path

# Carpeta del paquete proveedor_inteligente/
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
# Carpeta del repositorio (donde están run.py, requirements.txt…)
PROJECT_ROOT = _PACKAGE_ROOT.parent


def get_db_path() -> Path:
    """Base SQLite en la raíz del proyecto (junto a run.py), no en AppData."""
    return PROJECT_ROOT / "datos_empresa.db"


def get_flet_cache_dir() -> Path:
    """Caché del cliente Flet en el proyecto (evita ~/.flet no escribible)."""
    d = PROJECT_ROOT / ".flet_cache" / "client"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_app_icon_path() -> Path | None:
    """Icono de ventana (Windows: .ico en la raíz del repo, carpeta assets/)."""
    p = PROJECT_ROOT / "assets" / "app_icon.ico"
    return p if p.is_file() else None
