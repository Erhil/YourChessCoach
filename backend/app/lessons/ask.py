"""The "Ask the coach" question in a lesson: prompt and check of the answer."""

import logging
import re

import chess

from app.coach.prompt import figurine_to_san
from app.coach.validator import SAN

log = logging.getLogger("app.lessons.ask")

UNAVAILABLE = "Тренер сейчас недоступен"
INEXACT = "Тренер не смог ответить точно — попробуйте переформулировать вопрос"
MAX_SENTENCES = 6

SYSTEM = (
    "Ты дружелюбный шахматный тренер для новичка. Ответь на вопрос в 2–5 коротких "
    "предложениях по-русски. Используй ТОЛЬКО текст урока и факты ниже. Если ответа в них нет, "
    "так и скажи и посоветуй перечитать урок или спросить про позицию. Ходы пиши только так, "
    "как они записаны в материале (например Nf3), фигуры называй словами. Не называй числовые "
    "оценки позиции. Не используй разметку и списки."
)


def _bare(san: str) -> str:
    return san.rstrip("+#")


def lesson_context(lesson: dict) -> str:
    parts, n = [f"Урок: {lesson['title']}"], 0
    for s in lesson["segments"]:
        if s["type"] == "markdown":
            parts.append(s["text"])
        else:
            n += 1
            sol = " ".join(s["solution"])
            parts.append(f"Позиция {n}. Задание: {s['task']} Подсказка: {s['hint']} Решение: {sol}")
    return "\n\n".join(parts)


def position_facts(fen: str, solution: list[str], analysis: list[dict]) -> str:
    out = [f"ФАКТЫ О ПОЗИЦИИ (движок): FEN {fen}. Решение из урока: {' '.join(solution)}."]
    if analysis:
        out.append("Лучшая линия: " + " ".join(analysis[0]["pv_san"][:4]) + ".")
    return "\n".join(out)


def best_line(fen: str, pool) -> list[dict]:
    try:
        return pool.analyse(chess.Board(fen), depth=16)[1]
    except Exception as exc:  # noqa: BLE001 - no engine: answer from the lesson text only
        log.warning("engine facts skipped: %s", exc)
        return []


def build_user(question: str, context: str, facts: str | None) -> str:
    return f"{context}\n\n{facts or ''}\n\nВОПРОС: {question}"


def check(answer: str, context: str) -> list[str]:
    """Reasons to reject the answer; an empty list means it is valid."""
    text = figurine_to_san(answer or "").strip()
    if not text:
        return ["empty answer"]
    known = {_bare(m[1]) for m in SAN.finditer(context)}
    for tok in list(known):
        known |= set(re.findall(r"[a-h][1-8]", tok))
    reasons = [
        f"move or square not in context: {m[1]}"
        for m in SAN.finditer(text)
        if _bare(m[1]) not in known
    ]
    rest = SAN.sub(" ", text)
    if len([s for s in re.split(r"[.!?…]+(?:\s|$)", rest) if s.strip()]) > MAX_SENTENCES:
        reasons.append("too many sentences")
    letters = [c for c in rest if c.isalpha()]
    if not letters or sum("Ѐ" <= c <= "ӿ" for c in letters) / len(letters) < 0.6:
        reasons.append("text is not mostly Russian")
    for w in re.findall(r"[^\W\d_]+", text):
        if any(c.isascii() for c in w) and any("Ѐ" <= c <= "ӿ" for c in w):
            reasons.append(f"mixed Latin and Cyrillic letters in word: {w}")
    return reasons
