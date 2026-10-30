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
    selected = next(
        p
        for p in ask.passage_catalog(ask.lesson_context(lesson))
        if p["text"].startswith("Конь. Он ходит")
    )
    llm = LessonLLM(selected, json.dumps({"verdict": "yes", "evidence": selected["text"]}))
    out = post(llm).json()
    assert out == {"answer": to_display(selected["text"]), "source": "llm", "reason": None}
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


class LessonLLM:
    """Network boundary with separate selection and verification responses."""

    def __init__(self, passage, verdict):
        self.responses = iter([json.dumps({"passage": passage["id"]}), verdict])
        self.calls = []

    def chat(self, system, user, model):
        self.calls.append((system, user, model))
        response = next(self.responses)
        if response is None:
            from app.llm.client import LLMError

            raise LLMError("verification unavailable")
        return response


def test_valid_but_irrelevant_selection_has_honest_no_answer():
    lesson = load_lesson(base.lessons_dir / "08-fork.md")
    selected = ask.passage_catalog(ask.lesson_context(lesson))[0]
    llm = LessonLLM(selected, '{"verdict":"no_answer","evidence":null}')
    question = "Как поставить мат двумя слонами?"
    out = post(llm, question=question).json()
    assert out == {"answer": None, "source": None, "reason": ask.NO_ANSWER}
    assert json.loads(llm.calls[1][1]) == {
        "question": question,
        "passage": to_display(selected["text"]),
    }
    assert llm.calls[0][2] == llm.calls[1][2]


def test_null_selection_has_honest_no_answer():
    llm = FakeLLM('{"passage":null}')
    assert post(llm).json() == {"answer": None, "source": None, "reason": ask.NO_ANSWER}
    assert len(llm.calls) == 1


@pytest.mark.parametrize(
    "question,starts,accepted",
    [
        ("Почему конь прыгает буквой Г, а не на две клетки по диагонали?", "Конь ходит", False),
        ("Как ходит конь?", "Конь ходит", True),
        ("Почему вилка с шахом сильна?", "Конь одновременно", True),
    ],
)
def test_reason_request_requires_authored_cause(tmp_path, question, starts, accepted):
    lesson = load_lesson(base.lessons_dir / "01-board-and-moves.md")
    selected = next(
        p for p in ask.passage_catalog(ask.lesson_context(lesson)) if p["text"].startswith(starts)
    )
    llm = LessonLLM(selected, json.dumps({"verdict": "yes", "evidence": [selected["text"]]}))
    settings = dataclasses.replace(ON, app_db_path=tmp_path / "reason.db")
    with TestClient(create_app(settings)) as client:
        client.app.state.llm = llm
        out = client.post("/api/lessons/board-and-moves/ask", json={"question": question}).json()
    if accepted:
        assert out == {"answer": selected["text"], "source": "llm", "reason": None}
    else:
        assert out == {"answer": None, "source": None, "reason": ask.NO_ANSWER}
    assert json.loads(llm.calls[1][1])["question"] == question


def test_evidence_spans_allow_exact_reordering_and_quote_wrappers():
    passage = "Конь ходит буквой «Г». Он перепрыгивает через другие фигуры."
    evidence = ["«Он перепрыгивает через другие фигуры.»", "Конь ходит буквой «Г»."]
    payload = json.dumps({"verdict": "yes", "evidence": evidence})
    assert ask.verify_answer(payload, passage, "Как ходит конь?")
    evidence.append("Он ходит назад на две клетки.")
    with pytest.raises(ValueError, match="evidence"):
        ask.verify_answer(json.dumps({"verdict": "yes", "evidence": evidence}), passage, "Как?")


def test_castling_definition_does_not_explain_a_requested_reason(tmp_path):
    lesson = load_lesson(base.lessons_dir / "06-opening-principles.md")
    selected = next(
        p for p in ask.passage_catalog(ask.lesson_context(lesson)) if "две клетки" in p["text"]
    )
    llm = LessonLLM(selected, json.dumps({"verdict": "yes", "evidence": selected["text"]}))
    settings = dataclasses.replace(ON, app_db_path=tmp_path / "castling.db")
    with TestClient(create_app(settings)) as client:
        client.app.state.llm = llm
        out = client.post(
            "/api/lessons/opening-principles/ask",
            json={
                "question": "Почему при длинной рокировке король проходит две клетки, а ладья три?"
            },
        ).json()
    assert out == {"answer": None, "source": None, "reason": ask.NO_ANSWER}


@pytest.mark.parametrize(
    "verdict,reason",
    [
        ('{"verdict":"yes","evidence":"invented evidence"}', ask.INEXACT),
        ('{"verdict":"yes","evidence":""}', ask.INEXACT),
        ('{"verdict":"maybe","evidence":null}', ask.INEXACT),
        ('{"verdict":"no_answer","evidence":null,"extra":true}', ask.INEXACT),
        ("not JSON", ask.INEXACT),
        (None, ask.UNAVAILABLE),
    ],
)
def test_verification_failure_stays_distinct(verdict, reason):
    lesson = load_lesson(base.lessons_dir / "08-fork.md")
    selected = ask.passage_catalog(ask.lesson_context(lesson))[0]
    assert post(LessonLLM(selected, verdict)).json() == {
        "answer": None,
        "source": None,
        "reason": reason,
    }
