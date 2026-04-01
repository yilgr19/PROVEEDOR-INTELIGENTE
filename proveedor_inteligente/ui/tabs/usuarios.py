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
    set_user_role,
    update_user_username,
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
    # None = alta nueva; si hay id, el formulario actualiza ese usuario al pulsar el botón principal.
    edit_user_id: list[int | None] = [None]

    form_section_title = ft.Text("Registrar Nuevo", weight=ft.FontWeight.W_600)

    def cancel_edit_form(_: ft.ControlEvent | None = None) -> None:
        edit_user_id[0] = None
        new_admin_username.value = ""
        new_admin_password.value = ""
        new_admin_role_seg.selected = [ROLE_USER]
        new_admin_username.label = "Nuevo usuario"
        new_admin_password.label = "Contraseña"
        new_admin_password.hint_text = None
        register_user_btn.content = "Registrar"
        cancel_edit_btn.visible = False
        form_section_title.value = "Registrar Nuevo"
        admin_form_msg.value = ""
        page.update()

    def begin_edit_user(user_id: int) -> None:
        tgt = get_user_by_id(conn, user_id)
        if not tgt:
            show_snack("Usuario no encontrado.")
            return
        edit_user_id[0] = user_id
        new_admin_username.value = str(tgt["username"])
        new_admin_password.value = ""
        role = normalize_role(str(tgt["role"] or ""))
        new_admin_role_seg.selected = [
            ROLE_ADMIN if role == ROLE_ADMIN else ROLE_USER
        ]
        new_admin_username.label = "Usuario"
        new_admin_password.label = "Contraseña"
        new_admin_password.hint_text = (
            "No se puede mostrar la clave guardada; escriba una nueva"
        )
        form_section_title.value = "Editar usuario"
        register_user_btn.content = "Guardar cambios"
        cancel_edit_btn.visible = True
        admin_form_msg.value = ""
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
                            tooltip="Cargar en el formulario inferior para editar",
                            on_click=lambda e, tid=uid: begin_edit_user(tid),
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

        eid = edit_user_id[0]
        if eid is not None:
            tgt = get_user_by_id(conn, eid)
            if not tgt:
                show_snack("Usuario no encontrado.")
                cancel_edit_form()
                return
            old_un = str(tgt["username"]).strip().lower()
            old_role = normalize_role(str(tgt["role"] or ""))
            try:
                if un != old_un:
                    update_user_username(conn, eid, un)
                set_user_password(conn, eid, hash_password(pw))
                if role != old_role:
                    if user_is_admin(tgt) and role != ROLE_ADMIN and count_admins(conn) <= 1:
                        admin_form_msg.value = (
                            "No puede quitar el rol de administrador al único admin."
                        )
                        page.update()
                        return
                    set_user_role(conn, eid, role)
            except ValueError as err:
                admin_form_msg.value = str(err)
                page.update()
                return
            except Exception as ex:
                admin_form_msg.value = str(ex)
                page.update()
                return
            if state.get("user_id") == eid:
                state["username"] = un
                state["is_admin"] = role == ROLE_ADMIN
            msg = f"Cambios guardados en la base de datos para «{un}»."
            if state.get("user_id") == eid and un != old_un:
                msg += " Puede cerrar sesión para actualizar el nombre en la barra superior."
            show_snack(msg)
            cancel_edit_form()
            refresh_admin_user_rows()
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
    cancel_edit_btn = ft.TextButton("Cancelar edición", visible=False, on_click=cancel_edit_form)

    users_panel = ft.Column(
        [
            ft.Text("Gestión de Usuarios", size=20, weight=ft.FontWeight.W_600),
            bootstrap_users_hint,
            admin_users_list,
            ft.Divider(),
            form_section_title,
            ft.Row(
                [new_admin_username, new_admin_password, new_admin_role_seg],
                wrap=True,
                spacing=12,
            ),
            ft.Row([register_user_btn, cancel_edit_btn], spacing=12),
            admin_form_msg,
        ],
        tight=True,
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    return UsuariosTabBundle(panel=users_panel, refresh_rows=refresh_admin_user_rows)
