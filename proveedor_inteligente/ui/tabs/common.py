"""Textos de ayuda y utilidades compartidas entre pestañas."""
from __future__ import annotations

from datetime import datetime

MIN_USERNAME_LEN = 3
MIN_PASSWORD_LEN = 6


def fmt_created_at(raw: object) -> str:
    if raw is None:
        return "—"
    s = str(raw).strip()
    if not s:
        return "—"
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return s[:16]


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


def parse_sale_optional(raw: str | None) -> tuple[float | None, bool]:
    """Devuelve (valor o None, True si había texto pero no es número válido)."""
    s = (raw or "").strip().replace(",", ".")
    if not s:
        return None, False
    try:
        return float(s), False
    except ValueError:
        return None, True
