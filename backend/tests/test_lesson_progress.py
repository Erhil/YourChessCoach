from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.config import settings as default_settings
from app.main import create_app

LESSON = """---
title: Test
level: 1
themes: []
prerequisites: []
---
Text

```chess
fen: 4k3/8/8/8/8/8/8/4K2R w - - 0 1
task: t
solution: Rh8+
hint: h
```

```chess
fen: 4k3/8/8/8/8/8/8/4K2R w - - 0 1
task: t
solution: Rh8+
hint: h
```
"""


@pytest.fixture
def client(tmp_path):
    lessons = tmp_path / "lessons"
    lessons.mkdir()
    (lessons / "01-test.md").write_text(LESSON, encoding="utf-8")
    settings = replace(
        default_settings,
        app_db_path=tmp_path / "app.db",
        frontend_dist=tmp_path / "dist",
        lessons_dir=lessons,
    )
    return TestClient(create_app(settings))


def entry(client):
    return next(x for x in client.get("/api/lessons").json() if x["slug"] == "test")


def test_mark_and_complete(client):
    assert entry(client)["solved"] == 0
    r = client.post("/api/lessons/test/positions/1")
    assert r.json() == {"solved": [1], "positions": 2, "completed": False}
    assert entry(client)["solved"] == 1
    assert not entry(client)["completed"]
    assert client.post("/api/lessons/test/positions/0").json()["completed"] is True
    assert entry(client)["completed"]
    assert client.get("/api/lessons/test").json()["solved"] == [0, 1]


def test_idempotent(client):
    client.post("/api/lessons/test/positions/0")
    r = client.post("/api/lessons/test/positions/0")
    assert r.json()["solved"] == [0]


def test_not_found(client):
    assert client.post("/api/lessons/nope/positions/0").status_code == 404
    assert client.post("/api/lessons/test/positions/2").status_code == 404
    assert client.post("/api/lessons/test/positions/-1").status_code == 404
