import dataclasses
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.coach.validator import to_display
from app.config import settings as base
from app.db import connect
from app.lessons import ask
from app.lessons.loader import load_lesson
from app.main import create_app
from tests.fakes import FakeLLM

ON = dataclasses.replace(base, llm_enabled=True)
GOOD = "Конь ходит буквой «Г» и бьёт сразу две фигуры. Например, Nf7+ даёт шах и бьёт ферзя."


def post(llm, settings=ON, **body):
    body.setdefault("question", "Почему конь так хорош для вилки?")
    with TestClient(create_app(settings)) as c:
        c.app.state.llm = llm
        return c.post("/api/lessons/fork/ask", json=body)


def test_valid_answer_is_returned():
    lesson = load_lesson(base.lessons_dir / "08-fork.md")
    selected = ask.passage_catalog(ask.lesson_context(lesson))[0]
    llm = FakeLLM(json.dumps({"passage": selected["id"]}))
    out = post(llm).json()
    catalog = json.loads(llm.calls[0][1].split("Отрывки: ", 1)[1].split("\n\n", 1)[0])
    assert out == {"answer": to_display(catalog[0]["text"]), "source": "llm", "reason": None}
    assert "Почему конь так хорош" in llm.calls[0][1]


def test_invented_move_gives_reason():
    out = post(FakeLLM("Лучше всего играть Bc4, это сильный ход.")).json()
    assert out["answer"] is None and out["reason"] == ask.INEXACT


def test_disabled_gives_reason():
    llm = FakeLLM('{"passage":0}')
    out = post(llm, dataclasses.replace(ON, llm_enabled=False)).json()
    assert out["answer"] is None and out["reason"] == ask.UNAVAILABLE
    assert llm.calls == []


def test_llm_error_gives_reason():
    out = post(FakeLLM(None)).json()
    assert out["answer"] is None and out["reason"] == ask.UNAVAILABLE


def test_bad_input():
    assert post(FakeLLM(GOOD), question="").status_code == 422
    assert post(FakeLLM(GOOD), position=99).status_code == 404


@pytest.mark.engine
def test_position_facts_reach_the_prompt():
    llm = FakeLLM('{"passage":null}')
    post(llm, position=0)
    user = llm.calls[0][1]
    assert "ФАКТЫ О ПОЗИЦИИ" in user and "Лучшая линия: Nf7+" in user


@pytest.mark.parametrize(
    "payload",
    [
        GOOD,
        '{"passage":null}',
        '{"passage":true}',
        '{"passage":0,"text":"Соперник ставит мат."}',
        '{"passage":999}',
        '{"passage":0}',
        '{"passage":"p_unknown"}',
    ],
)
def test_generated_claims_and_unavailable_answers_are_rejected(payload):
    out = post(FakeLLM(payload)).json()
    assert out == {"answer": None, "source": None, "reason": ask.INEXACT}


def test_template_selection_skips_llm_and_position_engine(tmp_path):
    settings = dataclasses.replace(ON, app_db_path=tmp_path / "lesson-template.db")
    llm = FakeLLM('{"passage":0}')

    class Engine:
        calls = 0

        def analyse(self, *args, **kwargs):
            self.calls += 1
            return None, []

    engine = Engine()
    with TestClient(create_app(settings)) as client:
        client.app.state.llm = llm
        client.app.state.pool = engine
        db = connect(settings.app_db_path)
        try:
            with db:
                db.execute(
                    "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('llm_model', ?)",
                    ("template",),
                )
        finally:
            db.close()
        response = client.post(
            "/api/lessons/fork/ask",
            json={"question": "Почему конь так хорош для вилки?", "position": 0},
        )
    assert response.status_code == 200
    assert response.json() == {"answer": None, "source": None, "reason": ask.UNAVAILABLE}
    assert llm.calls == []
    assert engine.calls == 0


def test_explicit_passage_id_returns_whole_text_after_reordering():
    lesson_path = Path(__file__).resolve().parents[2] / "content/lessons/01-board-and-moves.md"
    context = ask.lesson_context(load_lesson(lesson_path))
    catalog = ask.passage_catalog(context)
    knight = next(p for p in catalog if p["text"].startswith("Конь ходит"))
    user = ask.build_user("Как ходит конь?", context, None)
    assert knight in json.loads(user.split("Отрывки: ", 1)[1].split("\n\n", 1)[0])
    payload = json.dumps({"passage": knight["id"]})
    reordered = "\n\n".join(reversed(ask.passages(context)))
    assert ask.render_response(payload, context) == knight["text"]
    assert ask.render_response(payload, reordered) == knight["text"]
