"""SQLite local: inventario de costos por proveedor y referencia."""
from __future__ import annotations

import sqlite3
import re
from datetime import datetime, timezone
from typing import Any

from config import get_db_path

ROLE_ADMIN = "admin"
ROLE_USER = "user"


def normalize_role(value: str) -> str:
    r = (value or "").strip().lower()
    if r in ("admin", "administrador"):
        return ROLE_ADMIN
    return ROLE_USER


def normalize_reference(ref: str) -> str:
    s = (ref or "").strip().upper()
    s = re.sub(r"\s+", " ", s)
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
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM users WHERE role = ?", (ROLE_ADMIN,)
    ).fetchone()
    return int(row["c"]) if row else 0


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


def replace_supplier_prices(
    conn: sqlite3.Connection,
    supplier_id: int,
    rows: list[tuple[str, str, str | None, float, str | None]],
    source_file: str | None,
) -> int:
    """rows: (reference_raw, reference_norm, description, cost, optional)."""
    conn.execute("DELETE FROM price_rows WHERE supplier_id = ?", (supplier_id,))
    ts = now_iso()
    n = 0
    for ref_raw, ref_norm, desc, cost, _ in rows:
        if not ref_norm:
            continue
        try:
            c = float(cost)
        except (TypeError, ValueError):
            continue
        conn.execute(
            """
            INSERT INTO price_rows
            (supplier_id, reference_raw, reference_norm, description, cost, source_file, imported_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (supplier_id, ref_raw, ref_norm, desc, c, source_file, ts),
        )
        n += 1
    conn.commit()
    return n


def search_by_reference(
    conn: sqlite3.Connection, reference: str
) -> list[dict[str, Any]]:
    ref_norm = normalize_reference(reference)
    if not ref_norm:
        return []
    cur = conn.execute(
        """
        SELECT s.name AS supplier_name, p.reference_raw, p.description, p.cost, p.source_file, p.imported_at
        FROM price_rows p
        JOIN suppliers s ON s.id = p.supplier_id
        WHERE p.reference_norm = ?
        ORDER BY p.cost ASC, s.name COLLATE NOCASE
        """,
        (ref_norm,),
    )
    return [dict(r) for r in cur.fetchall()]


def count_all_prices(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM price_rows").fetchone()
    return int(row["c"]) if row else 0
