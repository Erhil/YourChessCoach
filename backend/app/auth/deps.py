from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.auth import service
from app.db import Db

USER_COOKIE = "session"
ADMIN_COOKIE = "admin_session"
NEED_LOGIN = "Нужен вход"


def current_user_id(request: Request, db: Db) -> int:
    user_id = service.resolve_session(db, request.cookies.get(USER_COOKIE), admin=False)
    if user_id is None:
        raise HTTPException(401, NEED_LOGIN)
    row = db.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(401, NEED_LOGIN)
    return user_id


def require_admin(request: Request, db: Db) -> None:
    if service.resolve_session(db, request.cookies.get(ADMIN_COOKIE), admin=True) is None:
        raise HTTPException(401, NEED_LOGIN)


UserId = Annotated[int, Depends(current_user_id)]
