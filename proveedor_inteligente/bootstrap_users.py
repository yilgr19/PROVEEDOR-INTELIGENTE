"""
Usuarios iniciales (opcional). Tercer valor del tuple = rol:

- "admin": importar/exportar Excel, gestión de usuarios, mismas consultas que un usuario.
- "user": solo consultas (referencia, precio opcional, tabla y recomendación); sin importar ni exportar.

Si el tuple solo tiene (usuario, contraseña), se asume rol administrador en ese arranque.

Importante: este archivo solo CREA usuarios que no existen en la base. Si ya existía «admin»
con otra clave, cambiar la contraseña aquí no la actualiza sola. Use una de estas opciones:
- Ponga SINCRONIZAR_CONTRASEÑAS_DESDE_BOOTSTRAP = True, abra la app una vez, entre, y vuelva a False.
- O cambie la clave desde el panel de administración (si aún puede entrar).
"""
from __future__ import annotations

# Activado ahora para que su PC copie las claves de abajo a la base al abrir la app.
# Después de entrar bien con admin / user1, dígale al asistente que la ponga otra vez en False.
SINCRONIZAR_CONTRASEÑAS_DESDE_BOOTSTRAP: bool = True

USUARIOS_DESDE_CODIGO: list[tuple[str, str] | tuple[str, str, str]] = [
    # Administrador inicial — cambie la contraseña al entrar (Administración de usuarios).
    ("admin", "admin123", "admin"),
    ("user1", "Proveedor2026!", "user"),
]
