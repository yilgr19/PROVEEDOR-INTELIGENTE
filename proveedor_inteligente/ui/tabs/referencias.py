"""Pestaña Referencias: CRUD de precios por referencia y proveedor (administradores)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import flet as ft

from proveedor_inteligente.ui.tabs.common import (
    format_number_with_grouping,
    parse_locale_number,
)

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
    edit_price_row_id: list[int | None] = [None]

    ref_filter_supplier_dd = ft.Dropdown(width=220, label="Proveedor (filtro)")
    ref_search_field = ft.TextField(
        label="Buscar referencia o descripción",
        expand=True,
        on_submit=lambda _: refresh_ref_list(),
    )

    ref_list_column = ft.Column(
        spacing=10,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    ref_crud_msg = ft.Text(color=ft.Colors.ERROR, size=12)
    ref_new_supplier_dd = ft.Dropdown(width=200, label="Proveedor (alta)")
    ref_new_reference = ft.TextField(label="Referencia", width=160)
    ref_new_desc = ft.TextField(label="Descripción (opcional)", width=200)

    def _blur_cost(e: ft.ControlEvent) -> None:
        c = e.control
        t = (c.value or "").strip()
        if not t:
            return
        try:
            c.value = format_number_with_grouping(parse_locale_number(t))
        except ValueError:
            pass

    ref_new_cost = ft.TextField(
        label="Costo",
        width=120,
        hint_text="Ej. 1,234.56 o 1.234,56",
        on_blur=_blur_cost,
    )
    quick_supplier_name = ft.TextField(label="Nuevo Proveedor", width=220)

    form_section_title = ft.Text(
        "Nueva referencia manual",
        weight=ft.FontWeight.W_600,
    )
    cancel_edit_btn = ft.OutlinedButton(
        "Cancelar edición",
        visible=False,
        on_click=lambda _: cancel_edit_ref_form(),
    )
    ref_form_fab = ft.FloatingActionButton(
        icon=ft.Icons.ADD,
        tooltip="Añadir referencia",
        on_click=lambda _: ref_form_submit(),
        mini=True,
    )

    def cancel_edit_ref_form(_: Any = None) -> None:
        edit_price_row_id[0] = None
        ref_new_supplier_dd.disabled = False
        ref_new_reference.value = ""
        ref_new_desc.value = ""
        ref_new_cost.value = ""
        form_section_title.value = "Nueva referencia manual"
        ref_form_fab.icon = ft.Icons.ADD
        ref_form_fab.tooltip = "Añadir referencia"
        cancel_edit_btn.visible = False
        ref_crud_msg.value = ""
        page.update()

    def begin_edit_price_row(row_id: int) -> None:
        row = get_price_row(conn, row_id)
        if not row:
            show_snack("Referencia no encontrada.")
            return
        edit_price_row_id[0] = row_id
        ref_new_supplier_dd.value = str(row["supplier_id"])
        ref_new_supplier_dd.disabled = True
        ref_new_reference.value = str(row["reference_raw"])
        ref_new_desc.value = str(row["description"] or "")
        ref_new_cost.value = format_number_with_grouping(row["cost"])
        form_section_title.value = "Editar referencia"
        ref_form_fab.icon = ft.Icons.SAVE
        ref_form_fab.tooltip = "Guardar cambios"
        cancel_edit_btn.visible = True
        ref_crud_msg.value = ""
        page.update()

    def delete_price_row_now(row_id: int) -> None:
        row = get_price_row(conn, row_id)
        if not row:
            show_snack("Referencia no encontrada.")
            return
        ref_txt = str(row["reference_raw"])
        try:
            delete_price_row(conn, row_id)
        except Exception as ex:
            show_snack(f"No se pudo eliminar: {ex}")
            return
        show_snack(f"Referencia «{ref_txt}» eliminada de la base de datos.")
        if edit_price_row_id[0] == row_id:
            cancel_edit_ref_form()
        refresh_stats()
        refresh_ref_list()

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
        page.update()

    def refresh_ref_list(_: Any = None) -> None:
        ref_list_column.controls.clear()
        ref_crud_msg.value = ""

        sid = (
            None
            if ref_filter_supplier_dd.value in (None, "", "__all__")
            else int(ref_filter_supplier_dd.value)
        )
        q = (ref_search_field.value or "").strip()

        try:
            rows = list_price_rows_admin(conn, sid, q)
            if not rows:
                ref_list_column.controls.append(
                    ft.Text("No hay datos para mostrar.", color=ft.Colors.GREY_400)
                )

            for r in rows:
                rid = int(r["id"])
                ref_list_column.controls.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Text(
                                    str(r["supplier_name"]),
                                    width=100,
                                    weight="bold",
                                ),
                                ft.Text(str(r["reference_raw"]), width=110),
                                ft.Text(
                                    str(r["description"] or "")[:40],
                                    expand=True,
                                ),
                                ft.Text(
                                    f"${format_number_with_grouping(r['cost'])}",
                                    width=96,
                                ),
                                ft.OutlinedButton(
                                    "Modificar",
                                    tooltip="Cargar en el formulario inferior para editar",
                                    on_click=lambda e, tid=rid: begin_edit_price_row(tid),
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    icon_color=ft.Colors.ERROR,
                                    tooltip="Eliminar de la base de datos",
                                    on_click=lambda e, tid=rid: delete_price_row_now(tid),
                                ),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=10,
                        border=ft.border.all(1, ft.Colors.OUTLINE),
                        border_radius=8,
                    )
                )
        except Exception as ex:
            ref_crud_msg.value = f"Error: {ex}"

        page.update()

    def quick_add_supplier(_: Any) -> None:
        if quick_supplier_name.value:
            upsert_supplier(conn, quick_supplier_name.value)
            quick_supplier_name.value = ""
            refresh_ref_supplier_options()
            show_snack("Proveedor creado")

    def ref_form_submit(_: Any = None) -> None:
        if not ref_new_reference.value or not ref_new_cost.value:
            ref_crud_msg.value = "Faltan datos obligatorios"
            page.update()
            return
        try:
            cost = parse_locale_number(ref_new_cost.value or "")
            desc = (ref_new_desc.value or "").strip() or None
            rid_edit = edit_price_row_id[0]
            if rid_edit is not None:
                update_price_row(
                    conn,
                    rid_edit,
                    ref_new_reference.value,
                    desc or "",
                    cost,
                )
                show_snack("Cambios guardados en la base de datos.")
                cancel_edit_ref_form()
            else:
                insert_price_row_manual(
                    conn,
                    int(ref_new_supplier_dd.value),
                    ref_new_reference.value,
                    desc,
                    cost,
                )
                ref_new_reference.value = ""
                ref_new_desc.value = ""
                ref_new_cost.value = ""
                show_snack("Referencia añadida.")
            refresh_ref_list()
            refresh_stats()
        except Exception as e:
            ref_crud_msg.value = str(e)
        page.update()

    panel_principal = ft.Column(
        [
            ft.Text("Administración de Referencias", size=24, weight="bold"),
            ft.Row(
                [
                    quick_supplier_name,
                    ft.ElevatedButton(
                        "Crear Proveedor", on_click=quick_add_supplier
                    ),
                ]
            ),
            ft.Row(
                [
                    ref_filter_supplier_dd,
                    ref_search_field,
                    ft.ElevatedButton(
                        "Consultar",
                        icon=ft.Icons.SEARCH,
                        on_click=refresh_ref_list,
                    ),
                ]
            ),
            ft.Divider(),
            ref_list_column,
            ft.Divider(),
            form_section_title,
            ft.Row(
                [
                    ref_new_supplier_dd,
                    ref_new_reference,
                    ref_new_desc,
                    ref_new_cost,
                    cancel_edit_btn,
                    ref_form_fab,
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ref_crud_msg,
        ],
        expand=True,
        spacing=15,
    )

    return ReferenciasTabBundle(
        panel=panel_principal,
        refresh_supplier_options=refresh_ref_supplier_options,
        refresh_list=refresh_ref_list,
    )
