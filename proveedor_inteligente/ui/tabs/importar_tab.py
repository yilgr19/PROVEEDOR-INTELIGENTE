"""Pestaña Importar: carga y actualización de Excel de proveedores."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import flet as ft

from proveedor_inteligente.data.database import replace_supplier_prices, upsert_supplier
from proveedor_inteligente.services.excel_service import parse_supplier_excel


def create_import_tab(
    page: ft.Page,
    conn: Any,
    state: dict[str, Any],
    fp_import: ft.FilePicker,
    refresh_stats: Callable[[], None],
    on_import_maybe_refresh_refs: Callable[[], None],
) -> ft.Column:
    import_status = ft.Text()

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
        on_import_maybe_refresh_refs()
        page.update()

    return ft.Column(
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
        tight=True,
    )
