"""Textos de ayuda y utilidades compartidas entre pestañas."""
from __future__ import annotations

import math
from datetime import datetime

MIN_USERNAME_LEN = 3
MIN_PASSWORD_LEN = 6


def parse_locale_number(raw: str | None) -> float:
    """Interpreta números con separador de miles (y coma o punto decimal)."""
    s = (raw or "").strip().replace(" ", "").replace("\u00a0", "")
    if not s:
        raise ValueError("vacío")
    negative = s.startswith("-")
    if negative:
        s = s[1:].strip()
    if not s:
        raise ValueError("vacío")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, tail = s.rsplit(",", 1)
        if tail.isdigit() and len(tail) <= 2:
            s = head.replace(".", "") + "." + tail
        else:
            s = s.replace(",", "")
    elif "." in s:
        parts = s.split(".")
        if len(parts) == 2:
            left, right = parts[0].replace(",", ""), parts[1]
            if (
                right.isdigit()
                and len(right) == 3
                and left.isdigit()
                and left not in ("", "0")
                and not (len(left) > 1 and left.startswith("0"))
            ):
                s = left + right
            elif right.isdigit() and len(right) <= 2:
                s = left + "." + right
            elif right.isdigit():
                s = left + "." + right
            else:
                s = "".join(parts)
        else:
            s = "".join(parts)
    val = float(s)
    return -val if negative else val


def format_number_with_grouping(
    value: object, *, max_frac_digits: int = 10
) -> str:
    """Comas como separador de miles y punto decimal (p. ej. 1,234.56)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value) if value is not None else ""
    if math.isnan(f) or math.isinf(f):
        return ""
    txt = f"{f:,.{max_frac_digits}f}"
    if "." in txt:
        txt = txt.rstrip("0").rstrip(".")
    return txt


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
        f"para esta referencia: {format_number_with_grouping(best['cost'])} "
        "(lista ordenada de menor a mayor costo)."
    )
    if len(lines) > 1:
        blocks.append(
            "El costo más alto en la lista es "
            f"{format_number_with_grouping(worst['cost'])} («{worst['supplier_name']}»)."
        )
    if sale is not None:
        blocks.append(
            "\nGanancia por unidad según precio de venta "
            f"{format_number_with_grouping(sale)} (venta − costo proveedor):"
        )
        for line in lines:
            cost = float(line["cost"])
            gain = sale - cost
            pct = (gain / sale * 100.0) if sale else 0.0
            blocks.append(
                f"  • {line['supplier_name']}: "
                f"{format_number_with_grouping(gain)} u. "
                f"(margen sobre venta {format_number_with_grouping(pct, max_frac_digits=2)}%)."
            )
        bgain = sale - float(best["cost"])
        blocks.append(
            "\nCon el proveedor recomendado, cada unidad deja "
            f"{format_number_with_grouping(bgain)} frente a ese precio de venta."
        )
    else:
        blocks.append(
            "\nOpcional: puede indicar un precio de venta junto a la referencia para ver ganancias; "
            "si lo deja vacío, la búsqueda no se ve afectada."
        )
    return "\n".join(blocks)


def parse_sale_optional(raw: str | None) -> tuple[float | None, bool]:
    """Devuelve (valor o None, True si había texto pero no es número válido)."""
    s = (raw or "").strip()
    if not s:
        return None, False
    try:
        return parse_locale_number(s), False
    except ValueError:
        return None, True
