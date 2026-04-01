"""
Interfaz Flet de Proveedor Inteligente.
Ejecutar desde la raíz del proyecto: python run.py
"""
from __future__ import annotations

import sqlite3
import flet as ft

from proveedor_inteligente.core.auth import hash_password, verify_password
from proveedor_inteligente.core.config import get_app_icon_path
from proveedor_inteligente.data.database import (
    ROLE_ADMIN,
    create_user,
    get_connection,
    get_user_by_username,
    init_db,
    set_user_password,
    user_count,
    user_is_admin,
)
from proveedor_inteligente.ui.tabs.importar_tab import create_import_tab
from proveedor_inteligente.ui.tabs.inicio import create_inicio_tab
from proveedor_inteligente.ui.tabs.referencias import create_referencias_tab
from proveedor_inteligente.ui.tabs.usuarios import create_usuarios_tab


def main(page: ft.Page) -> None:
    page.title = "Proveedor Inteligente"
    page.theme_mode = ft.ThemeMode.LIGHT
    
    # --- CONFIGURACIÓN DE TEMA COMPATIBLE (Sin surface_variant) ---
    _w = ft.Colors.WHITE
    page.theme = ft.Theme(
        color_scheme_seed=ft.Colors.BLUE,
        use_material3=True,
        color_scheme=ft.ColorScheme(
            primary=ft.Colors.BLUE,
            surface=_w,
            on_surface=ft.Colors.BLACK,
            outline=ft.Colors.BLUE_GREY_100,
        )
    )
    page.bgcolor = _w
    page.padding = 0

    if hasattr(page, "window"):
        w = page.window
        if hasattr(w, "min_width"):
            w.min_width = 1000
            w.min_height = 700
        icon_path = get_app_icon_path()
        if icon_path is not None and hasattr(w, "icon"):
            w.icon = str(icon_path.resolve())

    conn = get_connection()
    init_db(conn)

    # --- LÓGICA DE BOOTSTRAP ---
    try:
        from proveedor_inteligente import bootstrap_users as _bootstrap
    except ImportError:
        _bootstrap = None
    
    USUARIOS_DESDE_CODIGO = getattr(_bootstrap, "USUARIOS_DESDE_CODIGO", []) or []
    _sync_pass = bool(getattr(_bootstrap, "SINCRONIZAR_CONTRASEÑAS_DESDE_BOOTSTRAP", False))

    for entry in USUARIOS_DESDE_CODIGO:
        uname = entry[0].strip()
        plain = entry[1]
        role_boot = entry[2] if len(entry) > 2 else ROLE_ADMIN
        if len(uname) < 3 or len(plain) < 8: continue
        
        existing = get_user_by_username(conn, uname)
        if existing:
            if _sync_pass:
                set_user_password(conn, int(existing["id"]), hash_password(plain))
            continue
        try:
            create_user(conn, uname, hash_password(plain), role_boot)
        except sqlite3.IntegrityError:
            pass

    boot_names = [str(e[0]).strip() for e in USUARIOS_DESDE_CODIGO if len(str(e[0]).strip()) >= 3]
    bootstrap_users_hint = ft.Text(
        f"Usuarios iniciales: {', '.join(boot_names)}" if boot_names else "Sin usuarios predefinidos.",
        size=12, color=ft.Colors.BLUE_GREY_400
    )

    # --- ESTADO ---
    state: dict = {
        "username": None, "user_id": None, "is_admin": False,
        "last_lines": [], "last_ref": "", "last_sale": None, "admin_tab": 0,
    }

    user_field = ft.TextField(label="Usuario", autofocus=True, width=320)
    pass_field = ft.TextField(label="Contraseña", password=True, can_reveal_password=True, width=320)
    auth_msg = ft.Text(color=ft.Colors.ERROR)

    def show_snack(msg: str) -> None:
        page.snack_bar = ft.SnackBar(ft.Text(msg))
        page.snack_bar.open = True
        page.update()

    def close_dialog(_=None) -> None:
        page.dialog = None
        page.update()

    fp_import = ft.FilePicker()
    save_compare = ft.FilePicker()
    save_full = ft.FilePicker()

    # --- TABS ---
    inicio = create_inicio_tab(page, conn, state, save_compare, save_full)
    referencias = create_referencias_tab(page, conn, inicio.refresh_stats, show_snack, close_dialog)
    usuarios = create_usuarios_tab(page, conn, state, bootstrap_users_hint, show_snack, close_dialog)
    
    panel_import = create_import_tab(
        page, conn, state, fp_import, inicio.refresh_stats, 
        lambda: (referencias.refresh_supplier_options(), referencias.refresh_list()) if state["admin_tab"] == 3 else None
    )

    _main_panels = (inicio.panel, panel_import, usuarios.panel, referencias.panel)
    # Pestañas con scroll exterior: evita hijos expand+scroll anidados sin altura (p. ej. Importar).
    # Usuarios (2): el panel ya lleva su propio scroll interno.
    _tabs_con_scroll = {0, 1, 3}

    def _surface_para_pestaña(i: int) -> ft.Control:
        panel = _main_panels[i]
        # CAMBIO CLAVE: Usamos una Column para el scroll en lugar del Container
        if i in _tabs_con_scroll:
            content_view = ft.Column(
                controls=[panel],
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                spacing=0
            )
        else:
            content_view = panel

        return ft.Container(
            content=content_view,
            expand=True,
            bgcolor=_w,
            alignment=ft.Alignment.TOP_LEFT,
        )

    workspace_main = ft.Container(expand=True, bgcolor=_w, content=_surface_para_pestaña(0))

    def apply_main_panel(idx: int) -> None:
        state["admin_tab"] = idx
        workspace_main.content = _surface_para_pestaña(idx)

    def admin_nav_change(e: ft.ControlEvent) -> None:
        idx = e.control.selected_index
        apply_main_panel(idx)
        if idx == 2: usuarios.refresh_rows(update_page=False)
        if idx == 3: 
            referencias.refresh_supplier_options()
            referencias.refresh_list()
        page.update()

    nav_rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        extended=True,
        min_extended_width=200,
        bgcolor=_w,
        destinations=[
            ft.NavigationRailDestination(icon=ft.Icons.HOME_OUTLINED, selected_icon=ft.Icons.HOME, label="Inicio"),
            ft.NavigationRailDestination(icon=ft.Icons.UPLOAD_FILE_OUTLINED, selected_icon=ft.Icons.UPLOAD_FILE, label="Importar"),
            ft.NavigationRailDestination(icon=ft.Icons.PEOPLE_OUTLINE, selected_icon=ft.Icons.PEOPLE, label="Usuarios"),
            ft.NavigationRailDestination(icon=ft.Icons.INVENTORY_2_OUTLINED, selected_icon=ft.Icons.INVENTORY_2, label="Referencias"),
        ],
        on_change=admin_nav_change,
    )

    rail_divider = ft.VerticalDivider(width=1, visible=False, color=ft.Colors.BLUE_GREY_100)

    workspace = ft.Container(
        expand=True,
        visible=False,
        content=ft.Row(
            expand=True,
            spacing=0,
            controls=[
                ft.Container(padding=ft.padding.only(left=8, top=12, bottom=12), content=nav_rail),
                rail_divider,
                ft.Container(expand=True, padding=24, content=workspace_main),
            ],
        )
    )

    def logout(_=None) -> None:
        state.update({"username": None, "user_id": None, "is_admin": False})
        page.appbar = None
        auth_overlay.visible = True
        workspace.visible = False
        page.update()

    def go_main() -> None:
        auth_overlay.visible = False
        workspace.visible = True
        role_txt = "Administrador" if state["is_admin"] else "Usuario"
        page.appbar = ft.AppBar(
            title=ft.Text(f"Proveedor Inteligente — {state['username']} ({role_txt})"),
            bgcolor=ft.Colors.BLUE_700,
            color=_w,
            actions=[ft.IconButton(icon=ft.Icons.LOGOUT, icon_color=_w, on_click=logout)],
        )
        nav_rail.visible = state["is_admin"]
        rail_divider.visible = state["is_admin"]
        inicio.export_row.visible = state["is_admin"]
        inicio.role_hint.visible = not state["is_admin"]
        apply_main_panel(0)
        inicio.refresh_stats()
        page.update()

    def try_login(_=None) -> None:
        u, p = user_field.value, pass_field.value
        row = get_user_by_username(conn, u)
        if not row or not verify_password(p, row["password_hash"]):
            auth_msg.value = "Credenciales incorrectas."
            page.update()
            return
        state.update({"username": row["username"], "user_id": int(row["id"]), "is_admin": user_is_admin(row)})
        go_main()

    sin_cuentas = user_count(conn) == 0
    auth_overlay = ft.Container(
        expand=True, bgcolor=_w, alignment=ft.Alignment.CENTER,
        content=ft.Container(
            padding=40, bgcolor=_w, border_radius=20,
            border=ft.Border.all(1, ft.Colors.BLUE_GREY_100),
            content=ft.Column(
                [
                    ft.Text("Inicie Sesión", size=24, weight="bold"),
                    user_field, pass_field,
                    ft.ElevatedButton("Entrar", on_click=try_login, width=320),
                    auth_msg
                ], horizontal_alignment="center", spacing=15, tight=True, width=350
            )
        )
    )

    page.services.extend([fp_import, save_compare, save_full])
    page.add(ft.Stack(expand=True, controls=[workspace, auth_overlay]))


def _flet_cache_en_carpeta_proyecto() -> None:
    import flet_desktop
    from pathlib import Path
    from proveedor_inteligente.core.config import get_flet_cache_dir
    base = get_flet_cache_dir()
    def _get_dir() -> Path:
        flavor = flet_desktop.__get_desktop_flavor()
        ver = flet_desktop.version.version
        return base / f"flet-desktop-{flavor}-{ver}"
    flet_desktop.__get_client_storage_dir = _get_dir

def run_application() -> None:
    import os
    if os.environ.get("PROVEEDOR_USE_BROWSER", "").lower() in ("1", "true", "si", "yes"):
        ft.run(main, view=ft.AppView.WEB_BROWSER, host="127.0.0.1", port=0)
    else:
        _flet_cache_en_carpeta_proyecto()
        ft.run(main)