"""Pestaña Referencias: CRUD de precios por referencia y proveedor (administradores)."""
from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable
import flet as ft

from proveedor_inteligente.data.database import (
    ADMIN_PRICE_LIST_LIMIT,
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
    
    # --- CONTROLES DE UI ---
    ref_filter_supplier_dd = ft.Dropdown(width=220, label="Proveedor (filtro)")
    ref_search_field = ft.TextField(
        label="Buscar referencia o descripción",
        expand=True,
        on_submit=lambda _: refresh_ref_list()
    )
    
    # IMPORTANTE: El scroll se define en la Columna, NO en el Container
    ref_list_column = ft.Column(
        spacing=10, 
        scroll=ft.ScrollMode.AUTO, 
        expand=True
    )
    
    ref_crud_msg = ft.Text(color=ft.Colors.ERROR, size=12)
    ref_new_supplier_dd = ft.Dropdown(width=200, label="Proveedor (alta)")
    ref_new_reference = ft.TextField(label="Referencia", width=160)
    ref_new_desc = ft.TextField(label="Descripción (opcional)", width=200)
    ref_new_cost = ft.TextField(label="Costo", width=100)
    quick_supplier_name = ft.TextField(label="Nuevo Proveedor", width=220)

    # --- LÓGICA DE REFRESCO ---
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
        
        sid = None if ref_filter_supplier_dd.value in (None, "", "__all__") else int(ref_filter_supplier_dd.value)
        q = (ref_search_field.value or "").strip()
        
        try:
            rows = list_price_rows_admin(conn, sid, q)
            if not rows:
                ref_list_column.controls.append(ft.Text("No hay datos para mostrar.", color=ft.Colors.GREY_400))
            
            for r in rows:
                rid = int(r["id"])
                ref_list_column.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Text(str(r["supplier_name"]), width=100, weight="bold"),
                            ft.Text(str(r["reference_raw"]), width=110),
                            ft.Text(str(r["description"] or "")[:40], expand=True),
                            ft.Text(f"${r['cost']}", width=80),
                            ft.IconButton(ft.Icons.EDIT, on_click=lambda e, i=rid: open_ref_edit_dialog(i)),
                            ft.IconButton(ft.Icons.DELETE, icon_color=ft.Colors.ERROR, on_click=lambda e, i=rid: open_ref_delete_dialog(i)),
                        ]),
                        padding=10,
                        border=ft.border.all(1, ft.Colors.OUTLINE),
                        border_radius=8
                    )
                )
        except Exception as ex:
            ref_crud_msg.value = f"Error: {ex}"
        
        page.update()

    # --- DIÁLOGOS ---
    def open_ref_edit_dialog(row_id: int) -> None:
        row = get_price_row(conn, row_id)
        if not row: return
        
        ef_ref = ft.TextField(label="Referencia", value=str(row["reference_raw"]))
        ef_cost = ft.TextField(label="Costo", value=str(row["cost"]))

        def save_edit(_):
            try:
                update_price_row(conn, row_id, ef_ref.value, "", float(ef_cost.value))
                page.dialog.open = False
                refresh_ref_list()
                show_snack("Actualizado con éxito")
            except Exception as e:
                show_snack(f"Error: {e}")
            page.update()

        page.dialog = ft.AlertDialog(
            title=ft.Text("Editar Referencia"),
            content=ft.Column([ef_ref, ef_cost], tight=True),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: setattr(page.dialog, 'open', False)),
                ft.TextButton("Guardar", on_click=save_edit)
            ]
        )
        page.dialog.open = True
        page.update()

    def open_ref_delete_dialog(row_id: int) -> None:
        def confirm_del(_):
            delete_price_row(conn, row_id)
            page.dialog.open = False
            refresh_ref_list()
            show_snack("Referencia eliminada")
            page.update()

        page.dialog = ft.AlertDialog(
            title=ft.Text("¿Eliminar?"),
            content=ft.Text("Esta acción no se puede deshacer."),
            actions=[
                ft.TextButton("No", on_click=lambda _: setattr(page.dialog, 'open', False)),
                ft.TextButton("Sí, eliminar", on_click=confirm_del, color=ft.Colors.ERROR)
            ]
        )
        page.dialog.open = True
        page.update()

    def quick_add_supplier(_: Any):
        if quick_supplier_name.value:
            upsert_supplier(conn, quick_supplier_name.value)
            quick_supplier_name.value = ""
            refresh_ref_supplier_options()
            show_snack("Proveedor creado")

    def ref_add_click(_: Any):
        if not ref_new_reference.value or not ref_new_cost.value:
            ref_crud_msg.value = "Faltan datos obligatorios"
            page.update()
            return
        try:
            insert_price_row_manual(conn, int(ref_new_supplier_dd.value), ref_new_reference.value, ref_new_desc.value, float(ref_new_cost.value))
            ref_new_reference.value = ""
            ref_new_cost.value = ""
            refresh_ref_list()
            show_snack("Referencia añadida")
        except Exception as e:
            ref_crud_msg.value = str(e)
            page.update()

    # --- DISEÑO FINAL ---
    panel_principal = ft.Column(
        [
            ft.Text("Administración de Referencias", size=24, weight="bold"),
            ft.Row([quick_supplier_name, ft.ElevatedButton("Crear Proveedor", on_click=quick_add_supplier)]),
            ft.Row([ref_filter_supplier_dd, ref_search_field, ft.ElevatedButton("Consultar", icon=ft.Icons.SEARCH, on_click=refresh_ref_list)]),
            ft.Divider(),
            
            # La lista de productos ocupará el espacio central
            ref_list_column, 
            
            ft.Divider(),
            ft.Text("Nueva Referencia Manual", weight="bold"),
            ft.Row([ref_new_supplier_dd, ref_new_reference, ref_new_desc, ref_new_cost, ft.FloatingActionButton(icon=ft.Icons.ADD, on_click=ref_add_click, mini=True)]),
            ref_crud_msg
        ],
        expand=True,
        spacing=15
    )

    return ReferenciasTabBundle(
        panel=panel_principal,
        refresh_supplier_options=refresh_ref_supplier_options,
        refresh_list=refresh_ref_list,
    )