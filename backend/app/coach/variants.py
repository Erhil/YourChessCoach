"""Engine variants for free questions: the top moves of a position and the moves named in a question.

Every number and every line here comes from Stockfish; the verdicts use the same thresholds as
the move classification.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

import chess
from pydantic import BaseModel

from app.coach.classify import classify, mover_view, score_win_chance, thresholds
from app.coach.facts import cut_line, settled_material
from app.coach.prompt import figurine_to_san
from app.coach.schema import CoachFacts, Material
from app.config import Settings
from app.config import settings as default_settings
from app.engines.pool import EnginePool

MAX_LINE = 6
MAX_NAMED = 3
Side = Literal["white", "black"]
Owner = Literal["player", "opponent"]

_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(O-O-O|O-O|0-0-0|0-0"
    r"|[KQRBN][a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?"
    r"|[a-h](?:x[a-h])?[1-8](?:=[QRBN])?)[+#]?(?![A-Za-z0-9])"
)
# A bare lowercase square after one of these words is a square, not a pawn move: "конь на f6".
SQUARE_WORDS = {"на", "с", "со", "в", "во", "к", "от", "до", "у", "над", "под", "поле", "поля"}
_OPPONENT_WORD = re.compile(r"соперник|противник")


class Ply(BaseModel):
    san: str
    side: Side


class Variant(BaseModel):
    san: str
    uci: str
    mover: Side
    verdict: Literal["best", "good", "inaccuracy", "mistake", "blunder"]
    win_chance: float  # of the mover
    mate: int | None  # mover's view: > 0 the mover mates, < 0 the mover gets mated
    line: list[Ply]  # starts with this move
    material: Material  # mover's view, along the line


@dataclass
class NamedMove:
    san: str
    uci: str
    owner: Owner


@dataclass
class Asked:
    move: NamedMove
    variant: Variant
    played: bool = False


@dataclass
class QuestionFacts:
    facts: CoachFacts
    candidates: list[Variant]
    asked: list[Asked] = field(default_factory=list)


def _side(color: chess.Color) -> Side:
    return "white" if color == chess.WHITE else "black"


def _variant(
    board: chess.Board,
    pv_uci: list[str],
    pv_san: list[str],
    view: dict,
    best_view: dict,
    is_best: bool,
    th: tuple[float, float, float],
) -> Variant:
    """`view` and `best_view` are scores from the mover's point of view."""
    me = board.turn
    wc_best = score_win_chance(best_view["cp"], best_view["mate"])
    wc = score_win_chance(view["cp"], view["mate"])
    verdict = classify(wc_best, wc, is_best, best_view["mate"], view["mate"], th)
    full = cut_line(board, pv_uci)  # material is counted on the whole exchange
    color = me
    line = []
    for san in pv_san[: min(len(full), MAX_LINE)]:
        line.append(Ply(san=san, side=_side(color)))
        color = not color
    material = settled_material(board, full, me)
    if not view["mate"] and (material.change < 0 < wc - 0.5 or material.change > 0 > wc - 0.5):
        # the material sentence would contradict the engine: say nothing about material
        material = Material(change=0, lost=[], gained=[])
    return Variant(
        san=pv_san[0],
        uci=pv_uci[0],
        mover=_side(me),
        verdict=verdict,
        win_chance=round(wc, 3),
        mate=view["mate"] or None,
        line=line,
        material=material,
    )


def _from_lines(board: chess.Board, lines: list[dict], th: tuple[float, float, float]):
    if not lines:
        return []
    best_view = mover_view(lines[0]["score"], board.turn)
    return [
        _variant(
            board,
            ln["pv_uci"],
            ln["pv_san"],
            mover_view(ln["score"], board.turn),
            best_view,
            i == 0,
            th,
        )
        for i, ln in enumerate(lines)
    ]


def candidates(
    pool: EnginePool,
    board: chess.Board,
    depth: int,
    k: int = 5,
    th: tuple[float, float, float] | None = None,
) -> list[Variant]:
    """The k best moves of the position, best first, each with a verdict against the best."""
    _, lines = pool.analyse(board, depth, multipv=k)
    return _from_lines(board, lines, th or thresholds(default_settings))


def analyse_move(
    pool: EnginePool,
    board: chess.Board,
    move: chess.Move,
    depth: int,
    th: tuple[float, float, float] | None = None,
    lines: list[dict] | None = None,
) -> Variant:
    """One given move: from the top lines if it is there, else the reply line after it.

    `lines` are multipv lines of `board` the caller already has.
    """
    th = th or thresholds(default_settings)
    if lines is None:
        _, lines = pool.analyse(board, depth, multipv=5)
    top = _from_lines(board, lines, th)
    for v in top:
        if v.uci == move.uci():
            return v
    me = board.turn
    san = board.san(move)
    best_view = mover_view(lines[0]["score"], me)
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        view = {"cp": None, "mate": 1}
        pv_uci, pv_san = [move.uci()], [san]
    elif after.is_game_over():
        view = {"cp": 0, "mate": None}
        pv_uci, pv_san = [move.uci()], [san]
    else:
        _, al = pool.analyse(after, depth)
        view = mover_view(al[0]["score"], me)
        pv_uci, pv_san = [move.uci(), *al[0]["pv_uci"]], [san, *al[0]["pv_san"]]
    return _variant(board, pv_uci, pv_san, view, best_view, False, th)


def moves_in_question(text: str, before: chess.Board, after: chess.Board | None) -> list[NamedMove]:
    """Moves named in the question that are legal: the player's (in `before`) or the opponent's."""
    text = figurine_to_san(text)
    low = text.lower()
    found: list[NamedMove] = []
    for m in _TOKEN.finditer(text):
        tok = m[1].replace("0", "O")
        if re.fullmatch(r"[a-h][1-8]", tok):
            words = re.findall(r"[а-яё]+", low[: m.start()])
            if words and words[-1] in SQUARE_WORDS:
                continue
        owner = _owner(tok, before, after, bool(_OPPONENT_WORD.search(low)))
        if owner is None:
            continue
        board = before if owner == "player" else after
        move = board.parse_san(tok)
        if all(n.uci != move.uci() or n.owner != owner for n in found):
            found.append(NamedMove(board.san(move), move.uci(), owner))
    return found[:MAX_NAMED]


def _owner(tok: str, before: chess.Board, after: chess.Board | None, opp_word: bool):
    legal: list[Owner] = []
    for owner, board in (("player", before), ("opponent", after)):
        if board is None or board.is_game_over():
            continue
        try:
            board.parse_san(tok)
        except ValueError:
            continue
        legal.append(owner)
    if len(legal) == 2:
        return "opponent" if opp_word else "player"
    return legal[0] if legal else None


def question_facts(
    pool: EnginePool, f: CoachFacts, text: str, settings: Settings = default_settings
) -> QuestionFacts:
    """The facts, the top-5 moves of the position before the move and the moves of the question."""
    depth, th = settings.coach_depth, thresholds(settings)
    before = chess.Board(f.fen_before)
    played = chess.Move.from_uci(f.player_move.uci)
    after = before.copy(stack=False)
    after.push(played)
    _, lines = pool.analyse(before, depth, multipv=5)
    qf = QuestionFacts(f, _from_lines(before, lines, th))
    named_moves = moves_in_question(text, before, after)
    square = rf"(?<![a-z0-9]){f.player_move.uci[2:4]}(?![a-z0-9])"
    if re.search(square, text.lower()) and all(n.uci != f.player_move.uci for n in named_moves):
        # "why is the knight on f6 bad": the question is about the played move
        named_moves.insert(0, NamedMove(f.player_move.san, f.player_move.uci, "player"))
    for named in named_moves[:MAX_NAMED]:
        is_played = named.owner == "player" and named.uci == f.player_move.uci
        board = before if named.owner == "player" else after
        v = analyse_move(
            pool,
            board,
            chess.Move.from_uci(named.uci),
            depth,
            th,
            lines if board is before else None,
        )
        if is_played:  # one verdict for the played move everywhere
            v = v.model_copy(update={"verdict": f.classification})
        qf.asked.append(Asked(named, v, is_played))
    return qf
