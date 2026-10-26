"""Protection for an open port: login rate limit, security headers, Origin check, engine slots."""

import ipaddress
import json
import threading
import time
from collections.abc import Callable, Iterator
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.auth.deps import UserId
from app.config import Settings

LOGIN_MAX_FAILS = 5
LOGIN_WINDOW_S = 15 * 60
# After a move the UI sends up to 4 at once (verdict, opponent, eval bar, level-5 hint).
ENGINE_REQUESTS_PER_USER = 3
SLOT_WAIT_S = 10.0  # a request over the limit waits this long for a free slot, then gets 429
MAX_BODY_BYTES = 1024 * 1024
TOO_BIG = "Слишком большой запрос"
TOO_MANY_LOGINS = "Слишком много неверных попыток. Попробуйте позже"
COACH_BUSY = "Подождите, тренер ещё думает"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_MAX_KEYS = 10_000
_PRUNE_EVERY_S = 60.0

# Only style ATTRIBUTES may be inline (react-chessboard sets them); <style> elements stay blocked.
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; style-src-attr 'unsafe-inline'; "
    "script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}
HSTS = "max-age=31536000"


def client_ip(request: Request) -> str:
    """The peer address. X-Forwarded-For counts only with TRUST_PROXY; the last value comes from our proxy."""
    if request.app.state.settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"


class LoginLimiter:
    """Failed logins in a sliding window, by key (client IP, login). In memory, one process."""

    def __init__(
        self,
        max_fails: int = LOGIN_MAX_FAILS,
        window_s: float = LOGIN_WINDOW_S,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_fails, self.window_s, self.clock = max_fails, window_s, clock
        self._fails: dict[str, list[float]] = {}
        self._next_prune = 0.0
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> list[float]:
        recent = [t for t in self._fails.get(key, []) if now - t < self.window_s]
        if recent:
            self._fails[key] = recent
        else:
            self._fails.pop(key, None)
        return recent

    def guard(self, keys: list[str]) -> None:
        """Raise 429 with Retry-After when any key has too many failures."""
        now = self.clock()
        with self._lock:
            wait = 0.0
            for key in keys:
                recent = self._recent(key, now)
                if len(recent) >= self.max_fails:
                    wait = max(wait, recent[0] + self.window_s - now)
        if wait > 0:
            raise HTTPException(429, TOO_MANY_LOGINS, headers={"Retry-After": str(int(wait) + 1)})

    def fail(self, keys: list[str]) -> None:
        now = self.clock()
        with self._lock:
            if len(self._fails) > _MAX_KEYS and now >= self._next_prune:
                self._next_prune = now + _PRUNE_EVERY_S  # one full scan a minute at most
                for key in list(self._fails):
                    self._recent(key, now)
            for key in keys:
                self._fails.setdefault(key, []).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


def login_keys(request: Request, name: str) -> list[str]:
    """Keys of one login attempt: [client IP, client IP + login].

    Not the login alone: then anyone who knows a login could lock its owner out.
    """
    ip = limiter_ip(client_ip(request))
    return [f"ip:{ip}", f"login:{ip}:{name}"]


def limiter_ip(ip: str) -> str:
    """An IPv6 client gets a whole /64 network for itself, so it cannot dodge the limit by changing the address."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6:
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return ip


class UserSlots:
    """At most `limit` running heavy requests for each user.

    A request over the limit waits up to `wait_s` for a free slot. At most `limit` requests
    of one user wait at the same time; the next ones fail at once.
    """

    def __init__(self, limit: int = ENGINE_REQUESTS_PER_USER, wait_s: float = SLOT_WAIT_S):
        self.limit, self.wait_s = limit, wait_s
        self._busy: dict[int, int] = {}
        self._waiting: dict[int, int] = {}
        self._cond = threading.Condition()

    def acquire(self, user_id: int) -> bool:
        with self._cond:
            if self._busy.get(user_id, 0) >= self.limit:
                if self._waiting.get(user_id, 0) >= self.limit:
                    return False
                self._waiting[user_id] = self._waiting.get(user_id, 0) + 1
                try:
                    free = self._cond.wait_for(
                        lambda: self._busy.get(user_id, 0) < self.limit, timeout=self.wait_s
                    )
                finally:
                    left = self._waiting[user_id] - 1
                    if left:
                        self._waiting[user_id] = left
                    else:
                        del self._waiting[user_id]
                if not free:
                    return False
            self._busy[user_id] = self._busy.get(user_id, 0) + 1
            return True

    def release(self, user_id: int) -> None:
        with self._cond:
            left = self._busy.get(user_id, 1) - 1
            if left > 0:
                self._busy[user_id] = left
            else:
                self._busy.pop(user_id, None)
            self._cond.notify_all()


def engine_slot(request: Request, user_id: UserId) -> Iterator[None]:
    """Dependency of the routes that use Stockfish, the opponent or the LLM."""
    slots: UserSlots = request.app.state.engine_slots
    if not slots.acquire(user_id):
        raise HTTPException(429, COACH_BUSY)
    try:
        yield
    finally:
        slots.release(user_id)


ENGINE_HEAVY = [Depends(engine_slot)]


def _origin_ok(request: Request, trust_proxy: bool) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        return True
    scheme = request.url.scheme
    if trust_proxy and request.headers.get("x-forwarded-proto"):
        scheme = request.headers["x-forwarded-proto"].split(",")[-1].strip()
    parts = urlsplit(origin)
    return parts.scheme == scheme and parts.netloc == request.headers.get("host")


class BodyLimit:
    """ASGI middleware: a request body over `limit` bytes gets 413 before routing and parsing.

    Content-Length is checked first. A chunked body (no Content-Length) is counted while it streams.
    """

    def __init__(self, app, limit: int = MAX_BODY_BYTES, secure: bool = False):
        self.app, self.limit, self.secure = app, limit, secure

    async def _reject(self, send) -> None:
        headers = {**HEADERS, "Connection": "close"}
        if self.secure:
            headers["Strict-Transport-Security"] = HSTS
        body = json.dumps({"detail": TOO_BIG}, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(k.lower().encode(), v.encode("utf-8")) for k, v in headers.items()],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.limit:
            await self._reject(send)
            return
        total = 0
        over = False
        started = False

        async def counted():
            # Raising here would reach FastAPI as "400 error parsing the body": stop the body instead.
            nonlocal total, over
            if over:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.limit:
                    over = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            nonlocal started
            if over and not started:
                return  # the app failed on the cut body: its answer is dropped, 413 follows
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted, guarded_send)
        except Exception:
            if not over:
                raise
        if over and not started:
            await self._reject(send)


def install(app: FastAPI, settings: Settings) -> None:
    app.state.login_limiter = LoginLimiter()
    app.state.engine_slots = UserSlots(settings.engine_requests_per_user)

    @app.middleware("http")
    async def protect(request: Request, call_next):
        path = request.url.path
        checked = path.rstrip("/") == "/mcp" or (
            request.method in UNSAFE_METHODS and path.startswith("/api/")
        )
        if checked and not _origin_ok(request, settings.trust_proxy):
            response = JSONResponse({"detail": "Запрос с чужого адреса"}, status_code=403)
        else:
            response = await call_next(request)
        response.headers.update(HEADERS)
        if settings.cookie_secure:
            response.headers["Strict-Transport-Security"] = HSTS
        return response

    app.add_middleware(BodyLimit, secure=settings.cookie_secure)  # added last: runs first
