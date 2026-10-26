"""Checks LLM text against the facts. An empty list means the text is valid."""

import re

from app.coach.prompt import figurine_to_san
from app.coach.schema import CoachFacts
from app.coach.templates import fig

PIECE_MOVE = r"[KQRBN][a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?"
PAWN_MOVE = r"[a-h](?:x[a-h])?[1-8](?:=[QRBN])?[+#]?"
_SAN = rf"(?<![A-Za-z0-9])(O-O(?:-O)?[+#]?|{PIECE_MOVE}|{PAWN_MOVE})(?![A-Za-z0-9])"
SAN = re.compile(_SAN)
# "Лучше было сыграть c4", "лучший ход был Qg5": the move named here must be the engine's best move.
RECOMMEND = re.compile(
    r"(?i:лучше|лучш\w+\s+ход\w*|стоило|следовало)"
    r"(?:\s+(?i:бы|был\w*|сыграть|пойти|ходом|ход))*[\s:—–-]+" + _SAN
)
MATE_IN = re.compile(r"\bмат\w*\s+в\s+(\d+)", re.IGNORECASE)
NUM_WORDS = {
    "один": 1, "одного": 1, "одним": 1, "одну": 1, "два": 2, "две": 2, "двух": 2, "три": 3,
    "трех": 3, "четыре": 4, "четырех": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8,
    "девять": 9, "десять": 10,
}  # fmt: skip
_NUM = "|".join(NUM_WORDS)
MATE_IN_WORD = re.compile(rf"\bмат\w*\s+в\s+({_NUM})\b")
MOVES_WORD = re.compile(rf"\b({_NUM})\s+ход(?:а|ов|у)?\b")
# Russian piece nouns: stem plus every case ending. "е" stands for "ё" too (text is normalised).
_ENDS = ["ь", "я", "ю", "ем", "е", "и", "ей", "ям", "ями", "ях"]
PIECE_FORMS = {
    "K": ("корол", _ENDS),
    "Q": ("ферз", _ENDS),
    "R": ("ладь", ["я", "и", "ю", "ей", "е", "ям", "ями", "ях"]),
    "B": ("слон", ["", "а", "у", "ом", "е", "ы", "ов", "ам", "ами", "ах"]),
    "N": ("кон", _ENDS),
    "P": ("пешк", ["а", "и", "е", "у", "ой", "ою", "ам", "ами", "ах"]),
}
WORD_PIECE = {st + e: k for k, (st, ends) in PIECE_FORMS.items() for e in ends} | {"пешек": "P"}
LOSS_WORD = re.compile(r"потер|теря|отда[леюв]|лиши[лт]|лишае")
LIST_MARKER = re.compile(r"(?m)^\s*(?:[-*•–]|\d+[.)])\s")
MARKDOWN = re.compile(r"[*_`#\[\]|]|^\s*>", re.MULTILINE)
_OPP = r"(?:соперник|противник)\w*\s+(?:\w+\s+)?(?:сделал|сыграл|пошел|ходит|ответил)\w*\s+"
_YOU = r"(?:вы\s+(?:\w+\s+)?(?:сыграли|сделали|пошли|ответили)|ваш\s+ход)\s+"
_MOVE_PREFIX = r"(?:(?:ход|ходом)\s+)?"
STALEMATE_WORD = re.compile(r"\bпат(?:а|у|ом|е)?\b|ничь")
LOSS_OUTCOME = re.compile(r"проигр|поражен")
PLAIN_PAT = re.compile(r"\bпат(?:а|у|ом|е)?\b")
MISTAKE_WORD = re.compile(r"зевок|зевк|ошибк")
# Praise: "хороший ход", "ход, который был хорошим". Not "лучший": the text often says so of the best move.
PRAISE_WORD = re.compile(
    r"(?<!не )(?:отличн|хорош|прекрасн)\w*\s+ход"
    r"|(?<!не )(?:был|была|было|является|оказался)\s+(?:отличн|хорош|прекрасн)\w*"
)
BAD_CLASSES = ("inaccuracy", "mistake", "blunder")
INFORMAL = re.compile(
    r"\b(?:проверяй|обращай|смотри|ищи|думай|следи|помни|считай|ты|тебя|тебе|твой|твоя|твои|твое)\b"
)


def _bare(san: str) -> str:
    return san.rstrip("+#")


def _allowed(f: CoachFacts) -> tuple[set[str], set[str], set[int]]:
    moves = [f.player_move.san, *f.best_line, *f.refutation]
    squares = {f.player_move.uci[:2], f.player_move.uci[2:4]}
    if f.best_move:
        moves.append(f.best_move.san)
        squares |= {f.best_move.uci[:2], f.best_move.uci[2:4]}
    if f.threat:
        moves.append(f.threat.move_san)
    for m in [*f.motifs_against, *f.motifs_missed]:
        if m.move_san:
            moves.append(m.move_san)
        squares |= {s["square"] for s in [m.by, *m.targets]}
    for r in [*f.reasons_against, *f.reasons_missed]:
        squares |= set(r.squares) | {p["square"] for p in r.pieces}
    for san in moves:
        squares |= set(re.findall(r"[a-h][1-8]", san))
    mates = {n for n in (f.allowed_mate_in, f.missed_mate_in) if n}
    if f.threat and f.threat.mate_in:
        mates.add(f.threat.mate_in)
    return {_bare(m) for m in moves}, squares, mates


def _fact_pieces(f: CoachFacts, moves: set[str]) -> tuple[set[str], set[str]]:
    """Piece letters present in the facts, and those a loss sentence may name.

    A loss sentence may name the lost pieces and the pieces that take or attack them.
    """
    shown = set()
    for san in moves:
        shown |= set(re.findall(r"=([QRBN])", san))
        shown |= {san[0]} if san[0] in "KQRBN" else {"K", "R"} if san[0] == "O" else {"P"}
    mine = str.isupper if f.side == "white" else str.islower
    lost = {p.upper() for p in f.material.lost}
    for m in f.motifs_against:
        lost |= {t["piece"].upper() for t in m.targets if mine(t["piece"])}
    for m in [*f.motifs_against, *f.motifs_missed]:
        shown |= {s["piece"].upper() for s in [m.by, *m.targets]}
    for r in [*f.reasons_against, *f.reasons_missed]:
        shown |= {p["piece"].upper() for p in r.pieces}
    for mat in (f.material, f.missed_material):
        shown |= {p.upper() for p in [*mat.lost, *mat.gained]}
    shown_all = shown | lost
    for m in f.motifs_against:
        lost.add(m.by["piece"].upper())
    for san in f.refutation:
        lost |= {san[0]} if san[0] in "KQRBN" else {"K", "R"} if san[0] == "O" else {"P"}
    return shown_all, lost


def _piece_words(sentence: str) -> list[tuple[str, str]]:
    words = re.findall(r"[а-я]+", sentence.lower().replace("ё", "е"))
    return [(w, WORD_PIECE[w]) for w in words if w in WORD_PIECE]


def _role_reasons(text: str, f: CoachFacts) -> list[str]:
    """The player's move must not be called the opponent's move, and the other way round."""
    low = text.lower().replace("ё", "е")
    mine = _bare(f.player_move.san)
    theirs = _bare(f.refutation[0]) if f.refutation else None
    if mine == theirs:
        return []
    mv = _MOVE_PREFIX + re.escape(mine.lower()) + r"(?![a-z0-9])"
    reasons = []
    if re.search(r"(?:" + _OPP + r"|ход\s+(?:соперника|противника)\s+)" + mv, low):
        reasons.append(f"move {mine} named as the opponent's move")
    if theirs and re.search(_YOU + _MOVE_PREFIX + re.escape(theirs.lower()) + r"(?![a-z0-9])", low):
        reasons.append(f"move {theirs} named as the player's move")
    return reasons


def _outcome_reasons(low: str, f: CoachFacts) -> list[str]:
    reasons = []
    if f.game_over == "stalemate":
        if not STALEMATE_WORD.search(low):
            reasons.append("stalemate is not named as a draw")
        if LOSS_OUTCOME.search(low):
            reasons.append("stalemate described as a loss")
    elif f.game_over is None and PLAIN_PAT.search(low):
        reasons.append("stalemate in text but not in facts")
    if f.classification in ("best", "good") and MISTAKE_WORD.search(low):
        reasons.append("mistake word for a good move")
    if f.classification in BAD_CLASSES and PRAISE_WORD.search(low):
        reasons.append("praise for a bad move")
    return reasons


def _recommend_reasons(text: str, f: CoachFacts) -> list[str]:
    """A move the text recommends must be the best move, not only a move or square in the facts."""
    best = _bare(f.best_move.san) if f.best_move else None
    return [
        f"recommended move is not the best move: {m[1]}"
        for m in RECOMMEND.finditer(text)
        if _bare(m[1]) != best
    ]


def validate(text: str, facts: CoachFacts) -> list[str]:
    text = figurine_to_san(text or "").strip()
    if not text:
        return ["empty text"]
    moves, squares, mates = _allowed(facts)
    reasons = []

    for m in SAN.finditer(text):
        tok = _bare(m[1])
        is_square = re.fullmatch(r"[a-h][1-8]", tok)
        if tok not in moves and not (is_square and tok in squares):
            reasons.append(f"move or square not in facts: {m[1]}")
    rest = SAN.sub(" ", text)

    if LIST_MARKER.search(text) or MARKDOWN.search(rest):
        reasons.append("markdown or list markers")
    sentences = [s for s in re.split(r"[.!?…]+(?:\s|$)", rest) if s.strip()]
    if len(sentences) > 4:
        reasons.append(f"too many sentences: {len(sentences)}")
    letters = [c for c in rest if c.isalpha()]
    cyrillic = sum("Ѐ" <= c <= "ӿ" for c in letters)
    if not letters or cyrillic / len(letters) < 0.6:
        reasons.append("text is not mostly Russian")
    for w in re.findall(r"[^\W\d_]+", text):
        if any(c.isascii() for c in w) and any("Ѐ" <= c <= "ӿ" for c in w):
            reasons.append(f"mixed Latin and Cyrillic letters in word: {w}")
    plain = rest.lower().replace("ё", "е")
    for n in {*MATE_IN_WORD.findall(plain), *MOVES_WORD.findall(plain)}:
        if NUM_WORDS[n] not in mates:
            reasons.append(f"number in words not in facts: {n}")
    shown, lost = _fact_pieces(facts, moves)
    for w in re.findall(r"[а-я]+", plain):
        if w not in WORD_PIECE and any(
            w.startswith(st) for st, _ in PIECE_FORMS.values() if st != "кон"
        ):
            reasons.append(f"unknown form of piece word: {w}")
    for w, piece in _piece_words(rest):
        if piece not in shown:
            reasons.append(f"piece not in facts: {w}")
    for sent in re.split(r"[.!?…]+(?:\s|$)", rest):
        if LOSS_WORD.search(sent.lower()):
            reasons += [
                f"lost piece not in material.lost: {w}"
                for w, piece in _piece_words(sent)
                if piece not in lost
            ]
    for n in MATE_IN.findall(rest):
        if int(n) not in mates:
            reasons.append(f"mate in {n} not in facts")
    if re.search(r"\d", MATE_IN.sub(" ", rest)):
        reasons.append("digits in text")
    reasons += _role_reasons(text, facts)
    reasons += _recommend_reasons(text, facts)
    reasons += _outcome_reasons(plain, facts)
    reasons += [f"informal address: {m}" for m in INFORMAL.findall(plain)]
    return reasons


def to_display(text: str) -> str:
    """Figurine notation for the UI: Nf3 -> ♘f3. Call it on validated text."""
    return SAN.sub(lambda m: fig(m[1]), figurine_to_san(text))
