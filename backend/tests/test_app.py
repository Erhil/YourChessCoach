from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "index.html").write_text("<html>INDEX</html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return tmp_path


@pytest.fixture
def client(dist, tmp_path):
    cfg = replace(settings, frontend_dist=dist, engines_dir=tmp_path / "no-engines")
    return TestClient(create_app(cfg))


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == settings.app_version
    assert body["engines"]["stockfish"] == {"available": False}


def test_spa_fallback(client):
    r = client.get("/play")
    assert r.status_code == 200
    assert r.text == "<html>INDEX</html>"


def test_well_known_is_json_404_not_the_app_page(client):
    # MCP clients probe /.well-known/oauth-* ; the app page there would look like metadata.
    for path in (
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-authorization-server",
    ):
        r = client.get(path)
        assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_static_asset(client):
    r = client.get("/assets/app.js")
    assert r.status_code == 200
    assert r.text == "console.log(1)"


def test_unknown_api_is_json_404(client):
    r = client.get("/api/unknown")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


def test_missing_dist(tmp_path):
    cfg = replace(settings, frontend_dist=tmp_path / "nope")
    r = TestClient(create_app(cfg)).get("/play")
    assert r.status_code == 404
    assert "Фронтенд не собран" in r.text
