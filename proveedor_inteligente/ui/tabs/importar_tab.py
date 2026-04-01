"""Pestaña Importar: carga de Excel por proveedor (diseño de cuadrícula responsiva)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import flet as ft

from proveedor_inteligente.data.database import (
    delete_supplier,
    list_suppliers,
    merge_supplier_prices,
    upsert_supplier,
)
from proveedor_inteligente.services.excel_service import parse_supplier_excel


def create_import_tab(
    page: ft.Page,
    conn: Any,
    state: dict[str, Any],
    fp_import: ft.FilePicker,
    refresh_stats: Callable[[], None],
    on_import_maybe_refresh_refs: Callable[[], None],
) -> ft.Column:
    import_status = ft.Text(size=13, selectable=True, text_align=ft.TextAlign.CENTER)

    # CAMBIO: Usamos ResponsiveRow en lugar de Column para ver varias tarjetas por fila
    cards_grid = ft.ResponsiveRow(
        spacing=20,
        run_spacing=20,
    )

    def _apply_excel_file(path: Path, supplier_name_override: str | None) -> tuple[bool, str]:
        try:
            rows, stem = parse_supplier_excel(path)
            name = (supplier_name_override or stem).strip()
            if not name:
                return False, f"{path.name}: nombre de proveedor vacío"
            sid = upsert_supplier(conn, name)
            n_ins, n_upd, n_same, n_rem = merge_supplier_prices(
                conn, sid, rows, path.name
            )
            return True, (
                f"{name} — altas: {n_ins}, actualizadas: {n_upd}, "
                f"sin cambios: {n_same}, quitadas (ya no en Excel): {n_rem}."
            )
        except Exception as ex:
            return False, f"{path.name}: {ex}"

    async def _pick_new_suppliers(_: ft.ControlEvent | None = None) -> None:
        if not state["is_admin"]:
            page.snack_bar = ft.SnackBar(ft.Text("Solo un administrador puede importar archivos Excel."))
            page.snack_bar.open = True
            page.update()
            return

        files = await fp_import.pick_files(
            dialog_title="Seleccionar archivos Excel",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["xlsx", "xlsm"],
            allow_multiple=True,
        )
        if not files: return
        
        ok, errs = 0, []
        for f in files:
            if f.path:
                success, line = _apply_excel_file(Path(f.path), None)
                if success: ok += 1
                else: errs.append(line)
        
        import_status.value = f"Importados: {ok}. Errores: {len(errs)}"
        refresh_stats()
        on_import_maybe_refresh_refs()
        _rebuild_cards()
        page.update()

    def _make_pick_supplier(supplier_name: str):
        async def handler(_: ft.ControlEvent | None = None) -> None:
            if not state["is_admin"]: return
            files = await fp_import.pick_files(
                dialog_title=f"Actualizar «{supplier_name}»",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["xlsx", "xlsm"],
            )
            if not files or not files[0].path: return
            
            success, line = _apply_excel_file(Path(files[0].path), supplier_name)
            import_status.value = line
            refresh_stats()
            on_import_maybe_refresh_refs()
            _rebuild_cards()
            page.update()
        return handler

    def _make_delete_supplier(supplier_id: int, supplier_name: str):
        """Elimina en SQLite al clic (sin diálogo): IconButton+modal falla en Flet desktop con scroll."""

        def on_delete(_: ft.ControlEvent | None = None) -> None:
            if not state["is_admin"]:
                page.snack_bar = ft.SnackBar(
                    ft.Text("Solo un administrador puede eliminar proveedores.")
                )
                page.snack_bar.open = True
                page.update()
                return
            delete_supplier(conn, supplier_id)
            import_status.value = (
                f"SQLite: proveedor «{supplier_name}» y todas sus referencias de precios eliminados."
            )
            page.snack_bar = ft.SnackBar(
                ft.Text(f"Eliminado «{supplier_name}» y sus referencias.")
            )
            page.snack_bar.open = True
            refresh_stats()
            on_import_maybe_refresh_refs()
            _rebuild_cards()
            page.update()

        return on_delete

    def _supplier_card(name: str, on_import_click, on_delete_click) -> ft.Container:
        return ft.Container(
            col={"sm": 12, "md": 6, "lg": 4},
            content=ft.Card(
                elevation=2,
                content=ft.Container(
                    padding=20,
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.Icons.STORE, color=ft.Colors.BLUE_700),
                                    ft.Text(
                                        name,
                                        size=16,
                                        weight=ft.FontWeight.W_600,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                        expand=True,
                                    ),
                                    ft.OutlinedButton(
                                        "Eliminar",
                                        icon=ft.Icons.DELETE_OUTLINE,
                                        tooltip="Quitar proveedor y todas sus referencias en SQLite",
                                        style=ft.ButtonStyle(color=ft.Colors.ERROR),
                                        on_click=on_delete_click,
                                    ),
                                ],
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Text(
                                "Sustituye precios con un nuevo Excel.",
                                size=12,
                                color=ft.Colors.GREY_600,
                            ),
                            ft.TextButton(
                                "Importar Excel",
                                icon=ft.Icons.UPLOAD_FILE,
                                on_click=on_import_click,
                            ),
                        ],
                        spacing=10,
                        tight=True,
                    ),
                ),
            ),
        )

    def _add_supplier_card(on_import_click) -> ft.Container:
        return ft.Container(
            col={"sm": 12, "md": 6, "lg": 4},
            content=ft.Container(
                padding=20,
                bgcolor=ft.Colors.BLUE_50,
                border_radius=12,
                border=ft.border.all(1, ft.Colors.BLUE_100),
                on_click=on_import_click,
                content=ft.Column([
                    ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE, size=40, color=ft.Colors.BLUE_700),
                    ft.Text("Añadir proveedor", size=16, weight="bold"),
                    ft.Text("Carga archivos para crear nuevos proveedores", size=12, text_align="center"),
                ], horizontal_alignment="center", spacing=10)
            )
        )

    def _rebuild_cards() -> None:
        cards_grid.controls.clear()
        try:
            rows = list_suppliers(conn)
            for s in rows:
                sid = int(s["id"])
                nm = str(s["name"])
                cards_grid.controls.append(
                    _supplier_card(
                        nm,
                        _make_pick_supplier(nm),
                        _make_delete_supplier(sid, nm),
                    )
                )
        except Exception as ex:
            import_status.value = f"No se pudo cargar proveedores: {ex}"
        cards_grid.controls.append(_add_supplier_card(_pick_new_suppliers))

    _rebuild_cards()

    # Mismo ritmo que la pestaña Usuarios: título size=20 W_600, subtítulo size=12;
    # sin padding extra (el workspace ya aporta padding=24 en flet_app).
    return ft.Column(
        [
            ft.Text(
                "Importar proveedores",
                size=20,
                weight=ft.FontWeight.W_600,
            ),
            ft.Text(
                "Los precios se actualizan automáticamente al subir el archivo.",
                size=12,
                color=ft.Colors.BLUE_GREY_400,
            ),
            cards_grid,
            ft.Container(padding=ft.padding.only(top=4), content=import_status),
        ],
        spacing=12,
        tight=True,
    )