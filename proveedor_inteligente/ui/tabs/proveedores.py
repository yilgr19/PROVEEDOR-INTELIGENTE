"""Pestaña Proveedores: listado y resumen de proveedores dados de alta."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import flet as ft

from proveedor_inteligente.data.database import list_suppliers_with_stats
from proveedor_inteligente.ui.tabs.common import fmt_created_at


@dataclass(frozen=True)
class ProveedoresTabBundle:
    panel: ft.Column
    refresh_list: Callable[[], None]


def create_proveedores_tab(
    page: ft.Page,
    conn: Any,
) -> ProveedoresTabBundle:
    list_column = ft.Column(spacing=10, tight=True)

    def refresh_list() -> None:
        list_column.controls.clear()
        try:
            rows = list_suppliers_with_stats(conn)
        except Exception as ex:
            list_column.controls.append(
                ft.Text(f"No se pudo cargar la lista: {ex}", color=ft.Colors.ERROR)
            )
            return
        if not rows:
            list_column.controls.append(
                ft.Text(
                    "Aún no hay proveedores. Use la pestaña Importar para crear el primero "
                    "al subir un Excel.",
                    size=13,
                    color=ft.Colors.BLUE_GREY_400,
                )
            )
            return
        for r in rows:
            name = str(r["name"])
            try:
                n_prices = int(r["price_count"] or 0)
            except (TypeError, ValueError):
                n_prices = 0
            try:
                upd = fmt_created_at(r["updated_at"])
            except (KeyError, TypeError):
                upd = "—"
            list_column.controls.append(
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=16, vertical=14),
                    bgcolor=ft.Colors.BLUE_GREY_50,
                    border_radius=10,
                    border=ft.border.all(1, ft.Colors.BLUE_GREY_100),
                    content=ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.STORE_OUTLINED,
                                color=ft.Colors.BLUE_700,
                                size=28,
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        name,
                                        size=16,
                                        weight=ft.FontWeight.W_600,
                                    ),
                                    ft.Text(
                                        f"{n_prices} referencias · Última actualización: {upd}",
                                        size=12,
                                        color=ft.Colors.BLUE_GREY_400,
                                    ),
                                ],
                                spacing=4,
                                tight=True,
                                expand=True,
                            ),
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )

    panel = ft.Column(
        [
            ft.Text(
                "Proveedores",
                size=20,
                weight=ft.FontWeight.W_600,
            ),
            ft.Text(
                "Proveedores registrados en la base de datos y carga de referencias por Excel.",
                size=12,
                color=ft.Colors.BLUE_GREY_400,
            ),
            list_column,
        ],
        spacing=12,
        tight=True,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    refresh_list()
    return ProveedoresTabBundle(panel=panel, refresh_list=refresh_list)
