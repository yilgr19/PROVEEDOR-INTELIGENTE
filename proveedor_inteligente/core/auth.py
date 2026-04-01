"""Contraseñas con bcrypt; sin acceso externo — solo usuarios creados en la app."""
from __future__ import annotations

import hashlib

import bcrypt


def _password_bytes(plain: str) -> bytes:
    """Digest fijo (32 B) para evitar el límite de 72 bytes de bcrypt con contraseñas largas."""
    return hashlib.sha256(plain.encode("utf-8")).digest()


def _coerce_hash(hashed: bytes | bytearray | memoryview | None) -> bytes | None:
    if hashed is None:
        return None
    if isinstance(hashed, memoryview):
        return hashed.tobytes()
    if isinstance(hashed, bytearray):
        return bytes(hashed)
    if isinstance(hashed, bytes):
        return hashed
    try:
        return bytes(hashed)
    except Exception:
        return None


def hash_password(plain: str) -> bytes:
    if plain is None:
        raise ValueError("La contraseña no puede estar vacía.")
    return bcrypt.hashpw(_password_bytes(plain), bcrypt.gensalt(rounds=12))


def verify_password(plain: str, hashed: bytes | memoryview | bytearray | None) -> bool:
    hb = _coerce_hash(hashed)
    if not plain or hb is None:
        return False
    try:
        raw = plain.encode("utf-8")
        # bcrypt rechaza contraseñas > 72 B en texto plano; esos usuarios solo pueden coincidir con digest.
        if len(raw) <= 72 and bcrypt.checkpw(raw, hb):
            return True
        return bcrypt.checkpw(_password_bytes(plain), hb)
    except Exception:
        return False
