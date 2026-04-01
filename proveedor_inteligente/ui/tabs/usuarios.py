import sqlite3
from dataclasses import dataclass
from typing import Any, Callable
import flet as ft

from proveedor_inteligente.core.auth import hash_password
from proveedor_inteligente.data.database import (
    ROLE_ADMIN, ROLE_USER, count_admins, create_user, delete_user,
    get_user_by_id, get_user_by_username, list_users, normalize_role,
    set_user_password, set_user_role, update_user_username, user_is_admin,
)
from proveedor_inteligente.ui.tabs.common import MIN_PASSWORD_LEN, MIN_USERNAME_LEN, fmt_created_at

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
    
    admin_users_list = ft.Column(spacing=8, tight=True)
    new_admin_username = ft.TextField(label="Nuevo usuario", width=200, bgcolor=ft.Colors.WHITE)
    new_admin_password = ft.TextField(label="Contraseña", password=True, can_reveal_password=True, width=200, bgcolor=ft.Colors.WHITE)
    
    new_admin_role_seg = ft.SegmentedButton(
        selected=[ROLE_USER],
        segments=[
            ft.Segment(value=ROLE_USER, label="Usuario"),
            ft.Segment(value=ROLE_ADMIN, label="Admin"),
        ],
    )
    admin_form_msg = ft.Text(color=ft.Colors.ERROR, size=12)

    def open_delete_dialog(user_id: int):
        if user_id == state["user_id"]:
            show_snack("No puede eliminar su propia cuenta.")
            return
        
        def confirm_delete(_):
            delete_user(conn, user_id)
            close_dialog()
            show_snack("Usuario eliminado.")
            refresh_admin_user_rows()

        page.dialog = ft.AlertDialog(
            title=ft.Text("Confirmar eliminación"),
            content=ft.Text("¿Está seguro de eliminar este usuario?"),
            actions=[
                ft.TextButton("Cancelar", on_click=close_dialog),
                ft.TextButton("Eliminar", on_click=confirm_delete, color=ft.Colors.ERROR),
            ],
        )
        page.dialog.open = True
        page.update()

    def refresh_admin_user_rows(*, update_page: bool = True):
        rows = list_users(conn)
        admin_users_list.controls.clear()
        
        # Cabecera simple
        admin_users_list.controls.append(
            ft.Row([
                ft.Text("Usuario", width=150, weight="bold"),
                ft.Text("Rol", width=200, weight="bold"),
                ft.Text("Acciones", weight="bold"),
            ])
        )

        for u in rows:
            uid = int(u["id"])
            role_val = normalize_role(u["role"])
            
            admin_users_list.controls.append(
                ft.Row([
                    ft.Text(u["username"], width=150),
                    ft.Text(role_val, width=200),
                    ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color="error", on_click=lambda e, tid=uid: open_delete_dialog(tid))
                ])
            )
        if update_page: page.update()

    def admin_add_user(_):
        un = new_admin_username.value.strip()
        pw = new_admin_password.value
        if not un or len(pw) < 6:
            admin_form_msg.value = "Datos inválidos."
            page.update()
            return
        create_user(conn, un, hash_password(pw), new_admin_role_seg.selected[0])
        new_admin_username.value = ""
        new_admin_password.value = ""
        refresh_admin_user_rows()

    users_panel = ft.Column([
        ft.Text("Gestión de Usuarios", size=20, weight="bold"),
        admin_users_list,
        ft.Divider(),
        ft.Text("Registrar Nuevo", weight="bold"),
        ft.Row([new_admin_username, new_admin_password, new_admin_role_seg]),
        ft.ElevatedButton("Registrar", on_click=admin_add_user),
        admin_form_msg
    ], tight=True)

    # CRITICAL: El return debe estar aquí
    return UsuariosTabBundle(panel=users_panel, refresh_rows=refresh_admin_user_rows)