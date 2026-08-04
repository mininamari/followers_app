from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
from typing import Optional

from core.config import DB_PATH, PERMISSIONS
from core.i18n import tr


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return "pbkdf2_sha256$200000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iters))
        return hmac.compare_digest(got, expected)
    except Exception:
        return False


def has_permission(user: Optional[dict], permission: str) -> bool:
    if not user:
        return False
    return permission in PERMISSIONS.get(user.get("role", ""), set())


def require_permission(user: Optional[dict], permission: str) -> None:
    if not has_permission(user, permission):
        raise PermissionError(tr("You do not have permission for this action.", "У вас нет прав для этого действия."))


def get_user(username: str) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None


def authenticate(username: str, password: str) -> Optional[dict]:
    user = get_user(username.strip())
    if user and user["is_active"] and verify_password(password, user["password_hash"]):
        return user
    return None
