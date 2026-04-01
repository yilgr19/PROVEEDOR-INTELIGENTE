import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

import flet as ft

from proveedor_inteligente.core.auth import hash_password
from proveedor_inteligente.data.database import (
    ROLE_ADMIN,
    ROLE_USER,
    count_admins,
    create_user,
    delete_user,
    get_user_by_id,
    get_user_by_username,
    list_users,
    normalize_role,
    set_user_password,
    user_is_admin,
)
from proveedor_inteligente.ui.tabs.common import MIN_PASSWORD_LEN, MIN_USERNAME_LEN, fmt_created_at

_ROL_LABEL = {ROLE_ADMIN: "admin", ROLE_USER: "user"}


@dataclass(frozen=True)
class UsuariosTabBundle:
    panel: ft.Column
    refresh_rows: Callable[..., None]


def create_usuarios_tab(
    page: ft.Page,
    conn: sqlite3.Connection,
    state: dict[str, Any],
    bootstrap_users_hint: ft.Text,
    show_snack: Callable[[str], None],
    close_dialog: Callable[[ft.ControlEvent | None], None],
) -> UsuariosTabBundle:

    # Sin scroll propio: el scroll único va en `users_panel`.
    admin_users_list = ft.Column(spacing=8, tight=True)
    new_admin_username = ft.TextField(
        label="Nuevo usuario", width=200, bgcolor=ft.Colors.WHITE
    )
    new_admin_password = ft.TextField(
        label="Contraseña",
        password=True,
        can_reveal_password=True,
        width=200,
        bgcolor=ft.Colors.WHITE,
    )

    new_admin_role_seg = ft.SegmentedButton(
        selected=[ROLE_USER],
        segments=[
            ft.Segment(value=ROLE_USER, label="Usuario"),
            ft.Segment(value=ROLE_ADMIN, label="Admin"),
        ],
    )
    admin_form_msg = ft.Text(color=ft.Colors.ERROR, size=12)

    def open_password_dialog(user_id: int) -> None:
        tgt = get_user_by_id(conn, user_id)
        if not tgt:
            show_snack("Usuario no encontrado.")
            return
        uname = str(tgt["username"])
        pwd_a = ft.TextField(
            label="Nueva contraseña",
            password=True,
            can_reveal_password=True,
            width=320,
            autofocus=True,
        )
        pwd_b = ft.TextField(
            label="Confirmar contraseña",
            password=True,
            can_reveal_password=True,
            width=320,
        )
        pwd_err = ft.Text(color=ft.Colors.ERROR, size=12, visible=False)

        def save_password(_: ft.ControlEvent | None = None) -> None:
            pwd_err.visible = False
            pwd_err.value = ""
            a = pwd_a.value or ""
            b = pwd_b.value or ""
            if len(a) < MIN_PASSWORD_LEN:
                pwd_err.value = f"Mínimo {MIN_PASSWORD_LEN} caracteres."
                pwd_err.visible = True
                page.update()
                return
            if a != b:
                pwd_err.value = "Las contraseñas no coinciden."
                pwd_err.visible = True
                page.update()
                return
            try:
                set_user_password(conn, user_id, hash_password(a))
            except Exception as ex:
                pwd_err.value = str(ex)
                pwd_err.visible = True
                page.update()
                return
            page.dialog = None
            page.update()
            show_snack(f"Contraseña guardada en la base de datos para «{uname}».")

        page.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Modificar contraseña — {uname}"),
            content=ft.Column(
                [pwd_a, pwd_b, pwd_err], tight=True, width=340
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=close_dialog),
                ft.TextButton("Aplicar", on_click=save_password),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.dialog.open = True
        page.update()

    def delete_user_now(user_id: int) -> None:
        """Borra la fila en SQLite al instante (DELETE + commit), con las mismas reglas de seguridad."""
        if user_id == state.get("user_id"):
            show_snack("No puede eliminar su propia cuenta con la sesión activa.")
            return
        tgt = get_user_by_id(conn, user_id)
        if not tgt:
            show_snack("Usuario no encontrado.")
            return
        if user_is_admin(tgt) and count_admins(conn) <= 1:
            show_snack("No puede eliminar al único administrador del sistema.")
            return
        uname = str(tgt["username"])
        delete_user(conn, user_id)
        show_snack(f"Usuario «{uname}» eliminado de la base de datos.")
        refresh_admin_user_rows()

    def refresh_admin_user_rows(*, update_page: bool = True) -> None:
        try:
            rows = list_users(conn)
        except Exception as ex:
            show_snack(f"No se pudieron cargar los usuarios: {ex}")
            return
        admin_users_list.controls.clear()
        admin_users_list.controls.append(
            ft.Row(
                [
                    ft.Text("Usuario", width=150, weight=ft.FontWeight.W_600),
                    ft.Text("Rol", width=120, weight=ft.FontWeight.W_600),
                    ft.Text("Alta", width=130, weight=ft.FontWeight.W_600),
                    ft.Text("Acciones", expand=True, weight=ft.FontWeight.W_600),
                ]
            )
        )

        for u in rows:
            uid = int(u["id"])
            role_norm = normalize_role(str(u["role"] or ""))
            role_txt = _ROL_LABEL.get(role_norm, role_norm)
            try:
                alta_txt = fmt_created_at(u["created_at"])
            except (KeyError, TypeError):
                alta_txt = "—"
            admin_users_list.controls.append(
                ft.Row(
                    [
                        ft.Text(str(u["username"]), width=150),
                        ft.Text(role_txt, width=120),
                        ft.Text(alta_txt, width=130, size=12),
                        ft.OutlinedButton(
                            "Modificar",
                            tooltip="Modificar contraseña (guarda en SQLite)",
                            on_click=lambda e, tid=uid: open_password_dialog(tid),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            icon_color=ft.Colors.ERROR,
                            tooltip="Eliminar de la base de datos",
                            on_click=lambda e, tid=uid: delete_user_now(tid),
                        ),
                    ],
                    spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
        if update_page:
            page.update()

    def admin_add_user(_: ft.ControlEvent | None = None) -> None:
        admin_form_msg.value = ""
        un = (new_admin_username.value or "").strip().lower()
        pw = new_admin_password.value or ""
        sel = new_admin_role_seg.selected or [ROLE_USER]
        role = normalize_role(str(sel[0]))
        if len(un) < MIN_USERNAME_LEN:
            admin_form_msg.value = f"Usuario: mínimo {MIN_USERNAME_LEN} caracteres."
            page.update()
            return
        if len(pw) < MIN_PASSWORD_LEN:
            admin_form_msg.value = f"Contraseña: mínimo {MIN_PASSWORD_LEN} caracteres."
            page.update()
            return
        if get_user_by_username(conn, un):
            admin_form_msg.value = "Ese nombre de usuario ya existe."
            page.update()
            return
        try:
            create_user(conn, un, hash_password(pw), role)
        except sqlite3.IntegrityError:
            admin_form_msg.value = "No se pudo crear el usuario."
            page.update()
            return
        new_admin_username.value = ""
        new_admin_password.value = ""
        new_admin_role_seg.selected = [ROLE_USER]
        show_snack(f"Usuario «{un}» registrado.")
        refresh_admin_user_rows()

    register_user_btn = ft.ElevatedButton("Registrar", on_click=admin_add_user)

    users_panel = ft.Column(
        [
            ft.Text("Gestión de Usuarios", size=20, weight=ft.FontWeight.W_600),
            bootstrap_users_hint,
            admin_users_list,
            ft.Divider(),
            ft.Text("Registrar Nuevo", weight=ft.FontWeight.W_600),
            ft.Row(
                [new_admin_username, new_admin_password, new_admin_role_seg],
                wrap=True,
                spacing=12,
            ),
            register_user_btn,
            admin_form_msg,
        ],
        tight=True,
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    return UsuariosTabBundle(panel=users_panel, refresh_rows=refresh_admin_user_rows)
