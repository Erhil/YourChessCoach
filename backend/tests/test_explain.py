import dataclasses
import logging

import pytest

from app.coach.explain import explain_facts
from app.config import settings as base_settings
from app.db import connect, migrate
from tests.fakes import FakeLLM
from tests.test_validator import GOOD, facts

ON = dataclasses.replace(base_settings, llm_enabled=True)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "t.db"
    migrate(path)
    conn = connect(path)
    yield conn
    conn.close()


def test_valid_text_is_llm_and_cached(db):
    llm = FakeLLM(GOOD)
    first = explain_facts(facts(), db, llm, ON)
    second = explain_facts(facts(), db, llm, ON)
    assert first["source"] == second["source"] == "llm"
    assert first["model"] == ON.llm_model
    assert second["text"] == first["text"]
    assert len(llm.calls) == 1


def test_invalid_text_gives_template_and_log(db, caplog):
    llm = FakeLLM("Лучше было Bc4.")
    with caplog.at_level(logging.INFO, logger="app.coach.explain"):
        out = explain_facts(facts(), db, llm, ON)
    assert out["source"] == "template" and out["model"] is None and out["text"]
    assert any("rejected" in r.message for r in caplog.records)
    assert db.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 0


def test_llm_error_gives_template(db):
    assert explain_facts(facts(), db, FakeLLM(None), ON)["source"] == "template"


def test_disabled_gives_template(db):
    llm = FakeLLM(GOOD)
    off = dataclasses.replace(ON, llm_enabled=False)
    assert explain_facts(facts(), db, llm, off)["source"] == "template"
    assert llm.calls == []


def test_app_setting_overrides_model(db):
    db.execute("INSERT INTO app_settings (key, value) VALUES ('llm_model', 'other:1b')")
    db.commit()
    llm = FakeLLM(GOOD)
    out = explain_facts(facts(), db, llm, ON)
    assert out["model"] == "other:1b" and llm.calls[0][2] == "other:1b"


def test_template_model_skips_llm(db):
    db.execute("INSERT INTO app_settings (key, value) VALUES ('llm_model', 'template')")
    db.commit()
    llm = FakeLLM(GOOD)
    out = explain_facts(facts(), db, llm, ON)
    assert out["source"] == "template" and out["text"] and llm.calls == []


def test_another_best_move_or_reply_is_not_a_cache_hit(db):
    # Stockfish can pick another best move or reply for the same position next time; the cached text
    # names the old ones and would contradict the arrows.
    llm = FakeLLM(GOOD)
    explain_facts(facts(), db, llm, ON)
    explain_facts(facts(best_move={"san": "Nf6", "uci": "g8f6"}, best_line=["Nf6"]), db, llm, ON)
    explain_facts(facts(refutation=["Qh4"]), db, llm, ON)
    assert len(llm.calls) == 3


def test_hit_with_text_invalid_for_new_facts_is_recomputed(db):
    llm = FakeLLM(GOOD)
    explain_facts(facts(), db, llm, ON)
    gone = {"change": 0, "lost": [], "gained": []}
    other = facts(motifs_against=[], material=gone)  # same best move and reply: the same cache key
    out = explain_facts(other, db, llm, ON)
    assert len(llm.calls) == 2
    assert out["source"] == "template"
    assert db.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 0
