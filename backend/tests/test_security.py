import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import TEST_LOGIN, TEST_TOKEN, ensure_user
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.security as sec
from app.auth import service
from app.config import settings as default_settings
from app.engines.pool import EngineUnavailableError
from app.main import create_app
from app.security import (
    HEADERS,
    HSTS,
    MAX_BODY_BYTES,
    LoginLimiter,
    UserSlots,
    limiter_ip,
)

BACKEND = Path(__file__).resolve().parents[1]
FEN = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"


@pytest.fixture
def cfg(tmp_path):
    return replace(
        default_settings,
        app_db_path=tmp_path / "app.db",
        frontend_dist=tmp_path / "dist",
        engines_dir=tmp_path / "no-engines",
        cookie_secure=False,
        trust_proxy=False,
    )


@pytest.fixture
def app(cfg):
    return create_app(cfg)


def plain(app) -> TestClient:
    return TestClient(app, auto_login=False)


def login(c, token=TEST_TOKEN, login_name=TEST_LOGIN):
    return c.post("/api/auth/login", json={"login": login_name, "token": token})


def test_import_does_not_touch_the_database(tmp_path):
    db = tmp_path / "import-check.db"
    env = {**os.environ, "APP_DB_PATH": str(db), "APP_DATA_DIR": str(tmp_path)}
    done = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        check=False,
        cwd=BACKEND,
        env=env,
        capture_output=True,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    assert not db.exists()
    assert list(tmp_path.iterdir()) == []


def test_startup_migrates(app, cfg):
    with TestClient(app, auto_login=False):
        assert cfg.app_db_path.exists()


def test_limiter_blocks_and_expires():
    now = [0.0]
    lim = LoginLimiter(max_fails=3, window_s=100, clock=lambda: now[0])
    keys = ["ip:a", "login:x"]
    for _ in range(3):
        lim.guard(keys)
        lim.fail(keys)
    with pytest.raises(HTTPException) as err:
        lim.guard(keys)
    assert err.value.status_code == 429
    assert int(err.value.headers["Retry-After"]) >= 100
    lim.guard(["ip:b", "login:y"])  # other client and other login are free
    now[0] = 101
    lim.guard(keys)


def test_login_rate_limit_and_reset(cfg):
    app = create_app(replace(cfg, trust_proxy=True))
    ensure_user(app)
    c = plain(app)

    def attempt(token, ip="10.0.0.1"):
        return c.post(
            "/api/auth/login",
            json={"login": TEST_LOGIN, "token": token},
            headers={"X-Forwarded-For": ip},
        )

    for _ in range(4):
        assert attempt("wrong-wrong").status_code == 401
    assert attempt(TEST_TOKEN).status_code == 200  # success resets this client's counters
    for _ in range(5):
        assert attempt("wrong-wrong").status_code == 401
    r = attempt(TEST_TOKEN)  # right token, but this client is locked
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    # Another client is not locked out by these failures: no one can lock the owner out.
    assert attempt(TEST_TOKEN, ip="10.0.0.2").status_code == 200


def test_login_limit_is_per_ip_too(app):
    ensure_user(app)
    c = plain(app)
    for i in range(5):
        assert login(c, "wrong-wrong", f"nobody{i}").status_code == 401
    assert login(c, "wrong-wrong", "another").status_code == 429


def test_admin_login_rate_limit(app):
    c = plain(app)
    for _ in range(5):
        assert c.post("/api/admin/login", json={"token": "bad"}).status_code == 401
    r = c.post("/api/admin/login", json={"token": default_settings.admin_token})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_forwarded_for_ignored_unless_trusted(cfg):
    def attempts(app):
        ensure_user(app)
        c = plain(app)
        for i in range(5):
            c.post(
                "/api/auth/login",
                json={"login": f"n{i}", "token": "x"},
                headers={"X-Forwarded-For": f"10.0.0.{i}"},
            )
        return c.post(
            "/api/auth/login",
            json={"login": "last", "token": "x"},
            headers={"X-Forwarded-For": "10.0.0.99"},
        ).status_code

    assert attempts(create_app(cfg)) == 429  # header ignored: one client IP
    trusted = replace(cfg, trust_proxy=True)
    assert attempts(create_app(trusted)) == 401  # every request has its own IP


def test_wrong_login_still_hashes_the_token(app, monkeypatch):
    ensure_user(app)
    calls = []
    real = service.hash_token
    monkeypatch.setattr(service, "hash_token", lambda t: calls.append(t) or real(t))
    c = plain(app)
    assert login(c, "wrong-wrong", "nobody").status_code == 401
    assert login(c, "wrong-wrong", TEST_LOGIN).status_code == 401
    assert len(calls) == 2


def test_security_headers(app, cfg):
    r = plain(app).get("/api/health")
    for name, value in HEADERS.items():
        assert r.headers[name] == value
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "style-src 'self';" in r.headers["content-security-policy"]  # no inline <style>
    assert "strict-transport-security" not in r.headers
    secure = TestClient(create_app(replace(cfg, cookie_secure=True)), auto_login=False)
    assert secure.get("/api/health").headers["strict-transport-security"] == HSTS


def test_headers_on_errors(app):
    r = plain(app).get("/api/games")
    assert r.status_code == 401
    assert r.headers["x-frame-options"] == "DENY"


def test_docs_are_disabled(app):
    c = plain(app)
    for path in ("/docs", "/redoc", "/openapi.json"):
        r = c.get(path)
        assert "swagger" not in r.text.lower()
        assert "openapi" not in r.text.lower()


def test_health_without_session_has_no_details(app):
    r = plain(app).get("/api/health")
    assert set(r.json()) == {"status", "version"}


def test_health_with_session_has_no_paths_or_model(app):
    body = TestClient(app).get("/api/health").json()
    assert set(body) == {"status", "version", "engines", "llm"}
    assert body["engines"] == {"stockfish": {"available": False}}
    assert set(body["llm"]) == {"enabled", "available"}


def test_origin_check(app):
    c = TestClient(app)
    url = "/api/auth/logout"
    assert c.post(url, headers={"Origin": "http://evil.example"}).status_code == 403
    assert c.post(url, headers={"Origin": "null"}).status_code == 403
    assert (
        c.post(url, headers={"Origin": "https://testserver"}).status_code == 403
    )  # scheme differs
    assert c.post(url, headers={"Origin": "http://testserver"}).status_code == 204
    assert c.post(url).status_code == 204  # no Origin: curl, tests
    # Reading is not checked.
    assert c.get("/api/auth/me", headers={"Origin": "http://evil.example"}).status_code == 401


def test_origin_check_with_proxy_scheme(cfg):
    c = TestClient(create_app(replace(cfg, trust_proxy=True)), auto_login=False)
    r = c.post(
        "/api/auth/logout",
        headers={"Origin": "https://testserver", "X-Forwarded-Proto": "https"},
    )
    assert r.status_code == 204


def test_user_slots_limit():
    slots = UserSlots(limit=2)
    assert slots.acquire(1) and slots.acquire(1)
    assert not slots.acquire(1)
    assert slots.acquire(2)  # another user is not blocked
    slots.release(1)
    assert slots.acquire(1)


class SlowPool:
    """analyse() waits for `gate`, then fails, so the test needs no engine."""

    def __init__(self):
        self.gate = threading.Event()
        self.started = threading.Semaphore(0)

    def analyse(self, *_args):
        self.started.release()
        self.gate.wait(10)
        raise EngineUnavailableError("fake")


def test_third_engine_request_of_a_user_gets_429(cfg):
    app = create_app(replace(cfg, engine_requests_per_user=2))
    app.state.engine_slots.wait_s = 0.2  # the real wait is 10 s
    ensure_user(app)
    app.state.pool = SlowPool()
    results: list[int] = []
    clients = [TestClient(app) for _ in range(3)]  # log in here: the setup is not thread safe

    def call(client):
        results.append(client.post("/api/analyze", json={"fen": FEN}).status_code)

    threads = [threading.Thread(target=call, args=(c,)) for c in clients[:2]]
    for t in threads:
        t.start()
    for _ in range(2):
        assert app.state.pool.started.acquire(timeout=10)
    third = clients[2].post("/api/analyze", json={"fen": FEN})
    assert third.status_code == 429
    assert "тренер" in third.json()["detail"]
    app.state.pool.gate.set()
    for t in threads:
        t.join(10)
    assert results == [503, 503]
    # Slots are free again.
    assert TestClient(app).post("/api/analyze", json={"fen": FEN}).status_code == 503


def test_slot_wait_gets_the_slot_when_one_is_freed():
    slots = UserSlots(limit=1, wait_s=5)
    assert slots.acquire(1)
    got = []
    t = threading.Thread(target=lambda: got.append(slots.acquire(1)))
    t.start()
    threading.Timer(0.2, slots.release, args=(1,)).start()
    t.join(5)
    assert got == [True]


def test_slot_wait_times_out():
    slots = UserSlots(limit=1, wait_s=0.3)
    assert slots.acquire(1)
    assert not slots.acquire(1)  # waited 0.3 s, no slot freed
    assert slots.acquire(2)  # another user is not blocked


def test_extra_waiters_fail_at_once():
    slots = UserSlots(limit=1, wait_s=5)
    assert slots.acquire(1)
    waiter = threading.Thread(target=slots.acquire, args=(1,))
    waiter.start()
    for _ in range(100):
        if slots._waiting.get(1):
            break
        time.sleep(0.05)
    start = time.monotonic()
    assert not slots.acquire(1)  # one waiter already: this one does not wait
    assert time.monotonic() - start < 1
    slots.release(1)
    waiter.join(5)


def test_four_parallel_heavy_requests_of_a_user_all_succeed(cfg):
    app = create_app(replace(cfg, engine_requests_per_user=3))
    ensure_user(app)
    pool = app.state.pool = SlowPool()
    clients = [TestClient(app) for _ in range(4)]
    results: list[int] = []
    threads = [
        threading.Thread(
            target=lambda c=c: results.append(c.post("/api/analyze", json={"fen": FEN}).status_code)
        )
        for c in clients
    ]
    for t in threads:
        t.start()
    for _ in range(3):
        assert pool.started.acquire(timeout=10)
    pool.gate.set()  # the 4th request gets its slot as soon as the first ones end
    for t in threads:
        t.join(15)
    assert results == [503, 503, 503, 503]  # SlowPool fails on purpose; none is 429


def test_default_engine_limit_is_three():
    assert default_settings.engine_requests_per_user == 3


def test_body_over_limit_is_413_with_content_length(app):
    c = TestClient(app, auto_login=False)
    big = b"x" * (MAX_BODY_BYTES + 1)
    r = c.post("/api/auth/login", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    assert r.headers["x-frame-options"] == "DENY"


def test_chunked_body_over_limit_is_413(app):
    c = TestClient(app, auto_login=False)

    def chunks():
        for _ in range(MAX_BODY_BYTES // 65536 + 2):
            yield b"x" * 65536

    r = c.post("/api/auth/login", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_chunked_body_over_limit_is_413_when_logged_in(app):
    c = TestClient(app)

    def chunks():
        for _ in range(MAX_BODY_BYTES // 65536 + 2):
            yield b"x" * 65536

    r = c.post("/api/games", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_normal_body_passes(app):
    ensure_user(app)
    c = TestClient(app, auto_login=False)
    assert login(c).status_code == 200
    big_ok = {"login": "x" * 64, "token": "y" * 64}
    assert c.post("/api/auth/login", json=big_ok).status_code == 401


def test_limiter_prune_runs_once_a_minute(monkeypatch):
    monkeypatch.setattr(sec, "_MAX_KEYS", 5)
    now = [0.0]
    lim = LoginLimiter(max_fails=3, window_s=100, clock=lambda: now[0])
    for i in range(10):
        lim.fail([f"k{i}"])
    assert len(lim._fails) == 10  # all recent: the scan at t=0 removed nothing
    now[0] = 150
    lim.fail(["new1"])  # the scan is allowed again: all k* are older than the window
    assert set(lim._fails) == {"new1"}
    scans = []
    real = lim._recent
    lim._recent = lambda key, t: scans.append(key) or real(key, t)
    for i in range(10):
        lim.fail([f"b{i}"])  # over the key limit, but the last scan was under 60 s ago
    assert scans == []
    now[0] = 150 + 61
    lim.fail(["after"])
    assert len(scans) == 11  # one full scan after a minute
    assert "after" in lim._fails


def test_ipv6_clients_share_a_64_prefix():
    assert limiter_ip("2001:db8:1:2:aaaa:bbbb:cccc:dddd") == limiter_ip("2001:db8:1:2::1")
    assert limiter_ip("2001:db8:1:3::1") != limiter_ip("2001:db8:1:2::1")
    assert limiter_ip("10.1.2.3") == "10.1.2.3"
    assert limiter_ip("unknown") == "unknown"


def test_short_admin_token_is_503(cfg):
    app = create_app(replace(cfg, admin_token="short-token-19-char"))  # 19 characters
    r = plain(app).post("/api/admin/login", json={"token": "short-token-19-char"})
    assert r.status_code == 503
    assert "слишком короткий" in r.json()["detail"]
    ok = create_app(replace(cfg, admin_token="x" * 20))
    assert plain(ok).post("/api/admin/login", json={"token": "x" * 20}).status_code == 200


def _session_count(app) -> int:
    from app.db import connect

    db = connect(app.state.settings.app_db_path)
    try:
        return db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    finally:
        db.close()


def test_login_replaces_the_old_session_of_the_browser(app):
    ensure_user(app)
    c = plain(app)
    assert login(c).status_code == 200
    assert _session_count(app) == 1
    assert login(c).status_code == 200
    assert _session_count(app) == 1  # the old one is deleted, not kept for 30 days
    assert c.get("/api/auth/me").status_code == 200


def test_admin_login_replaces_the_old_admin_session(app):
    c = plain(app)
    for _ in range(2):
        assert (
            c.post("/api/admin/login", json={"token": default_settings.admin_token}).status_code
            == 200
        )
    assert _session_count(app) == 1
