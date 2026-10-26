"""Users and sessions in SQLite. The only place that reads or writes the sessions table."""

import hmac
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

from app.auth.tokens import hash_secret, hash_token, new_session_id

USER_SESSION_TTL = timedelta(days=30)
ADMIN_SESSION_TTL = timedelta(hours=12)
LAST_SEEN_EVERY = timedelta(minutes=1)
# Tables whose rows belong to one user.
OWNED_TABLES = ("games", "puzzle_attempts", "user_ratings", "lesson_progress", "mistakes")
_DUMMY_HASH = hash_secret("no such user")


class LoginTakenError(Exception):
    pass


def _fmt(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def now() -> datetime:
    return datetime.now(UTC)


def create_user(db: sqlite3.Connection, login: str, token: str) -> int:
    """Insert a user. The first user also takes every row that has no owner yet, in one transaction."""
    db.execute("BEGIN IMMEDIATE")
    try:
        first = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        try:
            cur = db.execute(
                "INSERT INTO users (login, token_hash, created_at) VALUES (?, ?, ?)",
                (login, hash_token(token), _fmt(now())),
            )
        except sqlite3.IntegrityError as exc:
            raise LoginTakenError(login) from exc
        user_id = cur.lastrowid
        if first:
            for table in OWNED_TABLES:
                db.execute(f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL", (user_id,))
        db.commit()
        return user_id
    except BaseException:
        db.rollback()
        raise


def reset_token(db: sqlite3.Connection, user_id: int, token: str) -> None:
    with db:
        db.execute("UPDATE users SET token_hash = ? WHERE id = ?", (hash_token(token), user_id))
        db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def check_login(db: sqlite3.Connection, login: str, token: str) -> int | None:
    row = db.execute(
        "SELECT id, token_hash FROM users WHERE login = ?", (login.strip().lower(),)
    ).fetchone()
    expected = row["token_hash"] if row else _DUMMY_HASH
    ok = hmac.compare_digest(hash_token(token), expected)
    return row["id"] if row and ok else None


def create_session(db: sqlite3.Connection, user_id: int | None, admin: bool) -> tuple[str, int]:
    """Store a new session; return (cookie value, lifetime in seconds)."""
    ttl = ADMIN_SESSION_TTL if admin else USER_SESSION_TTL
    sid = new_session_id()
    moment = now()
    with db:
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (_fmt(moment),))
        db.execute(
            "INSERT INTO sessions (id_hash, user_id, admin, created_at, expires_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (hash_secret(sid), user_id, int(admin), _fmt(moment), _fmt(moment + ttl)),
        )
    return sid, int(ttl.total_seconds())


def delete_session(db: sqlite3.Connection, sid: str | None) -> None:
    if sid:
        with db:
            db.execute("DELETE FROM sessions WHERE id_hash = ?", (hash_secret(sid),))


def resolve_session(db: sqlite3.Connection, sid: str | None, admin: bool) -> int | None:
    """The one place where a cookie becomes an identity.

    Return the user id (user session) or 0 (admin session); None when there is no valid session.
    """
    if not sid:
        return None
    row = db.execute(
        "SELECT user_id, admin, expires_at FROM sessions WHERE id_hash = ?", (hash_secret(sid),)
    ).fetchone()
    if row is None or bool(row["admin"]) != admin:
        return None
    moment = now()
    if row["expires_at"] <= _fmt(moment):
        delete_session(db, sid)
        return None
    if admin:
        return 0
    with db:
        db.execute(
            "UPDATE users SET last_seen_at = ? WHERE id = ?"
            " AND (last_seen_at IS NULL OR last_seen_at <= ?)",
            (_fmt(moment), row["user_id"], _fmt(moment - LAST_SEEN_EVERY)),
        )
    return row["user_id"]


def new_mcp_key() -> str:
    return secrets.token_urlsafe(32)


def set_mcp_key(db: sqlite3.Connection, user_id: int, key: str) -> None:
    with db:
        db.execute(
            "UPDATE users SET mcp_key_hash = ?, mcp_key_created_at = ? WHERE id = ?",
            (hash_secret(key), _fmt(now()), user_id),
        )


def delete_mcp_key(db: sqlite3.Connection, user_id: int) -> None:
    with db:
        db.execute(
            "UPDATE users SET mcp_key_hash = NULL, mcp_key_created_at = NULL WHERE id = ?",
            (user_id,),
        )


def mcp_key_info(db: sqlite3.Connection, user_id: int) -> dict:
    row = db.execute(
        "SELECT mcp_key_created_at FROM users WHERE id = ? AND mcp_key_hash IS NOT NULL",
        (user_id,),
    ).fetchone()
    return {"exists": row is not None, "created_at": row[0] if row else None}


def resolve_mcp_key(db: sqlite3.Connection, key: str) -> int | None:
    """The user id that owns this MCP key, or None. The hash is looked up, then compared again."""
    digest = hash_secret(key)
    row = db.execute(
        "SELECT id, mcp_key_hash FROM users WHERE mcp_key_hash = ?", (digest,)
    ).fetchone()
    if row is None or not hmac.compare_digest(digest, row["mcp_key_hash"]):
        return None
    return row["id"]
