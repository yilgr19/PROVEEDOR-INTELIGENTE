"""
Aplicación de escritorio: comparativa de proveedores por referencia.
Ejecutar: python main.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import flet as ft

from auth import hash_password, verify_password
from database import (
    ROLE_ADMIN,
    ROLE_USER,
    count_admins,
    count_all_prices,
    create_user,
    delete_user,
    get_connection,
    get_user_by_id,
    get_user_by_username,
    init_db,
    list_suppliers,
    list_users,
    normalize_role,
    replace_supplier_prices,
    search_by_reference,
    set_user_password,
    set_user_role,
    upsert_supplier,
    user_count,
    user_is_admin,
)
from excel_service import export_comparison_excel, export_full_catalog, parse_supplier_excel


def build_explanation(lines: list[dict], sale: float | None) -> str:
    if not lines:
        return (
            "No hay coincidencias para esa referencia. "
            "Revise el código o importe los Excel de los proveedores."
        )
    best = lines[0]
    worst = lines[-1]
    blocks: list[str] = []
    blocks.append(
        f"El proveedor recomendado es «{best['supplier_name']}» porque tiene el menor costo "
        f"para esta referencia: {best['cost']} (lista ordenada de menor a mayor costo)."
    )
    if len(lines) > 1:
        blocks.append(
            f"El costo más alto en la lista es {worst['cost']} («{worst['supplier_name']}»)."
        )
    if sale is not None:
        blocks.append(
            f"\nGanancia por unidad según precio de venta {sale} (venta − costo proveedor):"
        )
        for line in lines:
            cost = float(line["cost"])
            gain = sale - cost
            pct = (gain / sale * 100.0) if sale else 0.0
            blocks.append(
                f"  • {line['supplier_name']}: {gain:.4f} u. (margen sobre venta {pct:.2f}%)."
            )
        bgain = sale - float(best["cost"])
        blocks.append(
            f"\nCon el proveedor recomendado, cada unidad deja {bgain:.4f} frente a ese precio de venta."
        )
    else:
        blocks.append(
            "\nOpcional: puede indicar un precio de venta junto a la referencia para ver ganancias; "
            "si lo deja vacío, la búsqueda no se ve afectada."
        )
    return "\n".join(blocks)


def _parse_sale_optional(raw: str | None) -> tuple[float | None, bool]:
    """
    Devuelve (valor o None, True si había texto pero no es número válido).
    """
    s = (raw or "").strip().replace(",", ".")
    if not s:
        return None, False
    try:
        return float(s), False
    except ValueError:
        return None, True


def main(page: ft.Page) -> None:
    page.title = "Proveedor Inteligente"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 24
    if hasattr(page, "window") and hasattr(page.window, "min_width"):
        page.window.min_width = 900
        page.window.min_height = 640

    conn = get_connection()
    init_db(conn)

    try:
        from bootstrap_users import USUARIOS_DESDE_CODIGO
    except ImportError:
        USUARIOS_DESDE_CODIGO = []

    for entry in USUARIOS_DESDE_CODIGO:
        if len(entry) == 2:
            uname, plain = entry[0], entry[1]
            role_boot = ROLE_ADMIN
        else:
            uname, plain, role_boot = entry[0], entry[1], entry[2]
        u = uname.strip()
        if len(u) < 3 or len(plain) < 8:
            continue
        if get_user_by_username(conn, u):
            continue
        try:
            create_user(conn, u, hash_password(plain), role_boot)
        except sqlite3.IntegrityError:
            pass

    state: dict = {
        "username": None,
        "user_id": None,
        "is_admin": False,
        "last_lines": [],
        "last_ref": "",
        "last_sale": None,
    }

    user_field = ft.TextField(label="Usuario", autofocus=True, width=320)
    pass_field = ft.TextField(
        label="Contraseña", password=True, can_reveal_password=True, width=320
    )
    auth_msg = ft.Text(color=ft.Colors.ERROR)

    sin_cuentas = user_count(conn) == 0
    bloque_sin_cuentas = ft.Column(
        [
            ft.Text(
                "No hay usuarios autorizados en el sistema.",
                weight=ft.FontWeight.BOLD,
                size=18,
            ),
            ft.Text(
                "Las cuentas no se crean desde esta pantalla. "
                "Defínalas en el archivo bootstrap_users.py (lista USUARIOS_DESDE_CODIGO), "
                "con contraseñas de al menos 8 caracteres, y vuelva a abrir la aplicación.",
                size=14,
            ),
        ],
        spacing=16,
        tight=True,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        visible=sin_cuentas,
    )

    stats_text = ft.Text()
    import_status = ft.Text()

    ref_input = ft.TextField(
        label="Referencia del producto",
        hint_text="Código para filtrar en todos los proveedores cargados",
        expand=True,
    )
    sale_input = ft.TextField(
        label="Precio de venta (opcional)",
        hint_text="Opcional — solo para cálculo de ganancia",
        expand=True,
    )

    table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("#")),
            ft.DataColumn(ft.Text("Proveedor")),
            ft.DataColumn(ft.Text("Referencia")),
            ft.DataColumn(ft.Text("Descripción")),
            ft.DataColumn(ft.Text("Costo")),
            ft.DataColumn(ft.Text("Ganancia / u.")),
            ft.DataColumn(ft.Text("Margen %")),
        ],
        rows=[],
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        vertical_lines=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
        horizontal_lines=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
        heading_row_height=44,
        data_row_min_height=40,
    )

    explain = ft.Text(selectable=True, expand=True)

    fp_import = ft.FilePicker()
    save_compare = ft.FilePicker()
    save_full = ft.FilePicker()

    main_column = ft.Column(spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)

    admin_users_list = ft.Column(
        spacing=8,
        scroll=ft.ScrollMode.AUTO,
        height=260,
    )
    new_admin_username = ft.TextField(label="Nuevo usuario", width=200)
    new_admin_password = ft.TextField(
        label="Contraseña (mín. 8)",
        password=True,
        can_reveal_password=True,
        width=200,
    )
    new_admin_role = ft.Dropdown(
        width=180,
        label="Rol",
        value=ROLE_USER,
        options=[
            ft.DropdownOption(key=ROLE_USER, text="Usuario"),
            ft.DropdownOption(key=ROLE_ADMIN, text="Administrador"),
        ],
    )
    admin_form_msg = ft.Text(color=ft.Colors.ERROR, size=12)
    pwd_field_a = ft.TextField(label="Nueva contraseña", password=True, width=300)
    pwd_field_b = ft.TextField(label="Confirmar contraseña", password=True, width=300)

    def show_snack(msg: str) -> None:
        page.snack_bar = ft.SnackBar(ft.Text(msg))
        page.snack_bar.open = True
        page.update()

    def close_dialog(_: ft.ControlEvent | None = None) -> None:
        page.dialog = None
        page.update()

    def open_delete_dialog(user_id: int) -> None:
        if user_id == state["user_id"]:
            show_snack("No puede eliminar su propia cuenta con la sesión activa.")
            return
        tgt = get_user_by_id(conn, user_id)
        if not tgt:
            return
        if user_is_admin(tgt) and count_admins(conn) <= 1:
            show_snack("No puede eliminar al único administrador del sistema.")
            return
        uname = str(tgt["username"])

        def confirm_delete(_: ft.ControlEvent | None = None) -> None:
            delete_user(conn, user_id)
            page.dialog = None
            page.update()
            show_snack(f"Usuario «{uname}» eliminado.")
            refresh_admin_user_rows()

        page.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Eliminar usuario"),
            content=ft.Text(
                f"¿Eliminar la cuenta «{uname}»? Esta acción no se puede deshacer."
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=close_dialog),
                ft.TextButton(
                    "Eliminar",
                    on_click=confirm_delete,
                    style=ft.ButtonStyle(color=ft.Colors.ERROR),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.dialog.open = True
        page.update()

    def open_password_dialog(user_id: int) -> None:
        tgt = get_user_by_id(conn, user_id)
        if not tgt:
            return
        uname = str(tgt["username"])
        pwd_field_a.value = ""
        pwd_field_b.value = ""

        def save_password(_: ft.ControlEvent | None = None) -> None:
            a = pwd_field_a.value or ""
            b = pwd_field_b.value or ""
            if len(a) < 8:
                show_snack("La contraseña debe tener al menos 8 caracteres.")
                return
            if a != b:
                show_snack("Las contraseñas no coinciden.")
                return
            set_user_password(conn, user_id, hash_password(a))
            page.dialog = None
            page.update()
            show_snack(f"Contraseña actualizada para «{uname}».")
            refresh_admin_user_rows()

        page.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Cambiar contraseña — {uname}"),
            content=ft.Column([pwd_field_a, pwd_field_b], tight=True),
            actions=[
                ft.TextButton("Cancelar", on_click=close_dialog),
                ft.TextButton("Guardar", on_click=save_password),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.dialog.open = True
        page.update()

    def admin_role_changed(e: ft.ControlEvent, target_id: int) -> None:
        new_val = e.control.value
        if not new_val:
            return
        tgt = get_user_by_id(conn, target_id)
        if not tgt:
            return
        if (
            user_is_admin(tgt)
            and new_val == ROLE_USER
            and count_admins(conn) <= 1
        ):
            show_snack("Debe existir al menos un administrador.")
            refresh_admin_user_rows()
            return
        set_user_role(conn, target_id, new_val)
        refresh_admin_user_rows()

    def refresh_admin_user_rows() -> None:
        admin_users_list.controls.clear()
        for u in list_users(conn):
            uid_ref = int(u["id"])
            cur_role = str(u["role"])
            role_dd = ft.Dropdown(
                width=170,
                label="Rol",
                value=cur_role
                if cur_role in (ROLE_ADMIN, ROLE_USER)
                else ROLE_USER,
                options=[
                    ft.DropdownOption(key=ROLE_USER, text="Usuario"),
                    ft.DropdownOption(key=ROLE_ADMIN, text="Administrador"),
                ],
                on_select=lambda e, tid=uid_ref: admin_role_changed(e, tid),
            )
            admin_users_list.controls.append(
                ft.Row(
                    [
                        ft.Text(str(u["username"]), width=140),
                        role_dd,
                        ft.IconButton(
                            icon=ft.Icons.PASSWORD,
                            tooltip="Cambiar contraseña",
                            on_click=lambda e, tid=uid_ref: open_password_dialog(tid),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            tooltip="Eliminar usuario",
                            icon_color=ft.Colors.ERROR,
                            on_click=lambda e, tid=uid_ref: open_delete_dialog(tid),
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
        page.update()

    def admin_add_user(_: ft.ControlEvent | None = None) -> None:
        admin_form_msg.value = ""
        un = (new_admin_username.value or "").strip()
        pw = new_admin_password.value or ""
        role = new_admin_role.value or ROLE_USER
        if len(un) < 3:
            admin_form_msg.value = "Usuario demasiado corto (mín. 3 caracteres)."
            page.update()
            return
        if len(pw) < 8:
            admin_form_msg.value = "Contraseña mínimo 8 caracteres."
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
        new_admin_role.value = ROLE_USER
        show_snack(f"Usuario «{un}» registrado.")
        refresh_admin_user_rows()

    admin_section = ft.Column(
        [
            ft.Text("Administración de usuarios", style=ft.TextThemeStyle.TITLE_MEDIUM),
            ft.Text(
                "Solo los administradores ven este apartado: alta de usuarios, cambio de "
                "contraseñas, cambio de rol y bajas.",
                size=12,
                color=ft.Colors.ON_SURFACE_VARIANT,
            ),
            ft.Text("Registrar nuevo usuario", style=ft.TextThemeStyle.TITLE_SMALL),
            ft.Row(
                [
                    new_admin_username,
                    new_admin_password,
                    new_admin_role,
                    ft.ElevatedButton(
                        "Registrar usuario", on_click=admin_add_user
                    ),
                ],
                wrap=True,
                spacing=12,
            ),
            admin_form_msg,
            ft.Text("Cuentas del sistema", style=ft.TextThemeStyle.TITLE_SMALL),
            admin_users_list,
        ],
        spacing=12,
        visible=False,
    )

    def logout(_: ft.ControlEvent | None = None) -> None:
        state["username"] = None
        state["user_id"] = None
        state["is_admin"] = False
        state["last_lines"] = []
        page.appbar = None
        auth_overlay.visible = True
        main_column.visible = False
        admin_section.visible = False
        pass_field.value = ""
        page.update()

    def refresh_stats() -> None:
        n = count_all_prices(conn)
        sups = list_suppliers(conn)
        stats_text.value = f"Referencias en base: {n} — Proveedores: {len(sups)}"

    def go_main() -> None:
        auth_overlay.visible = False
        main_column.visible = True
        role_lbl = "Administrador" if state["is_admin"] else "Usuario"
        page.appbar = ft.AppBar(
            title=ft.Text(
                f"Proveedor Inteligente — {state['username']} ({role_lbl})"
            ),
            bgcolor=ft.Colors.BLUE_700,
            color=ft.Colors.WHITE,
            actions=[
                ft.IconButton(
                    icon=ft.Icons.LOGOUT,
                    tooltip="Cerrar sesión",
                    icon_color=ft.Colors.WHITE,
                    on_click=logout,
                )
            ],
        )
        admin_section.visible = state["is_admin"]
        if state["is_admin"]:
            refresh_admin_user_rows()
        refresh_stats()
        page.update()

    def try_login(_: ft.ControlEvent | None = None) -> None:
        auth_msg.value = ""
        u = user_field.value or ""
        p = pass_field.value or ""
        row = get_user_by_username(conn, u)
        if not row or not verify_password(p, row["password_hash"]):
            auth_msg.value = "Usuario o contraseña incorrectos."
            page.update()
            return
        state["username"] = row["username"]
        state["user_id"] = int(row["id"])
        state["is_admin"] = user_is_admin(row)
        go_main()

    async def pick_import(_: ft.ControlEvent | None = None) -> None:
        files = await fp_import.pick_files(
            dialog_title="Seleccione los Excel de proveedores (uno por proveedor)",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["xlsx", "xlsm"],
            allow_multiple=True,
        )
        if not files:
            import_status.value = "Importación cancelada."
            page.update()
            return
        ok, err = 0, []
        for f in files:
            if not f.path:
                err.append(f"{f.name}: sin ruta local")
                continue
            path = Path(f.path)
            try:
                rows, name = parse_supplier_excel(path)
                sid = upsert_supplier(conn, name)
                n = replace_supplier_prices(conn, sid, rows, path.name)
                ok += 1
                import_status.value = f"Última carga: {name} — {n} referencias."
            except Exception as ex:
                err.append(f"{path.name}: {ex}")
        parts = [f"Archivos procesados correctamente: {ok}."]
        if err:
            parts.append("Errores: " + " | ".join(err))
        import_status.value = "\n".join(parts)
        refresh_stats()
        page.update()

    def do_search(_: ft.ControlEvent | None = None) -> None:
        ref = (ref_input.value or "").strip()
        sale, sale_bad = _parse_sale_optional(sale_input.value)
        lines = search_by_reference(conn, ref)
        state["last_lines"] = lines
        state["last_ref"] = ref
        state["last_sale"] = sale
        table.rows.clear()
        for i, line in enumerate(lines, start=1):
            cost = float(line["cost"])
            if sale is not None:
                gain = sale - cost
                margin = (gain / sale * 100.0) if sale else 0.0
                g_txt = f"{gain:.4f}"
                m_txt = f"{margin:.2f}"
            else:
                g_txt = "—"
                m_txt = "—"
            table.rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(str(i))),
                        ft.DataCell(ft.Text(str(line["supplier_name"]))),
                        ft.DataCell(ft.Text(str(line["reference_raw"]))),
                        ft.DataCell(ft.Text(str(line.get("description") or ""))),
                        ft.DataCell(ft.Text(str(cost))),
                        ft.DataCell(ft.Text(g_txt)),
                        ft.DataCell(ft.Text(m_txt)),
                    ]
                )
            )
        msg = build_explanation(lines, sale)
        if sale_bad:
            msg = (
                "El precio de venta no es un número válido; se ignoró para los cálculos.\n\n" + msg
            )
        explain.value = msg
        page.update()

    ref_input.on_submit = do_search
    sale_input.on_submit = do_search

    async def export_cmp_click(_: ft.ControlEvent | None = None) -> None:
        if not state["last_lines"]:
            page.snack_bar = ft.SnackBar(ft.Text("Primero busque una referencia."))
            page.snack_bar.open = True
            page.update()
            return
        out = await save_compare.save_file(
            dialog_title="Exportar comparativa a Excel",
            file_name="comparativa_referencia.xlsx",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["xlsx"],
        )
        if not out:
            return
        path = Path(out)
        if path.suffix.lower() != ".xlsx":
            path = path.with_suffix(".xlsx")
        try:
            export_comparison_excel(
                path,
                state["last_ref"],
                state["last_sale"],
                state["last_lines"],
                explain.value or "",
            )
            page.snack_bar = ft.SnackBar(ft.Text(f"Guardado: {path}"))
            page.snack_bar.open = True
        except Exception as ex:
            page.snack_bar = ft.SnackBar(ft.Text(f"Error al guardar: {ex}"))
            page.snack_bar.open = True
        page.update()

    async def export_full_click(_: ft.ControlEvent | None = None) -> None:
        out = await save_full.save_file(
            dialog_title="Exportar catálogo completo",
            file_name="catalogo_proveedores.xlsx",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["xlsx"],
        )
        if not out:
            return
        path = Path(out)
        if path.suffix.lower() != ".xlsx":
            path = path.with_suffix(".xlsx")
        try:
            export_full_catalog(path, conn)
            page.snack_bar = ft.SnackBar(ft.Text(f"Catálogo exportado: {path}"))
            page.snack_bar.open = True
        except Exception as ex:
            page.snack_bar = ft.SnackBar(ft.Text(f"Error: {ex}"))
            page.snack_bar.open = True
        page.update()

    login_btn = ft.ElevatedButton("Entrar", on_click=try_login)

    login_column = ft.Column(
        [
            ft.Text("Inicie sesión.", weight=ft.FontWeight.BOLD),
            user_field,
            pass_field,
            login_btn,
            auth_msg,
        ],
        spacing=12,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        visible=not sin_cuentas,
    )

    auth_inner = ft.Column(
        [bloque_sin_cuentas, login_column],
        spacing=24,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        tight=True,
        width=420,
    )
    auth_overlay = ft.Container(
        content=auth_inner,
        expand=True,
        alignment=ft.Alignment.CENTER,
        bgcolor=ft.Colors.SURFACE,
    )

    main_column.controls = [
        ft.Text("Importación", style=ft.TextThemeStyle.TITLE_MEDIUM),
        ft.Row(
            [
                ft.ElevatedButton(
                    "Cargar / actualizar Excel (varios archivos)",
                    icon=ft.Icons.UPLOAD_FILE,
                    on_click=pick_import,
                ),
            ]
        ),
        ft.Text(
            "Cada archivo actualiza un proveedor cuyo nombre es el del archivo (sin extensión). "
            "Volver a cargar el mismo proveedor sustituye sus datos anteriores.",
            size=12,
            color=ft.Colors.ON_SURFACE_VARIANT,
        ),
        stats_text,
        import_status,
        ft.Divider(),
        admin_section,
        ft.Divider(),
        ft.Text("Búsqueda por referencia", style=ft.TextThemeStyle.TITLE_MEDIUM),
        ft.Row(
            [
                ref_input,
                sale_input,
                ft.ElevatedButton("Buscar", icon=ft.Icons.SEARCH, on_click=do_search),
            ],
            spacing=12,
        ),
        ft.Container(content=table, expand=True),
        ft.Text("Recomendación y cálculos", style=ft.TextThemeStyle.TITLE_SMALL),
        explain,
        ft.Row(
            [
                ft.OutlinedButton("Exportar comparativa (Excel)", on_click=export_cmp_click),
                ft.OutlinedButton("Exportar catálogo completo", on_click=export_full_click),
            ],
            spacing=12,
        ),
    ]
    main_column.visible = False

    page.services.extend([fp_import, save_compare, save_full])
    page.add(
        ft.Stack(
            expand=True,
            controls=[
                main_column,
                auth_overlay,
            ],
        )
    )


def _flet_cache_en_carpeta_proyecto() -> None:
    """
    Flet guarda el cliente de escritorio en ~/.flet; en algunos equipos esa ruta no es escribible.
    Redirige la caché a ./.flet_cache dentro del proyecto.
    """
    import flet_desktop
    from pathlib import Path

    base = Path(__file__).resolve().parent / ".flet_cache" / "client"
    base.mkdir(parents=True, exist_ok=True)

    def _get_dir() -> Path:
        flavor = flet_desktop.__get_desktop_flavor()
        ver = flet_desktop.version.version
        return base / f"flet-desktop-{flavor}-{ver}"

    flet_desktop.__get_client_storage_dir = _get_dir  # type: ignore[method-assign]


if __name__ == "__main__":
    import os

    if os.environ.get("PROVEEDOR_USE_BROWSER", "").lower() in ("1", "true", "si", "yes"):
        # Solo localhost; abre el navegador en vez de ventana Flet (sin usar ~/.flet)
        ft.run(main, view=ft.AppView.WEB_BROWSER, host="127.0.0.1", port=0)
    else:
        _flet_cache_en_carpeta_proyecto()
        ft.run(main)
