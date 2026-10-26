"""Questions to the coach about one move: three template answers and a free question.

Every chess claim comes from the engine. All answers are templates and work with the LLM off.
A free question has a grounded template answer too; the LLM does not touch it.
"""

import logging

import chess

from app.coach.classify import ORDER
from app.coach.schema import CoachFacts
from app.coach.templates import (
    _better,
    _first,
    _items,
    _net,
    _phrase,
    _reason_text,
    fig,
)
from app.coach.variants import (
    Asked,
    QuestionFacts,
    Variant,
    candidates,
    question_facts,
)
from app.config import Settings
from app.engines.pool import EnginePool, EngineUnavailableError

log = logging.getLogger("app.coach.ask")

NO_THREAT = "Явной угрозы нет: соперник просто улучшает позицию."
FINE = "Ход не ошибка: тренер не нашёл в нём серьёзных минусов."
VERDICT = {
    "best": "{} — сильный ход, один из лучших в позиции.",
    "good": "{} — хороший ход: он почти не хуже лучшего.",
    "inaccuracy": "{} — неточность.",
    "mistake": "{} — ошибка.",
    "blunder": "{} — зевок.",
}
OPP_VERDICT = {
    "inaccuracy": "Для соперника {} — неточность.",
    "mistake": "Для соперника {} — ошибка.",
    "blunder": "Для соперника {} — зевок.",
}


def _pm(f: CoachFacts) -> str:
    return fig(f.player_move.san)


def _loss(f: CoachFacts) -> str | None:
    lost, gained = _net(f.material)
    if f.material.change >= 0 or not lost:
        return None
    return _items(lost, "acc") + (f" за {_items(gained, 'acc')}" if gained else "")


def _bad(f: CoachFacts) -> bool:
    return f.classification in ("inaccuracy", "mistake", "blunder")


def _missed_win(f: CoachFacts) -> str | None:
    """What the best move wins, when the played move loses nothing and is not the best move."""
    if not f.best_move or f.best_move.san == f.player_move.san or _loss(f):
        return None
    lost, won = _net(f.missed_material)
    if f.missed_material.change <= 0 or not won:
        return None
    return _items(won, "acc") + (f" за {_items(lost, 'acc')}" if lost else "")


def why(f: CoachFacts) -> str:
    if not _bad(f):
        return FINE
    ref0 = fig(f.refutation[0]) if f.refutation else None
    s: list[str | None] = []
    if f.allowed_mate_in:
        s.append(
            f"После {_pm(f)} у соперника мат в {f.allowed_mate_in}"
            + (f": {ref0}." if ref0 else ".")
        )
    elif ref0 and (missed := _missed_win(f)):  # the reply is a quiet defence: the point is the miss
        s.append(f"Можно было выиграть {missed}: {fig(f.best_move.san)}.")
    elif ref0:
        s.append(f"После {_pm(f)} соперник может ответить {ref0}.")
    loss = None if f.allowed_mate_in else _loss(f)  # after a mate the lost pawn is noise
    if loss:
        s.append(f"В итоге вы теряете {loss}.")
    s.append(_phrase(_first(f.motifs_against), "against"))
    s.append(_reason_text(f, f.reasons_against[0] if f.reasons_against else None, "against"))
    return " ".join(x for x in s if x) or "Ход заметно слабее лучшего."


def threat(f: CoachFacts) -> str:
    if not f.refutation or f.game_over:
        return NO_THREAT
    ref0 = fig(f.refutation[0])
    if f.allowed_mate_in:
        return f"У соперника мат в {f.allowed_mate_in}: {ref0}."
    reason = f.reasons_against[0] if f.reasons_against else None
    why_ = _phrase(_first(f.motifs_against), "against")
    if reason and reason.kind == "reply_attacks":
        why_ = why_ or _reason_text(f, reason, "against")
    loss = _loss(f)
    if not why_ and loss:
        why_ = f"Он выигрывает {loss}."
    return f"Соперник может ответить {ref0}. {why_}" if why_ else NO_THREAT


def also_good(f: CoachFacts, cands: list[Variant]) -> str | None:
    """Up to two other top moves as good as the best one: not the best, not the played one."""
    skip = {f.best_move.san if f.best_move else None, f.player_move.san}
    names = [
        fig(v.san)
        for v in cands
        if v.verdict in ("best", "good") and v.san not in skip and v.mover == f.side
    ][:2]
    if not names:
        return None
    if len(names) == 1:
        return f"Почти так же хорош {names[0]}."
    return f"Почти так же хороши {names[0]} и {names[1]}."


def better(f: CoachFacts, cands: list[Variant] | None = None) -> str:
    pm = _pm(f)
    best = fig(f.best_move.san) if f.best_move else None
    if not best or best == pm:
        return f"Ход {pm} и есть лучший в этой позиции."
    s: list[str | None] = [_better(f, best, pm)]
    given, won = _net(f.missed_material)
    if f.missed_mate_in:
        s.append(f"Это ведёт к мату в {f.missed_mate_in}.")
    elif f.missed_material.change > 0 and won:
        label = _phrase(_first(f.motifs_missed), "label")
        gain = _items(won, "acc") + (f" за {_items(given, 'acc')}" if given else "")
        s.append(f"Он выигрывает {gain}" + (f" — {label}." if label else "."))
    if len(f.best_line) > 1:
        s.append("Дальше может быть так: " + " ".join(fig(m) for m in f.best_line[:2]) + ".")
    s.append(also_good(f, cands or []))
    return " ".join(x for x in s if x)


def line(f: CoachFacts, question: str) -> dict:
    """Moves (SAN) for the board and the position they start from; the client draws the arrows."""
    if question == "better":
        return {"fen": f.fen_before, "moves": f.best_line[:3]}
    board = chess.Board(f.fen_before)
    board.push_uci(f.player_move.uci)
    return {"fen": board.fen(), "moves": f.refutation[:1]}


TEMPLATES = {"why": why, "threat": threat, "better": better}


def _reply(v: Variant) -> str | None:
    return fig(v.line[1].san) if len(v.line) > 1 else None


def _player_move(a: Asked) -> str:
    """Answer about a move of the player: the played one or an alternative."""
    v, x = a.variant, fig(a.move.san)
    intro = f"После вашего хода {x}" if a.played else f"Если вы сыграете {x},"
    reply, n = _reply(v), abs(v.mate or 0)
    s: list[str | None] = []
    if v.mate and v.mate < 0 and reply:
        s.append(
            f"{intro} соперник может ответить {reply} — это мат."
            if n == 1
            else f"{intro} у соперника мат в {n}: начинает {reply}."
        )
    elif v.mate:
        s.append(
            f"{intro} вы ставите мат."
            if v.line[0].san.endswith("#")
            else f"{intro} у вас мат в {n}."
        )
    else:
        s.append(
            f"{intro} сильнейший ответ соперника — {reply}." if reply else f"{intro.rstrip(',')}."
        )
        s.append(VERDICT[v.verdict].format(x))
        lost = _net(v.material)[0] if v.material.change < 0 else None
        if lost:
            s.append(f"В итоге вы теряете {_items(lost, 'acc')}.")
    return " ".join(x for x in s if x)


def _opponent_move(a: Asked) -> str:
    """Answer about a move of the opponent, with the player's best reply from the engine."""
    v, x = a.variant, fig(a.move.san)
    intro = f"Если соперник сыграет {x}"
    reply, n = _reply(v), abs(v.mate or 0)
    s: list[str | None] = []
    if v.mate and v.mate > 0:
        s.append(
            f"{x} ставит мат." if v.line[0].san.endswith("#") else f"{intro}, у него мат в {n}."
        )
    elif v.mate and reply:
        s.append(
            f"{intro}, вы ставите мат: {reply}."
            if n == 1
            else f"{intro}, у вас мат в {n}: начинает {reply}."
        )
    else:
        s.append(f"{intro}, лучший ответ — {reply}." if reply else f"{intro}.")
        s.append(OPP_VERDICT[v.verdict].format(x) if v.verdict in OPP_VERDICT else None)
        lost, gained = _net(v.material)
        if v.material.change > 0 and gained:
            s.append(f"Вы теряете {_items(gained, 'acc')}.")
        elif v.material.change < 0 and lost:
            s.append(f"Соперник теряет {_items(lost, 'acc')}.")
    return " ".join(x for x in s if x)


def _rank(a: Asked) -> tuple[int, float]:
    return ORDER.index(a.variant.verdict), -a.variant.win_chance


def template_free(q: QuestionFacts) -> str:
    """Answer about the moves of the question from the engine variants. No LLM."""
    own = [a for a in q.asked if a.move.owner == "player"]
    best = next((v for v in q.candidates if v.mover == q.facts.side), None)
    parts = [_player_move(a) for a in own]
    parts += [_opponent_move(a) for a in q.asked if a.move.owner == "opponent"]
    if len(own) > 1:
        first, second = sorted(own, key=_rank)[:2]
        (r1, w1), (r2, w2) = _rank(first), _rank(second)
        if r1 == r2 and abs(w1 - w2) < 0.03:
            bad = first.variant.verdict not in ("best", "good")
            parts.append("Оба хода слабые." if bad else "Эти ходы примерно равны по силе.")
        else:
            parts.append(f"Из этих ходов лучше {fig(first.move.san)}.")
    top = min(own, key=_rank) if own else None
    shown = {a.move.san for a in own}
    if top and best and top.variant.verdict not in ("best", "good") and best.san not in shown:
        parts.append(f"Лучше было {fig(best.san)}.")
    return " ".join(parts)


def grounded(f: CoachFacts, q: QuestionFacts | None) -> str:
    """The answer to a free question from the engine and the templates. No LLM."""
    if q and q.asked:
        return template_free(q)
    parts = [why(f), better(f, q.candidates if q else [])]
    if f.threat and not f.allowed_mate_in:  # a mate is already in the why answer
        parts.append(threat(f))
    return " ".join(parts)


def free(f: CoachFacts, text: str, settings: Settings, pool: EnginePool | None = None) -> dict:
    """The answer to a free question is always the grounded template answer."""
    q = None
    if pool:
        try:
            q = question_facts(pool, f, text, settings)
        except EngineUnavailableError as exc:
            log.warning("question variants skipped: %s", exc)
    return {"answer": grounded(f, q), "source": "template", "line": None, "reason": None}


def _top(f: CoachFacts, settings: Settings, pool: EnginePool | None) -> list[Variant]:
    if not pool:
        return []
    try:
        return candidates(pool, chess.Board(f.fen_before), settings.coach_depth)
    except EngineUnavailableError as exc:
        log.warning("candidates skipped: %s", exc)
        return []


def answer(
    f: CoachFacts,
    question: str,
    text: str | None,
    settings: Settings,
    pool: EnginePool | None = None,
) -> dict:
    if question == "free":
        return free(f, text or "", settings, pool)
    if question == "better":
        reply = better(f, _top(f, settings, pool))
    else:
        reply = TEMPLATES[question](f)
    return {"answer": reply, "source": "template", "line": line(f, question), "reason": None}
