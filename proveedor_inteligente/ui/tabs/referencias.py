"""Pestaña Referencias: CRUD de precios por referencia y proveedor (administradores)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

import flet as ft

from proveedor_inteligente.data.database import (
    delete_price_row,
    get_price_row,
    insert_price_row_manual,
    list_price_rows_admin,
    list_suppliers,
    update_price_row,
    upsert_supplier,
)


@dataclass(frozen=True)
class ReferenciasTabBundle:
    panel: ft.Column
    refresh_supplier_options: Callable[[], None]
    refresh_list: Callable[[], None]


def create_referencias_tab(
    page: ft.Page,
    conn: Any,
    refresh_stats: Callable[[], None],
    show_snack: Callable[[str], None],
    close_dialog: Callable[[ft.ControlEvent | None], None],
) -> ReferenciasTabBundle:
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
        height=320,
        tight=True,
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

    panel = ft.Column(
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
        tight=True,
        visible=True,
    )

    panel_outer = ft.Column([panel], spacing=0, tight=True)

    return ReferenciasTabBundle(
        panel=panel_outer,
        refresh_supplier_options=refresh_ref_supplier_options,
        refresh_list=refresh_ref_list,
    )
