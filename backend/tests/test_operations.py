import asyncio
import sqlite3
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import verified_copy
from app.llm.client import OllamaClient
from app.main import create_app


def test_selected_model_missing_and_public_health(tmp_path):
    app = create_app(replace(settings, app_db_path=tmp_path / "app.db", llm_enabled=True))
    app.state.llm = OllamaClient(
        "http://localhost",
        1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"models": [{"name": "other:4b"}]})
        ),
    )
    with TestClient(app) as client:
        with sqlite3.connect(app.state.settings.app_db_path) as db:
            db.execute("INSERT INTO app_settings(key,value) VALUES ('llm_model','missing:4b')")
        health = client.get("/api/health").json()
        assert health["llm"]["model"] == "missing:4b"
        assert health["llm"]["reachable"] is True
        assert health["llm"]["available"] is False
        assert health["llm"]["status"] == "model_missing"
        with sqlite3.connect(app.state.settings.app_db_path) as db:
            db.execute("UPDATE app_settings SET value='template' WHERE key='llm_model'")
        assert client.get("/api/health").json()["llm"]["status"] == "template"
        client.cookies.clear()
        assert set(client.get("/api/health").json()) == {"status", "version"}


def test_periodic_snapshot_restores_changed_rows_and_stops(tmp_path):
    app = create_app(
        replace(
            settings,
            app_db_path=tmp_path / "app.db",
            backup_dir=tmp_path / "backups",
            backup_interval_s=0.03,
        )
    )

    async def run():
        async with app.router.lifespan_context(app):
            with sqlite3.connect(app.state.settings.app_db_path) as db:
                db.execute("INSERT INTO app_settings(key,value) VALUES ('snapshot_test','first')")
            await asyncio.sleep(0.12)
            with sqlite3.connect(app.state.settings.app_db_path) as db:
                db.execute("UPDATE app_settings SET value='changed' WHERE key='snapshot_test'")
            for _ in range(50):
                await asyncio.sleep(0.03)
                snapshots = sorted((tmp_path / "backups").glob("*.db"))
                if snapshots:
                    with sqlite3.connect(snapshots[-1]) as db:
                        row = db.execute(
                            "SELECT value FROM app_settings WHERE key='snapshot_test'"
                        ).fetchone()
                    if row == ("changed",):
                        break
            else:
                pytest.fail("periodic snapshot never captured committed change")
        latest = sorted((tmp_path / "backups").glob("*.db"))
        restored = verified_copy(latest[-1], tmp_path / "restored.db")
        with sqlite3.connect(restored) as db:
            assert db.execute(
                "SELECT value FROM app_settings WHERE key='snapshot_test'"
            ).fetchone() == ("changed",)
        await asyncio.sleep(0.1)
        assert sorted((tmp_path / "backups").glob("*.db")) == latest

    asyncio.run(run())


def test_restore_rejects_corrupt_input_and_existing_target(tmp_path):
    corrupt = tmp_path / "bad.db"
    corrupt.write_text("not a sqlite database", encoding="utf-8")
    target = tmp_path / "restored.db"
    with pytest.raises(sqlite3.DatabaseError):
        verified_copy(corrupt, target)
    assert not target.exists()
    target.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        verified_copy(corrupt, target)
    assert target.read_text(encoding="utf-8") == "keep"
