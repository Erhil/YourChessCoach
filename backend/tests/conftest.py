import os
import tempfile

import pytest

# Tests must never touch the real user database (data/app.db is used by the stable server).
# Set this before the app modules read the settings.
_tmp = tempfile.mkdtemp(prefix="chess-coach-tests-")
os.environ["APP_DATA_DIR"] = _tmp
os.environ["LLM_ENABLED"] = "false"  # tests never call a real Ollama
os.environ["APP_DB_PATH"] = os.path.join(_tmp, "app.db")
os.environ["ADMIN_TOKEN"] = "test-admin-token-0123456789"

from fastapi.testclient import TestClient

from app.auth import service
from app.config import settings
from app.db import connect
from app.engines.locate import find_binary

TEST_LOGIN = "tester"
TEST_TOKEN = "abcd-efgh-jkmn-pqrs"

_plain_init = TestClient.__init__


def ensure_user(app, login: str = TEST_LOGIN, token: str = TEST_TOKEN) -> None:
    db = connect(app.state.settings.app_db_path)
    try:
        if db.execute("SELECT 1 FROM users WHERE login = ?", (login,)).fetchone() is None:
            service.create_user(db, login, token)
    finally:
        db.close()


def _init_logged_in(self, app, *args, auto_login: bool = True, **kwargs):
    """Every TestClient of the app logs in through the real login route, unless auto_login=False."""
    _plain_init(self, app, *args, **kwargs)
    if auto_login and hasattr(app, "state") and hasattr(app.state, "settings"):
        ensure_user(app)
        r = self.post("/api/auth/login", json={"login": TEST_LOGIN, "token": TEST_TOKEN})
        assert r.status_code == 200, r.text


TestClient.__init__ = _init_logged_in


def pytest_collection_modifyitems(config, items):
    if find_binary(settings.engines_dir, "stockfish") is not None:
        return
    skip = pytest.mark.skip(reason="Stockfish not found")
    for item in items:
        if "engine" in item.keywords:
            item.add_marker(skip)
