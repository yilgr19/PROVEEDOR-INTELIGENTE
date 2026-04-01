"""Pestaña Inicio: estadísticas, búsqueda por referencia, tabla y exportación."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import flet as ft

from proveedor_inteligente.data.database import (
    count_all_prices,
    count_suppliers,
    list_suppliers,
    search_by_reference,
    top_suppliers_by_avg_cost,
)
from proveedor_inteligente.services.excel_service import export_comparison_excel, export_full_catalog
from proveedor_inteligente.ui.tabs.common import build_explanation, parse_sale_optional


@dataclass(frozen=True)
class InicioTabBundle:
    panel: ft.Column
    refresh_stats: Callable[[], None]
    export_row: ft.Row
    role_hint: ft.Text
    admin_report: ft.Column


def create_inicio_tab(
    page: ft.Page,
    conn: Any,
    state: dict[str, Any],
    save_compare: ft.FilePicker,
    save_full: ft.FilePicker,
) -> InicioTabBundle:
    stats_text = ft.Text()
    report_dynamic = ft.Column(spacing=12, tight=True)

    admin_report = ft.Column(
        [
            ft.Text("Reporte general", style=ft.TextThemeStyle.TITLE_MEDIUM),
            ft.Text(
                "Resumen según datos importados desde Excel (costes en catálogo).",
                size=12,
                color=ft.Colors.BLUE_GREY_400,
            ),
            report_dynamic,
        ],
        spacing=8,
        tight=True,
        visible=False,
    )

    role_hint = ft.Text(
        "Rol «Usuario»: puede buscar por referencia, ver la comparativa de proveedores y el texto "
        "de recomendación. La carga de Excel, la exportación y la gestión de cuentas están reservadas "
        "para administradores.",
        size=12,
        color=ft.Colors.ON_SURFACE_VARIANT,
        visible=False,
    )

    ref_input = ft.TextField(
        label="Referencia del producto",
        hint_text="Letras, números y símbolos. No hace falta poner guiones si en el Excel van con guión.",
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
            tight=True,
        ),
    )

    explain = ft.Text(selectable=True)

    def refresh_stats() -> None:
        n = count_all_prices(conn)
        sups = list_suppliers(conn)
        stats_text.value = f"Referencias en base: {n} — Proveedores: {len(sups)}"

        report_dynamic.controls.clear()
        if not state.get("is_admin"):
            return
        nsup = count_suppliers(conn)
        report_dynamic.controls.append(
            ft.Card(
                content=ft.Container(
                    padding=20,
                    content=ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.WAREHOUSE_OUTLINED,
                                size=40,
                                color=ft.Colors.BLUE_700,
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        "Proveedores cargados",
                                        weight=ft.FontWeight.W_600,
                                        size=14,
                                    ),
                                    ft.Text(
                                        str(nsup),
                                        size=32,
                                        weight=ft.FontWeight.W_700,
                                        color=ft.Colors.BLUE_700,
                                    ),
                                    ft.Text(
                                        f"Referencias con precio en catálogo: {n}",
                                        size=12,
                                        color=ft.Colors.BLUE_GREY_400,
                                    ),
                                ],
                                spacing=4,
                                tight=True,
                                expand=True,
                            ),
                        ],
                        spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ),
            )
        )
        top_title = ft.Text(
            "Top 5 proveedores más económicos (menor coste medio por producto)",
            weight=ft.FontWeight.W_600,
            size=14,
        )
        try:
            top = top_suppliers_by_avg_cost(conn, limit=5)
        except Exception as ex:
            report_dynamic.controls.extend(
                [
                    top_title,
                    ft.Text(f"No se pudo calcular el ranking: {ex}", color=ft.Colors.ERROR),
                ]
            )
            return

        if not top:
            report_dynamic.controls.extend(
                [
                    top_title,
                    ft.Text(
                        "Aún no hay costes importados. Use la pestaña Importar para cargar Excel.",
                        size=13,
                        color=ft.Colors.BLUE_GREY_400,
                    ),
                ]
            )
            return

        top_rows_col = ft.Column(spacing=8, tight=True)
        for i, row in enumerate(top, start=1):
            name = str(row["supplier_name"])
            avg = float(row["avg_cost"] or 0)
            n_pr = int(row["n_prices"] or 0)
            top_rows_col.controls.append(
                ft.Container(
                    padding=ft.padding.symmetric(vertical=10, horizontal=12),
                    bgcolor=ft.Colors.BLUE_GREY_50,
                    border_radius=8,
                    border=ft.border.all(1, ft.Colors.BLUE_GREY_100),
                    content=ft.Row(
                        [
                            ft.Container(
                                width=28,
                                alignment=ft.Alignment.CENTER,
                                content=ft.Text(
                                    str(i),
                                    weight=ft.FontWeight.W_700,
                                    color=ft.Colors.BLUE_700,
                                ),
                            ),
                            ft.Column(
                                [
                                    ft.Text(name, weight=ft.FontWeight.W_600, size=14),
                                    ft.Text(
                                        f"Coste medio: {avg:.4f} · {n_pr} referencias",
                                        size=12,
                                        color=ft.Colors.BLUE_GREY_400,
                                    ),
                                ],
                                spacing=2,
                                tight=True,
                                expand=True,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )
        report_dynamic.controls.extend(
            [
                top_title,
                ft.Card(
                    elevation=0,
                    content=ft.Container(padding=8, content=top_rows_col),
                ),
            ]
        )

    def do_search(_: ft.ControlEvent | None = None) -> None:
        ref = (ref_input.value or "").strip()
        sale, sale_bad = parse_sale_optional(sale_input.value)
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
                "El precio de venta no es un número válido; se ignoró para los cálculos.\n\n"
                + msg
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

    export_row = ft.Row(
        [
            ft.OutlinedButton("Exportar comparativa (Excel)", on_click=export_cmp_click),
            ft.OutlinedButton("Exportar catálogo completo", on_click=export_full_click),
        ],
        spacing=12,
        visible=False,
    )

    panel = ft.Column(
        [
            admin_report,
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
        tight=True,
        visible=True,
    )

    return InicioTabBundle(
        panel=panel,
        refresh_stats=refresh_stats,
        export_row=export_row,
        role_hint=role_hint,
        admin_report=admin_report,
    )
