import dataclasses

import pytest
from fastapi.testclient import TestClient

from app.config import settings as base
from app.lessons import ask
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
    llm = FakeLLM(GOOD)
    out = post(llm).json()
    assert out == {"answer": GOOD, "source": "llm", "reason": None}
    assert "Почему конь так хорош" in llm.calls[0][1]


def test_invented_move_gives_reason():
    out = post(FakeLLM("Лучше всего играть Bc4, это сильный ход.")).json()
    assert out["answer"] is None and out["reason"] == ask.INEXACT


def test_disabled_gives_reason():
    llm = FakeLLM(GOOD)
    out = post(llm, dataclasses.replace(ON, llm_enabled=False)).json()
    assert out["answer"] is None and out["reason"] == ask.UNAVAILABLE
    assert llm.calls == []


def test_llm_error_gives_reason():
    out = post(FakeLLM(None)).json()
    assert out["answer"] is None and out["reason"] == ask.UNAVAILABLE


def test_bad_input():
    assert post(FakeLLM(GOOD), question="").status_code == 422
    assert post(FakeLLM(GOOD), position=99).status_code == 404


@pytest.mark.parametrize(
    "text",
    [
        "",
        "The knight forks two pieces.",
        "Это нужно. " * 7,
        "Конь на поле g7 силён.",
        "Конь сильнeе.",
    ],
)
def test_check_rejects(text):
    assert ask.check(text, "Конь Nf7 бьёт ферзя")


@pytest.mark.engine
def test_position_facts_reach_the_prompt():
    llm = FakeLLM(GOOD)
    assert post(llm, position=0).json()["answer"] == GOOD
    user = llm.calls[0][1]
    assert "ФАКТЫ О ПОЗИЦИИ" in user and "Лучшая линия: Nf7+" in user
