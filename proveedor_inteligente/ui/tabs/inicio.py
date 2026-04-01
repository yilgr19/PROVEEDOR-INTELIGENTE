"""Pestaña Inicio: estadísticas, búsqueda por referencia, tabla y exportación."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import flet as ft

from proveedor_inteligente.data.database import (
    count_all_prices,
    count_suppliers,
    list_offers_by_reference_norm,
    search_by_reference,
    top_suppliers_by_avg_cost,
)
from proveedor_inteligente.services.excel_service import export_comparison_excel, export_full_catalog
from proveedor_inteligente.ui.tabs.common import (
    build_explanation,
    format_number_with_grouping,
    parse_locale_number,
    parse_sale_optional,
)


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
    report_dynamic = ft.Column(spacing=12, tight=True, expand=True)

    catalog_stats = ft.Text(
        size=13,
        color=ft.Colors.BLUE_GREY_700,
    )

    admin_report = ft.Column(
        [
            ft.Text("Reporte general del sistema", size=20, weight=ft.FontWeight.W_700),
            ft.Text(
                "Resumen según datos importados (administradores).",
                size=12,
                color=ft.Colors.BLUE_GREY_500,
            ),
            report_dynamic,
        ],
        spacing=10,
        visible=False,
    )

    role_hint = ft.Text(
        "Rol «Usuario»: búsqueda por referencia, comparativa y análisis de recomendación. "
        "La importación y exportación a Excel están reservadas al administrador.",
        size=12,
        color=ft.Colors.BLUE_GREY_600,
        visible=False,
    )

    def _snack(msg: str) -> None:
        page.snack_bar = ft.SnackBar(ft.Text(msg))
        page.snack_bar.open = True
        page.update()

    ref_input = ft.TextField(
        label="Referencia o descripción",
        hint_text=(
            "1 carácter: referencia o descripción (orden A-Z). "
            "2+: referencia con ese prefijo o descripción que lo contenga. "
            "Rojo = mejor precio si hay varias filas iguales. ✓ = comparar proveedores."
        ),
        expand=True,
    )

    def _blur_sale(e: ft.ControlEvent) -> None:
        c = e.control
        t = (c.value or "").strip()
        if not t:
            return
        try:
            c.value = format_number_with_grouping(parse_locale_number(t))
        except ValueError:
            pass

    sale_input = ft.TextField(
        label="Precio de venta (opcional)",
        hint_text="Ej. 1,800,000 o 1800000",
        expand=True,
        on_blur=_blur_sale,
    )

    table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("#")),
            ft.DataColumn(ft.Text("Proveedor")),
            ft.DataColumn(ft.Text("Referencia")),
            ft.DataColumn(ft.Text("Costo")),
            ft.DataColumn(ft.Text("Ganancia / u.")),
            ft.DataColumn(ft.Text("Margen %")),
            ft.DataColumn(ft.Text("Elegir ref.")),
        ],
        rows=[],
        border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
        vertical_lines=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
        horizontal_lines=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
        heading_row_height=44,
        data_row_min_height=48,
    )

    focus_banner_text = ft.Text(
        size=13,
        color=ft.Colors.TEAL_900,
        expand=True,
    )
    back_focus_btn = ft.TextButton("Volver a la búsqueda")
    focus_banner = ft.Container(
        visible=False,
        padding=ft.padding.symmetric(horizontal=14, vertical=12),
        bgcolor=ft.Colors.TEAL_50,
        border_radius=8,
        border=ft.border.all(1, ft.Colors.TEAL_100),
        content=ft.Row(
            [
                ft.Icon(ft.Icons.FILTER_LIST_ALT, color=ft.Colors.TEAL_800, size=22),
                focus_banner_text,
                back_focus_btn,
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

    table_box = ft.Container(
        height=320,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=6,
        content=ft.Column(
            controls=[table],
            scroll=ft.ScrollMode.AUTO,
            tight=True,
        ),
    )

    def _mejor_opcion_indices(
        lines: list[dict[str, Any]], *, broad_mode: bool
    ) -> set[int]:
        """Índices con menor coste: vista comparativa = mínimo global; búsqueda = misma referencia o misma descripción (2+ filas)."""
        if not lines:
            return set()
        if not broad_mode:
            min_c = min(float(x["cost"]) for x in lines)
            return {i for i, x in enumerate(lines) if float(x["cost"]) == min_c}
        winners: set[int] = set()

        by_norm: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for idx, line in enumerate(lines):
            rn = str(line.get("reference_norm") or "")
            if rn:
                by_norm[rn].append((idx, float(line["cost"])))
        for items in by_norm.values():
            if len(items) < 2:
                continue
            min_c = min(c for _, c in items)
            for idx, c in items:
                if c == min_c:
                    winners.add(idx)

        by_desc: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for idx, line in enumerate(lines):
            d = (str(line.get("description") or "")).strip().lower()
            if d:
                by_desc[d].append((idx, float(line["cost"])))
        for items in by_desc.values():
            if len(items) < 2:
                continue
            min_c = min(c for _, c in items)
            for idx, c in items:
                if c == min_c:
                    winners.add(idx)

        return winners

    def _chip_mejor_opcion(*, vista_comparativa: bool) -> ft.Container:
        tip = (
            "Menor costo entre proveedores para esta referencia"
            if vista_comparativa
            else "Menor costo entre ofertas con la misma referencia o la misma descripción"
        )
        return ft.Container(
            content=ft.Text(
                "Mejor opción",
                size=10,
                weight=ft.FontWeight.W_700,
                color=ft.Colors.WHITE,
            ),
            bgcolor=ft.Colors.RED_700,
            padding=ft.padding.symmetric(horizontal=6, vertical=4),
            border_radius=4,
            tooltip=tip,
        )

    def _fill_results_table(
        lines: list[dict[str, Any]],
        sale: float | None,
        *,
        broad_mode: bool,
    ) -> None:
        table.rows.clear()
        mejor_idx = _mejor_opcion_indices(lines, broad_mode=broad_mode)
        for idx, line in enumerate(lines):
            disp = idx + 1
            cost = float(line["cost"])
            if sale is not None:
                gain = sale - cost
                margin = (gain / sale * 100.0) if sale else 0.0
                g_cell = f"${format_number_with_grouping(gain)}"
                m_cell = f"{format_number_with_grouping(margin, max_frac_digits=4)}%"
            else:
                g_cell = "—"
                m_cell = "—"
            ref_norm = str(line.get("reference_norm") or "")
            ref_raw = str(line["reference_raw"])
            action_parts: list[ft.Control] = []
            if broad_mode and ref_norm:
                action_parts.append(
                    ft.IconButton(
                        icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
                        icon_size=22,
                        tooltip="Ver esta referencia entre todos los proveedores (menor precio arriba)",
                        icon_color=ft.Colors.TEAL_700,
                        on_click=lambda e, rn=ref_norm, rr=ref_raw: _pick_reference_for_compare(
                            rn, rr
                        ),
                    ),
                )
            if idx in mejor_idx:
                action_parts.append(
                    _chip_mejor_opcion(vista_comparativa=not broad_mode),
                )
            if not action_parts:
                action_parts.append(
                    ft.Text(
                        "—",
                        size=11,
                        color=ft.Colors.BLUE_GREY_400,
                    ),
                )
            action_cell = ft.DataCell(
                ft.Row(
                    action_parts,
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            )
            table.rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(f"{disp:,}")),
                        ft.DataCell(ft.Text(str(line["supplier_name"]))),
                        ft.DataCell(ft.Text(ref_raw)),
                        ft.DataCell(ft.Text(f"${format_number_with_grouping(cost)}")),
                        ft.DataCell(ft.Text(g_cell)),
                        ft.DataCell(ft.Text(m_cell)),
                        action_cell,
                    ],
                ),
            )

    def _back_from_focus(_: ft.ControlEvent | None = None) -> None:
        broad = state.get("broad_search_lines")
        if not broad:
            state["focus_mode"] = False
            focus_banner.visible = False
            page.update()
            return
        sale, sale_bad = parse_sale_optional(sale_input.value)
        state["last_lines"] = broad
        state["last_ref"] = (ref_input.value or "").strip()
        state["last_sale"] = sale
        state["focus_mode"] = False
        state.pop("focus_ref_norm", None)
        state.pop("focus_reference_raw", None)
        focus_banner.visible = False
        _fill_results_table(broad, sale, broad_mode=True)
        if sale_bad:
            _snack("Precio de venta no válido; se ignoró para ganancias y márgenes.")
        page.update()

    def _pick_reference_for_compare(ref_norm: str, ref_raw: str) -> None:
        offers = list_offers_by_reference_norm(conn, ref_norm)
        if not offers:
            _snack("No hay ofertas para esa referencia.")
            return
        if (
            state.get("focus_mode")
            and state.get("focus_ref_norm") == ref_norm
            and len(state.get("last_lines") or []) == len(offers)
        ):
            _snack("Ya está viendo todas las ofertas de esta referencia (la 1.ª fila es la más barata).")
            return
        sale, sale_bad = parse_sale_optional(sale_input.value)
        state["last_lines"] = offers
        state["last_ref"] = ref_raw
        state["last_sale"] = sale
        state["focus_mode"] = True
        state["focus_ref_norm"] = ref_norm
        state["focus_reference_raw"] = ref_raw
        best = float(offers[0]["cost"])
        focus_banner_text.value = (
            f"Referencia «{ref_raw}»: {len(offers)} oferta(s) entre proveedores. "
            f"Fila 1 = menor costo (${format_number_with_grouping(best)})."
        )
        focus_banner.visible = True
        _fill_results_table(offers, sale, broad_mode=False)
        if sale_bad:
            _snack("Precio de venta no válido; se ignoró para ganancias y márgenes.")
        page.update()

    back_focus_btn.on_click = _back_from_focus

    def refresh_stats() -> None:
        n_refs = count_all_prices(conn)
        n_sups = count_suppliers(conn)
        catalog_stats.value = (
            f"Referencias en base: {n_refs:,} — Proveedores: {n_sups:,}"
        )

        report_dynamic.controls.clear()
        if not state.get("is_admin"):
            page.update()
            return

        card_suppliers = ft.Card(
            content=ft.Container(
                padding=22,
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.WAREHOUSE_OUTLINED, size=44, color=ft.Colors.BLUE_700),
                        ft.Column(
                            [
                                ft.Text(
                                    "Proveedores cargados",
                                    weight=ft.FontWeight.W_600,
                                    size=15,
                                ),
                                ft.Text(
                                    f"{n_sups:,}",
                                    size=34,
                                    weight=ft.FontWeight.W_800,
                                    color=ft.Colors.BLUE_700,
                                ),
                                ft.Text(
                                    f"Referencias en catálogo: {n_refs:,}",
                                    size=13,
                                    color=ft.Colors.BLUE_GREY_500,
                                ),
                            ],
                            spacing=6,
                            tight=True,
                            expand=True,
                        ),
                    ],
                    spacing=16,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ),
        )

        top_rows_col = ft.Column(spacing=8, tight=True)
        try:
            top_rows = top_suppliers_by_avg_cost(conn, limit=5)
        except Exception:
            top_rows = []

        if not top_rows:
            top_rows_col.controls.append(
                ft.Text(
                    "Aún no hay datos para el ranking.",
                    size=13,
                    color=ft.Colors.BLUE_GREY_500,
                )
            )
        else:
            for i, row in enumerate(top_rows, start=1):
                avg = float(row["avg_cost"] or 0)
                name = str(row["supplier_name"])
                top_rows_col.controls.append(
                    ft.Container(
                        padding=ft.padding.symmetric(vertical=8, horizontal=12),
                        bgcolor=ft.Colors.BLUE_GREY_50,
                        border_radius=8,
                        border=ft.border.all(1, ft.Colors.BLUE_GREY_100),
                        content=ft.Text(
                            f"{i}. {name} — coste medio $"
                            f"{format_number_with_grouping(avg)}",
                            size=13,
                        ),
                    )
                )

        card_top5 = ft.Card(
            content=ft.Container(
                padding=20,
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.LEADERBOARD_OUTLINED, color=ft.Colors.TEAL_700),
                                ft.Text(
                                    "Top 5 proveedores más económicos",
                                    weight=ft.FontWeight.W_600,
                                    size=15,
                                ),
                            ],
                            spacing=10,
                        ),
                        ft.Divider(height=1),
                        top_rows_col,
                    ],
                    spacing=12,
                    tight=True,
                ),
            ),
        )

        report_dynamic.controls.append(
            ft.ResponsiveRow(
                [
                    ft.Container(col={"sm": 12, "md": 6, "lg": 6}, content=card_suppliers),
                    ft.Container(col={"sm": 12, "md": 6, "lg": 6}, content=card_top5),
                ],
                spacing=16,
                run_spacing=16,
            ),
        )
        page.update()

    def _close_dialog(_: ft.ControlEvent | None = None) -> None:
        page.dialog.open = False
        page.update()

    def open_analysis(_: ft.ControlEvent | None = None) -> None:
        if state.get("focus_mode") and state.get("last_lines"):
            lines = list(state["last_lines"])
            ref = str(state.get("focus_reference_raw") or ref_input.value or "").strip()
        else:
            ref = (ref_input.value or "").strip()
            if not ref:
                _snack("Escriba una referencia y pulse Buscar (o abra el análisis tras buscar).")
                return
            lines = search_by_reference(conn, ref)
        sale, sale_bad = parse_sale_optional(sale_input.value)
        msg = build_explanation(lines, sale)
        if sale_bad:
            msg = (
                "El precio de venta no es un número válido; se ignoró para los cálculos.\n\n"
                + msg
            )
        page.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.TIPS_AND_UPDATES_OUTLINED),
                    ft.Text("Análisis de recomendación", weight=ft.FontWeight.W_600),
                ],
                tight=True,
            ),
            content=ft.Container(
                width=480,
                height=360,
                padding=ft.padding.only(top=8),
                content=ft.Column(
                    controls=[
                        ft.Text(
                            msg,
                            size=13,
                            selectable=True,
                        ),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                    tight=True,
                    expand=True,
                ),
            ),
            actions=[
                ft.TextButton("Cerrar", on_click=_close_dialog),
            ],
        )
        page.dialog.open = True
        page.update()

    def do_search(_: ft.ControlEvent | None = None) -> None:
        ref = (ref_input.value or "").strip()
        sale, sale_bad = parse_sale_optional(sale_input.value)
        lines = search_by_reference(conn, ref)
        state["broad_search_lines"] = lines
        state["last_lines"] = lines
        state["last_ref"] = ref
        state["last_sale"] = sale
        state["focus_mode"] = False
        state.pop("focus_ref_norm", None)
        state.pop("focus_reference_raw", None)
        focus_banner.visible = False

        _fill_results_table(lines, sale, broad_mode=True)

        if sale is not None:
            sale_input.value = format_number_with_grouping(sale)
        if sale_bad:
            _snack("Precio de venta no válido; se ignoró para ganancias y márgenes.")

        page.update()

    ref_input.on_submit = do_search
    sale_input.on_submit = do_search

    async def export_cmp_click(_: ft.ControlEvent | None = None) -> None:
        if not state.get("is_admin"):
            _snack("Solo un administrador puede exportar a Excel.")
            return
        if not state.get("last_lines"):
            _snack("Primero busque una referencia.")
            return
        sale, _ = parse_sale_optional(sale_input.value)
        if state.get("focus_mode") and state.get("last_lines"):
            lines = list(state["last_lines"])
            ref = str(state.get("focus_reference_raw") or state.get("last_ref") or "")
        else:
            ref = (ref_input.value or "").strip()
            lines = search_by_reference(conn, ref) if ref else list(state["last_lines"])
        msg = build_explanation(lines, sale)
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
                ref or state.get("last_ref", ""),
                sale,
                lines,
                msg,
            )
            _snack(f"Guardado: {path}")
        except Exception as ex:
            _snack(f"Error al guardar: {ex}")

    async def export_full_click(_: ft.ControlEvent | None = None) -> None:
        if not state.get("is_admin"):
            _snack("Solo un administrador puede exportar el catálogo completo.")
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
            _snack(f"Catálogo exportado: {path}")
        except Exception as ex:
            _snack(f"Error: {ex}")

    export_row = ft.Row(
        [
            ft.OutlinedButton(
                "Exportar comparativa (Excel)",
                icon=ft.Icons.DOWNLOAD_OUTLINED,
                on_click=export_cmp_click,
            ),
            ft.OutlinedButton(
                "Exportar catálogo completo",
                icon=ft.Icons.TABLE_CHART_OUTLINED,
                on_click=export_full_click,
            ),
        ],
        spacing=12,
        visible=False,
    )

    panel = ft.Column(
        [
            admin_report,
            catalog_stats,
            role_hint,
            ft.Divider(),
            ft.Text(
                "Búsqueda por referencia o descripción",
                size=18,
                weight=ft.FontWeight.W_700,
            ),
            ft.Row(
                [
                    ref_input,
                    ft.IconButton(
                        icon=ft.Icons.INSIGHTS_OUTLINED,
                        tooltip="Por qué se recomienda un proveedor (análisis)",
                        icon_color=ft.Colors.TEAL_700,
                        on_click=open_analysis,
                    ),
                    sale_input,
                    ft.IconButton(
                        icon=ft.Icons.SEARCH,
                        tooltip="Buscar",
                        icon_color=ft.Colors.BLUE_700,
                        on_click=do_search,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            focus_banner,
            table_box,
            export_row,
        ],
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    return InicioTabBundle(
        panel=panel,
        refresh_stats=refresh_stats,
        export_row=export_row,
        role_hint=role_hint,
        admin_report=admin_report,
    )
