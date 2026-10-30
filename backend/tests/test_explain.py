import dataclasses
import hashlib
import json
import logging
import re
from pathlib import Path

import pytest

from app.coach.explain import explain_facts
from app.coach.schema import CoachFacts
from app.coach.templates import explain
from app.config import settings as base_settings
from app.db import connect, migrate
from tests.fakes import FakeLLM
from tests.test_validator import facts

GOOD = '{"tip":"repeat"}'

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


def test_all_facts_invalidate_cache(db):
    llm = FakeLLM(GOOD)
    explain_facts(facts(), db, llm, ON)
    out = explain_facts(facts(missed_mate_in=1), db, llm, ON)
    assert len(llm.calls) == 2
    assert out["text"].startswith(explain(facts(missed_mate_in=1)))


@pytest.mark.parametrize(
    "sample",
    json.loads(
        (Path(__file__).parent / "fixtures" / "unsafe_coach.json").read_text(encoding="utf-8")
    ),
    ids=lambda sample: sample["id"],
)
def test_saved_role_contradictions_fall_back(db, sample):
    f = CoachFacts.model_validate(sample["facts"])
    out = explain_facts(f, db, FakeLLM(sample["text"]), ON)
    assert out == {"text": explain(f), "source": "template", "model": None}


@pytest.mark.parametrize(
    "text",
    [
        "После Qh4 вы выигрываете ферзя.",
        '{"tip":"repeat","text":"После Qh4 вы выигрываете ферзя."}',
        '{"tip":"Вы ставите мат в один ход."}',
    ],
)
def test_material_and_mate_claims_cannot_reach_user(db, text):
    out = explain_facts(facts(), db, FakeLLM(text), ON)
    assert out == {"text": explain(facts()), "source": "template", "model": None}


def test_legacy_and_poisoned_cache_cannot_return_prose(db):
    f = facts()
    unsafe = "После Qh4 вы выигрываете ферзя."
    legacy = (
        f"{f.fen_before}\n{f.player_move.uci}\n{ON.llm_model}\n{f.best_move.uci}\n{f.refutation[0]}"
    )
    db.execute(
        "INSERT INTO llm_cache VALUES (?, ?, ?, 'old')",
        (hashlib.sha256(legacy.encode()).hexdigest(), ON.llm_model, unsafe),
    )
    llm = FakeLLM(GOOD)
    out = explain_facts(f, db, llm, ON)
    assert out["source"] == "llm" and unsafe not in out["text"] and len(llm.calls) == 1
    db.execute("UPDATE llm_cache SET text = ?", (unsafe,))
    llm.text = unsafe
    out = explain_facts(f, db, llm, ON)
    assert out == {"text": explain(f), "source": "template", "model": None}


def test_safe_selection_renders_trusted_advice_with_sentence_bound(db):
    short = facts(best_move=None)
    out = explain_facts(short, db, FakeLLM(GOOD), ON)
    assert out["text"].startswith(explain(short))
    assert "повторите проверку" in out["text"]
    four = facts()
    core = explain(four)
    # Four trusted sentences already fill the display budget.
    assert len(re.split(r"[.!?]+(?:\s|$)", core.strip())) - 1 == 4
    assert explain_facts(four, db, FakeLLM(GOOD), ON)["text"] == core
