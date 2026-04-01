"""SQLite local: inventario de costos por proveedor y referencia."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from proveedor_inteligente.core.config import get_db_path

ROLE_ADMIN = "admin"
ROLE_USER = "user"

# Máximo de filas devueltas en el panel Referencias (todos los productos hasta este tope).
ADMIN_PRICE_LIST_LIMIT = 15_000


def normalize_role(value: str) -> str:
    r = (value or "").strip().lower()
    if r in ("admin", "administrador"):
        return ROLE_ADMIN
    return ROLE_USER


def normalize_reference(ref: str) -> str:
    s = (ref or "").strip().upper()
    s = re.sub(r"\s+", " ", s)
    return s


# Separadores frecuentes en Excel (guiones, puntos, etc.); al quitarlos, "ABC-12" y "ABC12" coinciden.
_REF_COMPACT_STRIP = re.compile(r"[\s\-−_./\\|:·,;]+")


def normalize_reference_compact(ref: str) -> str:
    """
    Clave tolerante para búsqueda: mayúsculas y sin separadores habituales.
    Conserva letras, dígitos y símbolos que no sean esos separadores (p. ej. #, +, *).
    """
    if not ref:
        return ""
    s = str(ref).strip().upper()
    s = re.sub(r"\s+", "", s)
    s = _REF_COMPACT_STRIP.sub("", s)
    return s


def get_connection() -> sqlite3.Connection:
    path = get_db_path()
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash BLOB NOT NULL,
            created_at TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user'
        );

        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS price_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
            reference_raw TEXT NOT NULL,
            reference_norm TEXT NOT NULL,
            description TEXT,
            cost REAL NOT NULL,
            source_file TEXT,
            imported_at TEXT NOT NULL,
            UNIQUE (supplier_id, reference_norm)
        );

        CREATE INDEX IF NOT EXISTS ix_price_ref ON price_rows(reference_norm);
        CREATE INDEX IF NOT EXISTS ix_price_supplier ON price_rows(supplier_id);
        """
    )
    conn.commit()
    _migrate_users_role(conn)
    _migrate_price_rows_reference_compact(conn)


def _migrate_users_role(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(users)")
    cols = [row[1] for row in cur.fetchall()]
    if "role" in cols:
        return
    conn.execute(
        "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'"
    )
    conn.commit()
    first = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
    if first:
        conn.execute(
            "UPDATE users SET role = ? WHERE id = ?",
            (ROLE_ADMIN, first["id"]),
        )
    conn.commit()


def _migrate_price_rows_reference_compact(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(price_rows)")
    cols = [row[1] for row in cur.fetchall()]
    if "reference_compact" in cols:
        return
    conn.execute("ALTER TABLE price_rows ADD COLUMN reference_compact TEXT")
    conn.commit()
    for row in conn.execute("SELECT id, reference_raw, reference_norm FROM price_rows"):
        c = normalize_reference_compact(row["reference_raw"] or "") or normalize_reference_compact(
            row["reference_norm"] or ""
        )
        conn.execute(
            "UPDATE price_rows SET reference_compact = ? WHERE id = ?",
            (c, row["id"]),
        )
    conn.commit()
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_price_ref_compact ON price_rows(reference_compact)"
    )
    conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def user_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    return int(row["c"]) if row else 0


def create_user(
    conn: sqlite3.Connection,
    username: str,
    password_hash: bytes,
    role: str = ROLE_USER,
) -> int:
    role = normalize_role(role)
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, created_at, role) VALUES (?, ?, ?, ?)",
        (username.strip().lower(), password_hash, now_iso(), role),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_user_by_username(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    row = conn.execute(
        "SELECT * FROM users WHERE username = ?",
        (username.strip().lower(),),
    ).fetchone()
    return row


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def list_users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, username, role, created_at FROM users ORDER BY username COLLATE NOCASE"
    ).fetchall()


def count_admins(conn: sqlite3.Connection) -> int:
    """Cuenta administradores usando normalize_role (p. ej. 'admin' o 'administrador' en BD)."""
    rows = conn.execute("SELECT role FROM users").fetchall()
    return sum(
        1
        for row in rows
        if normalize_role(str(row["role"] or "")) == ROLE_ADMIN
    )


def set_user_password(
    conn: sqlite3.Connection, user_id: int, password_hash: bytes
) -> None:
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (password_hash, user_id),
    )
    conn.commit()


def set_user_role(conn: sqlite3.Connection, user_id: int, role: str) -> None:
    conn.execute(
        "UPDATE users SET role = ? WHERE id = ?",
        (normalize_role(role), user_id),
    )
    conn.commit()


def update_user_username(
    conn: sqlite3.Connection, user_id: int, new_username: str
) -> None:
    nu = new_username.strip().lower()
    if len(nu) < 3:
        raise ValueError("El usuario debe tener al menos 3 caracteres.")
    row_other = get_user_by_username(conn, nu)
    if row_other is not None and int(row_other["id"]) != user_id:
        raise ValueError("Ese nombre de usuario ya está en uso.")
    conn.execute("UPDATE users SET username = ? WHERE id = ?", (nu, user_id))
    conn.commit()


def delete_user(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()


def user_is_admin(row: sqlite3.Row | dict[str, Any]) -> bool:
    r = row["role"] if isinstance(row, dict) else row["role"]
    return normalize_role(str(r)) == ROLE_ADMIN


def list_suppliers(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, name, updated_at FROM suppliers ORDER BY name COLLATE NOCASE"
    ).fetchall()


def list_suppliers_with_stats(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Id, nombre, updated_at y número de filas de precios (referencias) por proveedor."""
    return conn.execute(
        """
        SELECT s.id, s.name, s.updated_at,
               (SELECT COUNT(*) FROM price_rows p WHERE p.supplier_id = s.id) AS price_count
        FROM suppliers s
        ORDER BY s.name COLLATE NOCASE
        """
    ).fetchall()


def upsert_supplier(conn: sqlite3.Connection, name: str) -> int:
    name = name.strip()
    if not name:
        raise ValueError("Nombre de proveedor vacío")
    row = conn.execute("SELECT id FROM suppliers WHERE name = ?", (name,)).fetchone()
    if row:
        conn.execute(
            "UPDATE suppliers SET updated_at = ? WHERE id = ?",
            (now_iso(), row["id"]),
        )
        conn.commit()
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO suppliers (name, updated_at) VALUES (?, ?)",
        (name, now_iso()),
    )
    conn.commit()
    return int(cur.lastrowid)


def delete_supplier(conn: sqlite3.Connection, supplier_id: int) -> None:
    """Quita en SQLite todas las referencias/precios del proveedor y luego la fila del proveedor."""
    conn.execute("DELETE FROM price_rows WHERE supplier_id = ?", (supplier_id,))
    conn.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
    conn.commit()


def _float_equal(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) < 1e-9


def merge_supplier_prices(
    conn: sqlite3.Connection,
    supplier_id: int,
    rows: list[tuple[str, str, str | None, float, str | None]],
    source_file: str | None,
) -> tuple[int, int, int, int]:
    """
    rows: (reference_raw, reference_norm, description, cost, optional).

    - Referencia ya existente (mismo supplier + reference_norm): solo ejecuta UPDATE si
      cambian coste, descripción, texto crudo o reference_compact.
    - Referencia nueva: INSERT.
    - Filas en BD para ese proveedor cuya reference_norm no viene en el Excel: DELETE
      (el archivo es la foto actual del catálogo).

    Devuelve (insertadas, actualizadas, sin_cambios, eliminadas_en_bd).
    """
    ts = now_iso()
    norms_in_file: set[str] = set()
    parsed: list[tuple[str, str, str | None, float, str]] = []
    for ref_raw, ref_norm, desc, cost, _ in rows:
        if not ref_norm:
            continue
        try:
            c = float(cost)
        except (TypeError, ValueError):
            continue
        rraw = (ref_raw or "").strip()
        norms_in_file.add(ref_norm)
        ref_compact = normalize_reference_compact(rraw) or normalize_reference_compact(ref_norm)
        parsed.append((rraw, ref_norm, desc, c, ref_compact))

    n_ins = n_upd = n_same = 0
    for rraw, ref_norm, desc, c, ref_compact in parsed:
        d = ((desc or "").strip() or None)
        row = conn.execute(
            """
            SELECT cost, description, reference_raw, reference_compact
            FROM price_rows
            WHERE supplier_id = ? AND reference_norm = ?
            """,
            (supplier_id, ref_norm),
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO price_rows
                (supplier_id, reference_raw, reference_norm, reference_compact,
                 description, cost, source_file, imported_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (supplier_id, rraw, ref_norm, ref_compact, d, c, source_file, ts),
            )
            n_ins += 1
        else:
            old_c = float(row["cost"])
            old_d = row["description"]
            if old_d is not None:
                old_d = str(old_d).strip() or None
            old_r = (row["reference_raw"] or "").strip()
            old_rc = str(row["reference_compact"] or "")
            changed = (
                not _float_equal(old_c, c)
                or (old_d or "") != (d or "")
                or old_r != rraw
                or old_rc != (ref_compact or "")
            )
            if changed:
                conn.execute(
                    """
                    UPDATE price_rows SET
                        reference_raw = ?,
                        reference_compact = ?,
                        description = ?,
                        cost = ?,
                        source_file = ?,
                        imported_at = ?
                    WHERE supplier_id = ? AND reference_norm = ?
                    """,
                    (rraw, ref_compact, d, c, source_file, ts, supplier_id, ref_norm),
                )
                n_upd += 1
            else:
                n_same += 1

    n_rem = 0
    for pr in conn.execute(
        "SELECT id, reference_norm FROM price_rows WHERE supplier_id = ?",
        (supplier_id,),
    ).fetchall():
        if pr["reference_norm"] not in norms_in_file:
            conn.execute("DELETE FROM price_rows WHERE id = ?", (int(pr["id"]),))
            n_rem += 1

    conn.commit()
    return (n_ins, n_upd, n_same, n_rem)


def search_by_reference(
    conn: sqlite3.Connection, reference: str
) -> list[dict[str, Any]]:
    ref_norm = normalize_reference(reference)
    ref_c = normalize_reference_compact(reference)
    if not ref_norm and not ref_c:
        return []
    clauses: list[str] = []
    args: list[Any] = []
    if ref_norm:
        clauses.append("p.reference_norm = ?")
        args.append(ref_norm)
    if ref_c:
        clauses.append("p.reference_compact = ?")
        args.append(ref_c)
    cur = conn.execute(
        f"""
        SELECT s.name AS supplier_name, p.reference_raw, p.description, p.cost, p.source_file, p.imported_at
        FROM price_rows p
        JOIN suppliers s ON s.id = p.supplier_id
        WHERE ({' OR '.join(clauses)})
        ORDER BY p.cost ASC, s.name COLLATE NOCASE
        """,
        args,
    )
    return [dict(r) for r in cur.fetchall()]


def count_all_prices(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM price_rows").fetchone()
    return int(row["c"]) if row else 0


def count_suppliers(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM suppliers").fetchone()
    return int(row["c"]) if row else 0


def top_suppliers_by_avg_cost(
    conn: sqlite3.Connection, *, limit: int = 5
) -> list[sqlite3.Row]:
    """Proveedores con menor coste medio sobre sus productos (datos cargados por Excel)."""
    return conn.execute(
        """
        SELECT s.name AS supplier_name,
               AVG(p.cost) AS avg_cost,
               COUNT(p.id) AS n_prices
        FROM suppliers s
        INNER JOIN price_rows p ON p.supplier_id = s.id
        GROUP BY s.id, s.name
        ORDER BY AVG(p.cost) ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def get_price_row(conn: sqlite3.Connection, row_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT p.*, s.name AS supplier_name
        FROM price_rows p
        JOIN suppliers s ON s.id = p.supplier_id
        WHERE p.id = ?
        """,
        (row_id,),
    ).fetchone()


def list_price_rows_admin(
    conn: sqlite3.Connection,
    supplier_id: int | None = None,
    ref_substring: str = "",
    limit: int = ADMIN_PRICE_LIST_LIMIT,
) -> list[sqlite3.Row]:
    """Listado para panel admin: filtro opcional por proveedor y texto en referencia/descripción."""
    ref_substring = (ref_substring or "").strip()
    q = """
        SELECT p.id, p.supplier_id, s.name AS supplier_name, p.reference_raw,
               p.description, p.cost, p.source_file, p.imported_at
        FROM price_rows p
        JOIN suppliers s ON s.id = p.supplier_id
        WHERE 1=1
    """
    args: list[Any] = []
    if supplier_id is not None:
        q += " AND p.supplier_id = ?"
        args.append(supplier_id)
    if ref_substring:
        like_raw = f"%{ref_substring}%"
        like_norm = f"%{normalize_reference(ref_substring)}%"
        sub_compact = normalize_reference_compact(ref_substring)
        or_parts = [
            "p.reference_raw LIKE ? ESCAPE '\\'",
            "p.reference_norm LIKE ? ESCAPE '\\'",
            "(p.description IS NOT NULL AND p.description LIKE ? ESCAPE '\\')",
        ]
        like_args: list[str] = [like_raw, like_norm, like_raw]
        if sub_compact:
            or_parts.append("p.reference_compact LIKE ? ESCAPE '\\'")
            like_args.append(f"%{sub_compact}%")
        q += " AND (" + " OR ".join(or_parts) + ")"
        args.extend(like_args)
    q += " ORDER BY s.name COLLATE NOCASE, p.reference_norm COLLATE NOCASE LIMIT ?"
    args.append(limit)
    return conn.execute(q, args).fetchall()


def insert_price_row_manual(
    conn: sqlite3.Connection,
    supplier_id: int,
    reference_raw: str,
    description: str | None,
    cost: float,
    source_file: str | None = "manual",
) -> int:
    ref_norm = normalize_reference(reference_raw)
    if not ref_norm:
        raise ValueError("La referencia no puede estar vacía.")
    ref_compact = normalize_reference_compact(reference_raw) or normalize_reference_compact(ref_norm)
    cur = conn.execute(
        """
        INSERT INTO price_rows
        (supplier_id, reference_raw, reference_norm, reference_compact,
         description, cost, source_file, imported_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            supplier_id,
            reference_raw.strip(),
            ref_norm,
            ref_compact,
            (description or "").strip() or None,
            float(cost),
            source_file or "manual",
            now_iso(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_price_row(
    conn: sqlite3.Connection,
    row_id: int,
    reference_raw: str,
    description: str | None,
    cost: float,
) -> None:
    row = conn.execute(
        "SELECT supplier_id FROM price_rows WHERE id = ?", (row_id,)
    ).fetchone()
    if not row:
        raise ValueError("El registro no existe.")
    supplier_id = int(row["supplier_id"])
    ref_norm = normalize_reference(reference_raw)
    if not ref_norm:
        raise ValueError("La referencia no puede estar vacía.")
    dup = conn.execute(
        """
        SELECT id FROM price_rows
        WHERE supplier_id = ? AND reference_norm = ? AND id != ?
        """,
        (supplier_id, ref_norm, row_id),
    ).fetchone()
    if dup:
        raise ValueError("Ya existe esa referencia para este proveedor.")
    ref_compact = normalize_reference_compact(reference_raw) or normalize_reference_compact(ref_norm)
    conn.execute(
        """
        UPDATE price_rows
        SET reference_raw = ?, reference_norm = ?, reference_compact = ?, description = ?, cost = ?
        WHERE id = ?
        """,
        (
            reference_raw.strip(),
            ref_norm,
            ref_compact,
            (description or "").strip() or None,
            float(cost),
            row_id,
        ),
    )
    conn.commit()


def delete_price_row(conn: sqlite3.Connection, row_id: int) -> None:
    conn.execute("DELETE FROM price_rows WHERE id = ?", (row_id,))
    conn.commit()
