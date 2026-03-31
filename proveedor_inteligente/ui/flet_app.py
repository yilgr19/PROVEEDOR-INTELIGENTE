"""
Interfaz Flet de Proveedor Inteligente.
Ejecutar desde la raíz del proyecto: python run.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import flet as ft

from proveedor_inteligente.core.auth import hash_password, verify_password
from proveedor_inteligente.data.database import (
    ROLE_ADMIN,
    ROLE_USER,
    count_admins,
    count_all_prices,
    create_user,
    delete_price_row,
    delete_user,
    get_connection,
    get_price_row,
    get_user_by_id,
    get_user_by_username,
    init_db,
    insert_price_row_manual,
    list_price_rows_admin,
    list_suppliers,
    list_users,
    normalize_role,
    replace_supplier_prices,
    search_by_reference,
    set_user_password,
    set_user_role,
    update_price_row,
    upsert_supplier,
    user_count,
    user_is_admin,
)
from proveedor_inteligente.services.excel_service import (
    export_comparison_excel,
    export_full_catalog,
    parse_supplier_excel,
)


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
        from proveedor_inteligente import bootstrap_users as _bootstrap
    except ImportError:
        _bootstrap = None
    USUARIOS_DESDE_CODIGO = getattr(_bootstrap, "USUARIOS_DESDE_CODIGO", []) or []
    _sync_bootstrap_passwords = bool(
        getattr(_bootstrap, "SINCRONIZAR_CONTRASEÑAS_DESDE_BOOTSTRAP", False)
    )

    for entry in USUARIOS_DESDE_CODIGO:
        if len(entry) == 2:
            uname, plain = entry[0], entry[1]
            role_boot = ROLE_ADMIN
        else:
            uname, plain, role_boot = entry[0], entry[1], entry[2]
        u = uname.strip()
        if len(u) < 3 or len(plain) < 8:
            continue
        existing = get_user_by_username(conn, u)
        if existing:
            if _sync_bootstrap_passwords:
                set_user_password(conn, int(existing["id"]), hash_password(plain))
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
        "admin_tab": 0,
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
                "Defínalas en proveedor_inteligente/bootstrap_users.py (lista USUARIOS_DESDE_CODIGO), "
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

    table_box = ft.Container(
        height=340,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=4,
        content=ft.Column(
            controls=[table],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
    )

    explain = ft.Text(selectable=True)

    fp_import = ft.FilePicker()
    save_compare = ft.FilePicker()
    save_full = ft.FilePicker()

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

    ref_filter_supplier_dd = ft.Dropdown(
        width=220,
        label="Proveedor (filtro)",
    )
    ref_search_field = ft.TextField(
        label="Buscar referencia",
        hint_text="Fragmento de código o descripción",
        width=220,
    )
    ref_list_column = ft.Column(
        spacing=6,
        scroll=ft.ScrollMode.AUTO,
        height=300,
    )
    ref_crud_msg = ft.Text(color=ft.Colors.ERROR, size=12)
    ref_new_supplier_dd = ft.Dropdown(width=200, label="Proveedor (alta)")
    ref_new_reference = ft.TextField(label="Referencia", width=160)
    ref_new_desc = ft.TextField(label="Descripción (opcional)", width=200)
    ref_new_cost = ft.TextField(label="Costo", width=100)
    quick_supplier_name = ft.TextField(
        label="Nombre proveedor (vacío, sin Excel)",
        width=220,
    )

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

    def refresh_ref_supplier_options() -> None:
        sups = list_suppliers(conn)
        ref_filter_supplier_dd.options = [
            ft.DropdownOption(key="__all__", text="(Todos los proveedores)"),
            *[ft.DropdownOption(key=str(s["id"]), text=str(s["name"])) for s in sups],
        ]
        ref_filter_supplier_dd.value = "__all__"
        ref_new_supplier_dd.options = [
            ft.DropdownOption(key=str(s["id"]), text=str(s["name"])) for s in sups
        ]
        if sups:
            ref_new_supplier_dd.value = str(sups[0]["id"])
        else:
            ref_new_supplier_dd.value = None

    def refresh_ref_list() -> None:
        ref_crud_msg.value = ""
        val = ref_filter_supplier_dd.value
        sid = None if val in (None, "", "__all__") else int(val)
        q = (ref_search_field.value or "").strip()
        try:
            rows = list_price_rows_admin(conn, sid, q)
        except Exception as ex:
            ref_crud_msg.value = str(ex)
            rows = []
        ref_list_column.controls.clear()
        for r in rows:
            rid = int(r["id"])
            ref_list_column.controls.append(
                ft.Row(
                    [
                        ft.Text(str(r["supplier_name"]), width=110),
                        ft.Text(str(r["reference_raw"]), width=110),
                        ft.Text(str(r["description"] or "")[:42], width=128),
                        ft.Text(str(r["cost"]), width=56),
                        ft.IconButton(
                            icon=ft.Icons.EDIT_OUTLINED,
                            tooltip="Editar",
                            on_click=lambda e, i=rid: open_ref_edit_dialog(i),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            tooltip="Eliminar",
                            icon_color=ft.Colors.ERROR,
                            on_click=lambda e, i=rid: open_ref_delete_dialog(i),
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
        page.update()

    def open_ref_edit_dialog(row_id: int) -> None:
        row = get_price_row(conn, row_id)
        if not row:
            show_snack("Registro no encontrado.")
            return
        ef_ref = ft.TextField(label="Referencia", value=str(row["reference_raw"]))
        ef_desc = ft.TextField(label="Descripción", value=str(row["description"] or ""))
        ef_cost = ft.TextField(label="Costo", value=str(row["cost"]))

        def save_edit(_: ft.ControlEvent | None = None) -> None:
            try:
                c = float((ef_cost.value or "0").replace(",", "."))
            except ValueError:
                show_snack("Costo no válido.")
                return
            try:
                update_price_row(conn, row_id, ef_ref.value or "", ef_desc.value, c)
            except ValueError as e:
                show_snack(str(e))
                return
            page.dialog = None
            page.update()
            show_snack("Referencia actualizada.")
            refresh_ref_list()
            refresh_stats()

        page.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Editar — {row['supplier_name']}"),
            content=ft.Column([ef_ref, ef_desc, ef_cost], tight=True, width=420),
            actions=[
                ft.TextButton("Cancelar", on_click=close_dialog),
                ft.TextButton("Guardar", on_click=save_edit),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.dialog.open = True
        page.update()

    def open_ref_delete_dialog(row_id: int) -> None:
        row = get_price_row(conn, row_id)
        if not row:
            show_snack("Registro no encontrado.")
            return
        ref_lab = str(row["reference_raw"])
        prov = str(row["supplier_name"])

        def confirm_del(_: ft.ControlEvent | None = None) -> None:
            delete_price_row(conn, row_id)
            page.dialog = None
            page.update()
            show_snack(f"Eliminada «{ref_lab}» ({prov}).")
            refresh_ref_list()
            refresh_stats()

        page.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Eliminar referencia"),
            content=ft.Text(
                f"¿Eliminar la referencia «{ref_lab}» del proveedor «{prov}»?"
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=close_dialog),
                ft.TextButton(
                    "Eliminar",
                    on_click=confirm_del,
                    style=ft.ButtonStyle(color=ft.Colors.ERROR),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.dialog.open = True
        page.update()

    def ref_add_click(_: ft.ControlEvent | None = None) -> None:
        ref_crud_msg.value = ""
        sid_val = ref_new_supplier_dd.value
        if not sid_val:
            ref_crud_msg.value = (
                "No hay proveedores. Importe un Excel o cree datos antes de añadir referencias."
            )
            page.update()
            return
        ref_txt = (ref_new_reference.value or "").strip()
        if not ref_txt:
            ref_crud_msg.value = "Indique la referencia."
            page.update()
            return
        try:
            cost = float((ref_new_cost.value or "").replace(",", "."))
        except ValueError:
            ref_crud_msg.value = "Costo numérico no válido."
            page.update()
            return
        try:
            insert_price_row_manual(
                conn, int(sid_val), ref_txt, ref_new_desc.value, cost
            )
        except ValueError as e:
            ref_crud_msg.value = str(e)
            page.update()
            return
        except sqlite3.IntegrityError:
            ref_crud_msg.value = (
                "Ya existe esa referencia para el proveedor seleccionado."
            )
            page.update()
            return
        ref_new_reference.value = ""
        ref_new_desc.value = ""
        ref_new_cost.value = ""
        show_snack("Referencia creada.")
        refresh_ref_list()
        refresh_stats()

    def quick_add_supplier(_: ft.ControlEvent | None = None) -> None:
        n = (quick_supplier_name.value or "").strip()
        if not n:
            show_snack("Escriba el nombre del proveedor.")
            return
        upsert_supplier(conn, n)
        quick_supplier_name.value = ""
        show_snack(f"Proveedor «{n}» creado. Ya puede añadir referencias.")
        refresh_ref_supplier_options()
        refresh_ref_list()
        refresh_stats()

    users_panel = ft.Column(
        [
            ft.Text("Usuarios", style=ft.TextThemeStyle.TITLE_SMALL),
            ft.Text(
                "Alta de usuarios, contraseña, rol y bajas.",
                size=12,
                color=ft.Colors.ON_SURFACE_VARIANT,
            ),
            ft.Text("Registrar nuevo usuario", style=ft.TextThemeStyle.TITLE_SMALL),
            ft.Row(
                [
                    new_admin_username,
                    new_admin_password,
                    new_admin_role,
                    ft.ElevatedButton("Registrar usuario", on_click=admin_add_user),
                ],
                wrap=True,
                spacing=12,
            ),
            admin_form_msg,
            ft.Text("Cuentas del sistema", style=ft.TextThemeStyle.TITLE_SMALL),
            admin_users_list,
        ],
        spacing=12,
        visible=True,
    )

    refs_panel = ft.Column(
        [
            ft.Text("Referencias y costos", style=ft.TextThemeStyle.TITLE_SMALL),
            ft.Text(
                "Consulte, cree, edite o elimine precios por referencia y proveedor. "
                "Los cambios afectan las búsquedas de todos los usuarios.",
                size=12,
                color=ft.Colors.ON_SURFACE_VARIANT,
            ),
            ft.Row(
                [
                    quick_supplier_name,
                    ft.OutlinedButton(
                        "Crear proveedor vacío", on_click=quick_add_supplier
                    ),
                ],
                spacing=12,
                wrap=True,
            ),
            ft.Row(
                [
                    ref_filter_supplier_dd,
                    ref_search_field,
                    ft.ElevatedButton(
                        "Consultar", icon=ft.Icons.SEARCH, on_click=refresh_ref_list
                    ),
                ],
                wrap=True,
                spacing=12,
            ),
            ft.Text(
                "Proveedor | Referencia | Descripción | Costo",
                size=11,
                weight=ft.FontWeight.W_500,
            ),
            ref_list_column,
            ft.Divider(),
            ft.Text("Crear referencia", style=ft.TextThemeStyle.TITLE_SMALL),
            ft.Row(
                [
                    ref_new_supplier_dd,
                    ref_new_reference,
                    ref_new_desc,
                    ref_new_cost,
                    ft.ElevatedButton(
                        "Añadir", icon=ft.Icons.ADD, on_click=ref_add_click
                    ),
                ],
                wrap=True,
                spacing=12,
            ),
            ref_crud_msg,
        ],
        spacing=12,
        visible=True,
    )

    def logout(_: ft.ControlEvent | None = None) -> None:
        state["username"] = None
        state["user_id"] = None
        state["is_admin"] = False
        state["last_lines"] = []
        page.appbar = None
        auth_overlay.visible = True
        workspace.visible = False
        pass_field.value = ""
        page.update()

    def refresh_stats() -> None:
        n = count_all_prices(conn)
        sups = list_suppliers(conn)
        stats_text.value = f"Referencias en base: {n} — Proveedores: {len(sups)}"

    def go_main() -> None:
        auth_overlay.visible = False
        workspace.visible = True
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
        nav_rail.visible = state["is_admin"]
        rail_divider.visible = state["is_admin"]
        export_row.visible = state["is_admin"]
        role_hint.visible = not state["is_admin"]
        state["admin_tab"] = 0
        nav_rail.selected_index = 0
        panel_home.visible = True
        panel_import.visible = False
        panel_users.visible = False
        panel_refs.visible = False
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
        if not state["is_admin"]:
            page.snack_bar = ft.SnackBar(
                ft.Text("Solo un administrador puede cargar o actualizar archivos Excel.")
            )
            page.snack_bar.open = True
            page.update()
            return
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
        if panel_refs.visible:
            refresh_ref_supplier_options()
            refresh_ref_list()
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
        if not state["is_admin"]:
            page.snack_bar = ft.SnackBar(
                ft.Text("Solo un administrador puede exportar a Excel.")
            )
            page.snack_bar.open = True
            page.update()
            return
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
        if not state["is_admin"]:
            page.snack_bar = ft.SnackBar(
                ft.Text("Solo un administrador puede exportar el catálogo completo.")
            )
            page.snack_bar.open = True
            page.update()
            return
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

    role_hint = ft.Text(
        "Rol «Usuario»: puede buscar por referencia, ver la comparativa de proveedores y el texto "
        "de recomendación. La carga de Excel, la exportación y la gestión de cuentas están reservadas "
        "para administradores.",
        size=12,
        color=ft.Colors.ON_SURFACE_VARIANT,
        visible=False,
    )

    export_row = ft.Row(
        [
            ft.OutlinedButton("Exportar comparativa (Excel)", on_click=export_cmp_click),
            ft.OutlinedButton("Exportar catálogo completo", on_click=export_full_click),
        ],
        spacing=12,
        visible=False,
    )

    panel_import = ft.Column(
        [
            ft.Text("Importación de Excel", style=ft.TextThemeStyle.TITLE_MEDIUM),
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
            import_status,
        ],
        spacing=12,
        visible=False,
    )

    panel_home = ft.Column(
        [
            stats_text,
            role_hint,
            ft.Text("Búsqueda por referencia", style=ft.TextThemeStyle.TITLE_MEDIUM),
            ft.Row(
                [
                    ref_input,
                    sale_input,
                    ft.ElevatedButton(
                        "Buscar", icon=ft.Icons.SEARCH, on_click=do_search
                    ),
                ],
                spacing=12,
            ),
            table_box,
            ft.Text("Recomendación y cálculos", style=ft.TextThemeStyle.TITLE_SMALL),
            explain,
            export_row,
        ],
        spacing=16,
        visible=True,
    )

    panel_users = ft.Column(
        [users_panel],
        spacing=0,
        visible=False,
    )

    panel_refs = ft.Column(
        [refs_panel],
        spacing=0,
        visible=False,
    )

    def admin_nav_change(e: ft.ControlEvent) -> None:
        rail: ft.NavigationRail = e.control
        idx = rail.selected_index if rail.selected_index is not None else 0
        state["admin_tab"] = idx
        panel_home.visible = idx == 0
        panel_import.visible = idx == 1
        panel_users.visible = idx == 2
        panel_refs.visible = idx == 3
        if idx == 2:
            refresh_admin_user_rows()
        if idx == 3:
            refresh_ref_supplier_options()
            refresh_ref_list()
        page.update()

    nav_rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.NONE,
        extended=True,
        min_extended_width=200,
        group_alignment=-1.0,
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        visible=False,
        destinations=[
            ft.NavigationRailDestination(
                icon=ft.Icons.HOME_OUTLINED,
                selected_icon=ft.Icons.HOME,
                label="Inicio",
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.UPLOAD_FILE_OUTLINED,
                selected_icon=ft.Icons.UPLOAD_FILE,
                label="Importar",
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.PEOPLE_OUTLINE,
                selected_icon=ft.Icons.PEOPLE,
                label="Usuarios",
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.INVENTORY_2_OUTLINED,
                selected_icon=ft.Icons.INVENTORY_2,
                label="Referencias",
            ),
        ],
        on_change=admin_nav_change,
    )

    rail_divider = ft.VerticalDivider(width=1, visible=False)
    body_scroll = ft.Column(
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
        controls=[panel_home, panel_import, panel_users, panel_refs],
    )
    workspace = ft.Row(
        expand=True,
        spacing=0,
        controls=[
            nav_rail,
            rail_divider,
            ft.Container(expand=True, padding=ft.padding.only(left=16), content=body_scroll),
        ],
        visible=False,
    )

    page.services.extend([fp_import, save_compare, save_full])
    page.add(
        ft.Stack(
            expand=True,
            controls=[
                workspace,
                auth_overlay,
            ],
        )
    )


def _flet_cache_en_carpeta_proyecto() -> None:
    """Redirige la caché de Flet a la carpeta del repositorio (.flet_cache/client)."""
    import flet_desktop
    from pathlib import Path

    from proveedor_inteligente.core.config import get_flet_cache_dir

    base = get_flet_cache_dir()

    def _get_dir() -> Path:
        flavor = flet_desktop.__get_desktop_flavor()
        ver = flet_desktop.version.version
        return base / f"flet-desktop-{flavor}-{ver}"

    flet_desktop.__get_client_storage_dir = _get_dir  # type: ignore[method-assign]


def run_application() -> None:
    import os

    if os.environ.get("PROVEEDOR_USE_BROWSER", "").lower() in ("1", "true", "si", "yes"):
        ft.run(main, view=ft.AppView.WEB_BROWSER, host="127.0.0.1", port=0)
    else:
        _flet_cache_en_carpeta_proyecto()
        ft.run(main)
