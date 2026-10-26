import hmac
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth import service
from app.auth.deps import ADMIN_COOKIE, USER_COOKIE, UserId, require_admin
from app.auth.tokens import new_token
from app.db import Db
from app.progress.routes import build_progress
from app.security import login_keys

router = APIRouter(prefix="/api/auth")
admin_router = APIRouter(prefix="/api/admin")
key_router = APIRouter(prefix="/api/mcp-key")

BAD_LOGIN = "Неверный логин или токен"
BAD_ADMIN = "Неверный токен"
LOGIN_RE = re.compile(r"[a-z0-9_.-]{2,32}")
ADMIN_PATH = "/api/admin"
MIN_ADMIN_TOKEN = 20


def _set_cookie(request: Request, response: Response, name: str, sid: str, age: int, path: str):
    response.set_cookie(
        name,
        sid,
        max_age=age,
        path=path,
        httponly=True,
        samesite="strict",
        secure=request.app.state.settings.cookie_secure,
    )


class LoginIn(BaseModel):
    login: str = Field(max_length=64)
    token: str = Field(max_length=64)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Db) -> dict:
    limiter = request.app.state.login_limiter
    keys = login_keys(request, body.login.strip().lower())
    limiter.guard(keys)
    user_id = service.check_login(db, body.login, body.token)
    if user_id is None:
        limiter.fail(keys)
        raise HTTPException(401, BAD_LOGIN)
    for key in keys:  # a success clears this client's count
        limiter.reset(key)
    service.delete_session(
        db, request.cookies.get(USER_COOKIE)
    )  # not a second session for one browser
    sid, age = service.create_session(db, user_id, admin=False)
    _set_cookie(request, response, USER_COOKIE, sid, age, "/")
    return {"login": body.login.strip().lower()}


@router.post("/logout", status_code=204)
def logout(request: Request, db: Db) -> Response:
    service.delete_session(db, request.cookies.get(USER_COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(USER_COOKIE, path="/")
    return response


@router.get("/me")
def me(user_id: UserId, db: Db) -> dict:
    return {"login": db.execute("SELECT login FROM users WHERE id = ?", (user_id,)).fetchone()[0]}


class AdminLoginIn(BaseModel):
    token: str = Field(max_length=256)


@key_router.get("")
def mcp_key_state(user_id: UserId, db: Db) -> dict:
    return service.mcp_key_info(db, user_id)


@key_router.post("")
def mcp_key_create(user_id: UserId, db: Db) -> dict:
    """Create or replace the key. The key is shown here once; only its hash is stored."""
    key = service.new_mcp_key()
    service.set_mcp_key(db, user_id, key)
    return {"key": key}


@key_router.delete("", status_code=204)
def mcp_key_delete(user_id: UserId, db: Db) -> Response:
    service.delete_mcp_key(db, user_id)
    return Response(status_code=204)


@admin_router.post("/login")
def admin_login(body: AdminLoginIn, request: Request, response: Response, db: Db) -> dict:
    expected = request.app.state.settings.admin_token
    if not expected:
        raise HTTPException(503, "ADMIN_TOKEN не задан в .env")
    if len(expected) < MIN_ADMIN_TOKEN:
        raise HTTPException(
            503, f"ADMIN_TOKEN слишком короткий (нужно не меньше {MIN_ADMIN_TOKEN} символов)"
        )
    limiter = request.app.state.login_limiter
    keys = login_keys(request, "admin")
    limiter.guard(keys)
    if not hmac.compare_digest(body.token.encode("utf-8"), expected.encode("utf-8")):
        limiter.fail(keys)
        raise HTTPException(401, BAD_ADMIN)
    for key in keys:  # a success clears this client's count
        limiter.reset(key)
    service.delete_session(db, request.cookies.get(ADMIN_COOKIE))
    sid, age = service.create_session(db, None, admin=True)
    _set_cookie(request, response, ADMIN_COOKIE, sid, age, ADMIN_PATH)
    return {"admin": True}


@admin_router.post("/logout", status_code=204)
def admin_logout(request: Request, db: Db) -> Response:
    service.delete_session(db, request.cookies.get(ADMIN_COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(ADMIN_COOKIE, path=ADMIN_PATH)
    return response


class NewUser(BaseModel):
    login: str = Field(max_length=64)


def _lessons_dir(request: Request):
    return request.app.state.settings.lessons_dir


@admin_router.get("/users", dependencies=[Depends(require_admin)])
def list_users(request: Request, db: Db) -> list[dict]:
    out = []
    for u in db.execute(
        "SELECT id, login, created_at, last_seen_at, mcp_key_hash IS NOT NULL AS mcp_key FROM users ORDER BY id"
    ):
        p = build_progress(db, _lessons_dir(request), u["id"])
        out.append(
            {
                "id": u["id"],
                "login": u["login"],
                "created_at": u["created_at"],
                "last_seen_at": u["last_seen_at"],
                "mcp_key": bool(u["mcp_key"]),
                "games": p["games"]["count"],
                "puzzle_rating": p["puzzles"]["rating"],
                "puzzles_solved": p["puzzles"]["solved"],
                "mistakes_due": p["mistakes"]["due"],
                "mistakes_learned": p["mistakes"]["learned"],
                "lessons_done": p["lessons"]["completed"],
            }
        )
    return out


@admin_router.post("/users", status_code=201, dependencies=[Depends(require_admin)])
def create_user(body: NewUser, db: Db) -> dict:
    login = body.login.strip().lower()
    if not LOGIN_RE.fullmatch(login):
        raise HTTPException(422, "Логин: 2–32 символа, латиница, цифры и _ . -")
    token = new_token()
    try:
        user_id = service.create_user(db, login, token)
    except service.LoginTakenError:
        raise HTTPException(409, "Такой логин уже есть") from None
    return {"id": user_id, "login": login, "token": token}


def _user(db: Db, user_id: int) -> None:
    if db.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
        raise HTTPException(404, "Пользователь не найден")


@admin_router.post("/users/{user_id}/token", dependencies=[Depends(require_admin)])
def reset_user_token(user_id: int, db: Db) -> dict:
    _user(db, user_id)
    token = new_token()
    service.reset_token(db, user_id, token)
    return {"token": token}


@admin_router.get("/users/{user_id}/progress", dependencies=[Depends(require_admin)])
def user_progress(user_id: int, request: Request, db: Db) -> dict:
    _user(db, user_id)
    return build_progress(db, _lessons_dir(request), user_id)


@admin_router.delete(
    "/users/{user_id}/mcp-key", status_code=204, dependencies=[Depends(require_admin)]
)
def revoke_user_mcp_key(user_id: int, db: Db) -> Response:
    _user(db, user_id)
    service.delete_mcp_key(db, user_id)
    return Response(status_code=204)
