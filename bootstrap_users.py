"""
Usuarios iniciales (opcional). Tercer elemento del rol: "admin" o "user" (usuario).
Si solo indica (usuario, contraseña), se asume rol administrador para ese arranque.
Los administradores pueden crear más usuarios desde la aplicación.
"""
from __future__ import annotations

USUARIOS_DESDE_CODIGO: list[tuple[str, str] | tuple[str, str, str]] = [
    # Administrador inicial — cambie la contraseña al entrar (Administración de usuarios).
    ("admin", "Proveedor2026!", "admin"),
    # ("operador1", "OtraClaveSegura12", "user"),
]
