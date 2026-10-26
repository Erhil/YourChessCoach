"""Russian template explanations for coach facts. No LLM and no engine.

Every move and square in the text comes from the facts, so the LLM validator accepts it.
"""

import re
from collections import Counter
from typing import NamedTuple

import chess

from app.coach.classify import missed_leads
from app.coach.motifs import Motif
from app.coach.schema import CoachFacts, Material
from app.coach.why import Reason, _hits

FIG = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘"}
ORDER = "QRBNP"


class Name(NamedTuple):
    nom: str
    acc: str
    gen: str
    dat: str
    fem: bool
    pl: str  # genitive plural, used for "двух коней"


NAMES = {
    "K": Name("король", "короля", "короля", "королю", False, "королей"),
    "Q": Name("ферзь", "ферзя", "ферзя", "ферзю", False, "ферзей"),
    "R": Name("ладья", "ладью", "ладьи", "ладье", True, ""),
    "B": Name("слон", "слона", "слона", "слону", False, "слонов"),
    "N": Name("конь", "коня", "коня", "коню", False, "коней"),
    "P": Name("пешка", "пешку", "пешки", "пешке", True, ""),
}
NUMS = {2: ("двух", "две"), 3: ("трёх", "три"), 4: ("четырёх", "четыре")}

CLASS_WORD = {
    "blunder": "Зевок",
    "mistake": "Ошибка",
    "inaccuracy": "Неточность",
    "good": "Хороший ход",
    "best": "Отличный ход",
}

# Phrases per motif kind. "against": why the opponent's reply works. "label": the player's
# own missed idea (after a dash). "tip" / "tip_missed": how to notice it next time.
MOTIFS = {
    "hanging_piece": {
        "against": "{Poss} {t0} оказал{suf} под боем: {by_from} может забрать {pron}.",
        "label": "{t0} стоял{a} под боем",
        "tip": "Перед каждым ходом проверяйте, какие ваши фигуры остались без защиты.",
        "tip_missed": "Перед ходом смотрите, нет ли у соперника фигуры без защиты.",
    },
    "fork": {
        "against": "{Then} будет вилка: {by} нападает сразу на {ta}.",
        "label": "вилка {tg}",
        "tip": "Перед ходом смотрите, куда соперник может поставить фигуру, чтобы она била сразу две ваши.",
        "tip_missed": "Ищите поле, с которого ваша фигура нападает сразу на две цели.",
    },
    "pin": {
        "against": "{Then} будет связка: {by} не даёт {t0_dat} уйти — за {tpron} {t1}.",
        "label": "связка {t0_gen} и {t1_gen}",
        "tip": "Не оставляйте фигуру на одной линии с королём или ферзём, если её может атаковать слон, ладья или ферзь.",
        "tip_missed": "Ищите ход, после которого фигура соперника не может уйти, потому что за ней стоит ценная.",
    },
    "skewer": {
        "against": "{Then} будет сквозной удар: {by} бьёт {t0_acc}, а за {tpron} стоит {t1}.",
        "label": "сквозной удар по {t0_acc} и {t1_acc}",
        "tip": "Не ставьте ценную фигуру на линию дальнобойной фигуры соперника, если за ней стоит ещё одна ваша.",
        "tip_missed": "Ищите шах или атаку по линии, где за ценной фигурой стоит другая.",
    },
    "discovered_attack": {
        "against": "{Then} будет вскрытое нападение: линия откроется, и {by} нападёт на {ta}.",
        "label": "вскрытое нападение на {ta}",
        "tip": "Смотрите, какую линию соперник откроет одним ходом, убрав свою фигуру.",
        "tip_missed": "Проверьте, не откроет ли ход вашей фигуры линию для другой фигуры.",
    },
    "back_rank": {
        "against": "Это мат по последней горизонтали: {by} атакует короля, а свои фигуры закрывают ему отход.",
        "label": "мат по последней горизонтали",
        "tip": "Дайте королю выход: сдвиньте пешку перед ним, чтобы не получить мат на последней горизонтали.",
        "tip_missed": "Если король соперника закрыт своими пешками, ищите шах ладьёй или ферзём на последней горизонтали.",
    },
    "mate_threat": {
        "against": "У соперника есть мат: {by} ходом {mv}.",
        "label": "ход ведёт к мату",
        "tip": "Перед каждым ходом ищите шахи соперника: любой из них может оказаться матом.",
        "tip_missed": "Перед ходом проверьте все шахи: среди них может быть мат.",
    },
    "losing_exchange": {
        "against": "Это невыгодный размен: соперник может забрать {by_pa} на {by_sq}, а вы получите меньше, чем отдаёте.",
        "label": "выгодный размен",
        "tip": "Перед взятием сосчитайте размен до конца: кто и чем возьмёт в ответ.",
        "tip_missed": "Считайте размен до конца: иногда он выгоднее, чем кажется.",
    },
}
GENERIC_TIP = "Перед ходом спросите себя: что соперник сделает в ответ?"


def _mine(sp: dict[str, str]) -> str:
    n = _name(sp)
    return ("ваша " if n.fem else "ваш ") + n.nom


def _mine_acc(sp: dict[str, str]) -> str:
    n = _name(sp)
    return ("вашу " if n.fem else "вашего ") + n.acc


def _removed_defender(f: CoachFacts, r: Reason) -> str:
    mover, held = r.pieces[0], r.pieces[1]
    verb = "ушла" if _name(mover).fem else "ушёл"
    pron = "её" if _name(held).fem else "его"
    return (
        f"{_mine(mover).capitalize()} {verb} с {mover['square']} и больше не защищает "
        f"{_mine_acc(held)} на {held['square']} — соперник может {pron} забрать."
    )


def _reply_attacks(f: CoachFacts, r: Reason) -> str:
    att, hits = r.pieces[0], list(zip(r.squares, r.pieces[1:]))
    who = _name(att).nom + " соперника"
    start = "Соперник может ответить так, что "
    if f.refutation:
        start = f"Если соперник ответит {fig(f.refutation[0])}, "
    else:
        who += f" на {att['square']}"
    for sq, target in hits:
        if target["piece"].upper() != "K":
            tail = " — вам придётся тратить ход на защиту или отход."
            return f"{start}{who} нападёт на {_mine_acc(target)} на {sq}{tail}"
    return f"{start}{who} объявит шах вашему королю, и вам придётся отвечать на него."


def _reply_takes(f: CoachFacts, r: Reason, sq: str, target: dict[str, str]) -> str:
    """The reply attacks a piece that the refutation then takes: no 'spend a move' advice."""
    att = _name(r.pieces[0])
    pron = "её" if _name(target).fem else "его"
    return f"Тогда {att.nom} соперника нападёт на {_mine_acc(target)} на {sq}, и спасти {pron} не удастся."


def _best_attacks(f: CoachFacts, r: Reason) -> str:
    mover = r.pieces[0]
    check = " и объявляет шах" if r.detail == "check" else ""
    for sq, foe in zip(r.squares, r.pieces[1:]):
        if foe["piece"].upper() != "K":
            return f"{_name(mover).nom} нападает на {_name(foe).acc} соперника на {sq}{check}"
    return f"{_name(mover).nom} объявляет шах"


def _best_defends(f: CoachFacts, r: Reason) -> str:
    piece, sq = r.pieces[0], r.squares[0]
    if r.detail == "retreat":
        return f"{_mine(piece)} уходит на {sq} и больше не висит"
    return f"{_mine(piece)} на {sq} больше не висит"


def _center(f: CoachFacts, r: Reason) -> str:
    piece = r.pieces[0]
    if piece["piece"].upper() == "P":
        return "пешка занимает центр"
    return f"{_name(piece).nom} давит на центр"


def _squares_word(k: int) -> str:
    """'одно поле', 'два поля', 'три поля', 'четыре поля' (k is 1 to 4)."""
    return ("одно поле", "два поля", "три поля", "четыре поля")[k - 1]


def _passive_piece(f: CoachFacts, r: Reason) -> str:
    name, k = _name(r.pieces[0]).nom, int(r.detail or "")
    if k == 0:
        return f"После {fig(f.player_move.san)} {name} не бьёт ни одного поля и почти не участвует в игре."
    return f"После {fig(f.player_move.san)} {name} бьёт всего {_squares_word(k)} и почти не участвует в игре."


# Phrases per reason kind. "against" says what the played move broke; "idea" (after
# "Лучше было X:") says what the best move does; "tip" is the lesson for the next time.
REASONS = {
    "removed_defender": {
        "against": _removed_defender,
        "tip": "Прежде чем уводить фигуру, проверьте, кого она защищала.",
    },
    "reply_attacks": {
        "against": _reply_attacks,
        "tip": "Перед ходом представьте ответ соперника: не нападёт ли он на вашу фигуру.",
    },
    "pawn_shield": {
        "against": lambda f, r: (
            f"Пешка с {r.squares[0]} прикрывала вашего короля, а теперь у него меньше защиты."
        ),
        "tip": "Ходы пешек перед королём ослабляют его: делайте их только по необходимости.",
    },
    "opened_line": {
        "against": lambda f, r: (
            f"Ваш ход открыл линию: {_name(r.pieces[0]).nom} соперника на {r.squares[0]} "
            f"теперь нападает на поле {r.squares[1]} рядом с вашим королём."
        ),
        "tip": "Перед ходом проверьте, какую линию к вашему королю он откроет.",
    },
    "lost_castling": {
        "against": lambda f, r: (
            f"После этого хода рокироваться уже нельзя: король остаётся в центре, на {r.squares[0]}."
        ),
        "tip": "Рокируйтесь как можно раньше: король за пешками в безопасности.",
    },
    "queen_early": {
        "against": lambda f, r: "Ферзь вышел слишком рано: сначала нужно развить коней и слонов.",
        "tip": "В дебюте выводите коней и слонов, а ферзя оставьте дома.",
    },
    "same_piece_twice": {
        "against": lambda f, r: (
            "Эта фигура уже ходила, а другие ещё стоят дома: в дебюте развивайте "
            "новую фигуру каждым ходом."
        ),
        "tip": "В дебюте не ходите одной фигурой дважды, пока не развиты остальные.",
    },
    "edge_knight": {
        "against": lambda f, r: (
            f"Конь на {r.squares[0]} стоит у края и бьёт мало полей: в центре он сильнее."
        ),
        "tip": "Конь на краю доски слаб: ставьте коней ближе к центру.",
    },
    "blocks_center_pawn": {
        "against": lambda f, r: (
            f"Фигура на {r.squares[0]} закрывает вашу центральную пешку и мешает ей пойти вперёд."
        ),
        "tip": "Не закрывайте фигурами центральные пешки: им нужен путь вперёд.",
    },
    "doubled_pawns": {
        "against": lambda f, r: (
            f"После {fig(f.player_move.san)} у вас сдвоенные пешки на линии {r.detail}: "
            "они не защищают друг друга и мешают друг другу."
        ),
        "tip": "Без причины не сдваивайте пешки: берите фигурой или в сторону центра.",
    },
    "isolated_pawn": {
        "against": lambda f, r: (
            f"После {fig(f.player_move.san)} пешка на {r.squares[0]} осталась изолированной: "
            "рядом нет пешек, которые её защитят."
        ),
        "tip": "Не оставляйте пешку без соседей по вертикалям: её некому защитить.",
    },
    "passive_piece": {
        "against": _passive_piece,
        "tip": "Ставьте фигуры на открытые линии и диагонали, где они бьют много полей.",
    },
    "best_attacks": {"idea": _best_attacks},
    "best_defends": {"idea": _best_defends},
    "development": {"idea": lambda f, r: f"{_name(r.pieces[0]).nom} вступает в игру"},
    "castles": {"idea": lambda f, r: "король уходит в безопасное место, а ладья включается в игру"},
    "center": {"idea": _center},
}


def _reason_text(f: CoachFacts, r: Reason | None, key: str) -> str | None:
    if r is None or key not in REASONS.get(r.kind, {}):
        return None
    try:
        return REASONS[r.kind][key](f, r)
    except (IndexError, KeyError):
        return None


def _better(f: CoachFacts, best: str | None, pm: str) -> str | None:
    """'Лучше было X' with the idea of the better move when the facts have one."""
    if not best or best == pm:
        return None
    idea = _reason_text(f, f.reasons_missed[0] if f.reasons_missed else None, "idea")
    return f"Лучше было {best}" + (f": {idea}." if idea else ".")


def _why_sentences(f: CoachFacts, best: str | None, pm: str) -> list[str | None]:
    """Reason against the move, the threat, the better move with its idea, a tip. Cut to 4."""
    against = f.reasons_against[0] if f.reasons_against else None
    better = _better(f, best, pm)
    tip = REASONS[against.kind]["tip"] if against and against.kind in REASONS else GENERIC_TIP
    return [_reason_text(f, against, "against"), _threat(f), better, tip]


def fig(san: str) -> str:
    """SAN with figurine pieces: Nxe5+ -> ♘xe5+, e8=Q -> e8=♕."""
    if san and san[0] in FIG:
        san = FIG[san[0]] + san[1:]
    return re.sub(r"=([QRBN])", lambda m: "=" + FIG[m[1]], san)


def _name(sp: dict[str, str]) -> Name:
    return NAMES[sp["piece"].upper()]


def _join(words: list[str]) -> str:
    return " и ".join([", ".join(words[:-1]), words[-1]] if len(words) > 2 else words)


def _items(c: Counter, case: str) -> str:
    """Pieces in the accusative or genitive: 'ладью и пешку', 'двух коней'."""
    out = []
    for letter in sorted(c, key=ORDER.index):
        n, name = c[letter], NAMES[letter]
        if n == 1:
            out.append(getattr(name, case))
        elif n in NUMS and case == "acc":
            out.append(f"{NUMS[n][name.fem]} {name.gen if name.fem else name.pl}")
        else:
            out.append("нескольких фигур" if case == "gen" else "несколько фигур")
    return _join(out)


def _net(m: Material) -> tuple[Counter, Counter]:
    """Lost and gained pieces after trades of equal pieces cancel out."""
    lost, gained = Counter(m.lost), Counter(m.gained)
    common = lost & gained
    return lost - common, gained - common


def _ctx(m: Motif) -> dict[str, str]:
    by, ts = m.by, m.targets
    by_name = _name(by)
    d = {
        "by": f"{by_name.nom} на {by['square']}",
        "by_from": f"{by_name.nom} с {by['square']}",
        "by_sq": by["square"],
        "by_pa": ("вашу " if by_name.fem else "вашего ") + by_name.acc,
        "mv": fig(m.move_san or ""),
        "Then": f"После {fig(m.move_san)}" if m.move_san else "Тогда",
        "ta": _join([_name(t).acc for t in ts]),
        "tg": _join([_name(t).gen for t in ts]),
    }
    if ts:
        n = _name(ts[0])
        d |= {
            "t0": f"{n.nom} на {ts[0]['square']}",
            "t0_dat": f"{n.dat} на {ts[0]['square']}",
            "t0_gen": n.gen,
            "t0_acc": n.acc,
            "Poss": "Ваша" if n.fem else "Ваш",
            "suf": "ась" if n.fem else "ся",
            "a": "а" if n.fem else "",
            "pron": "её" if n.fem else "его",
            "tpron": "ней" if n.fem else "ним",
        }
    if len(ts) > 1:
        d |= {"t1": _name(ts[1]).nom, "t1_gen": _name(ts[1]).gen, "t1_acc": _name(ts[1]).acc}
    return d


def _phrase(m: Motif | None, key: str) -> str | None:
    if m is None:
        return None
    try:
        return MOTIFS[m.kind][key].format(**_ctx(m))
    except (KeyError, IndexError):
        return None


def _tip(m: Motif | None, key: str = "tip", default: str | None = None) -> str:
    kind = m.kind if m else default
    return MOTIFS[kind][key] if kind else GENERIC_TIP


def _first(motifs: list[Motif], *kinds: str) -> Motif | None:
    return next((m for m in motifs if not kinds or m.kind in kinds), None)


def _mate_text(f: CoachFacts, cls: str, pm: str, ref0: str | None) -> list[str]:
    n = f.allowed_mate_in
    start = f": {ref0}" if n == 1 else f", начиная с {ref0}"
    first = f"{cls}: у соперника мат в {n}" + (start if ref0 else "") + "."
    motif = _first(f.motifs_against, "back_rank")
    # The first sentence already names the mating move: do not name it again as a threat.
    same = f.threat and f.refutation and f.threat.move_san == f.refutation[0]
    return [
        first,
        _phrase(motif, "against") or (None if same else _threat(f)),
        _tip(motif, default="mate_threat"),
    ]


def _threat(f: CoachFacts) -> str | None:
    if not f.threat:
        return None
    what = "угрозу мата" if f.threat.mate_in else "угрозу соперника"
    return f"Вы не заметили {what}: {fig(f.threat.move_san)}."


def _loss_note(f: CoachFacts, lost: Counter, gained: Counter) -> str | None:
    """The actual loss, named only when it is big (3 points or more)."""
    if f.material.change > -3 or not lost:
        return None
    what = f"{_items(lost, 'acc')} за {_items(gained, 'acc')}" if gained else _items(lost, "acc")
    return f"Кроме того, вы можете потерять {what}."


def _names_win(f: CoachFacts) -> bool:
    """The best move wins more than the played one, by a motif or by a plain capture."""
    if f.missed_material.change <= max(f.material.change, 0):
        return False
    if f.motifs_missed:
        return True
    board = chess.Board(f.fen_before)
    return chess.Move.from_uci(f.best_move.uci) in board.generate_legal_captures()


def _taken_reason(f: CoachFacts) -> tuple[Reason, str] | None:
    """Why-sentence for a material loss: only when the refutation takes a named piece or square."""
    line = _refutation_moves(f)
    if line is None:
        return None
    after = chess.Board(f.fen_before)
    after.push_uci(f.player_move.uci)
    for r in f.reasons_against:
        if r.kind not in ("removed_defender", "reply_attacks") or r.detail == "check":
            continue
        squares = r.squares[:1] if r.kind == "removed_defender" else r.squares
        pieces = r.pieces[1:] if r.kind == "reply_attacks" else r.pieces[1:2]
        hit = [(s, p) for s, p in zip(squares, pieces) if p["piece"].upper() != "K"]
        for s, p in hit:
            # The opponent's plies are 0, 2, 4 of the refutation; _hits also checks the gain.
            if _hits(after, chess.parse_square(s), line):
                if r.kind == "reply_attacks":  # name the piece that is taken, not the first one
                    return r, _reply_takes(f, r, s, p)
                text = _reason_text(f, r, "against")
                return (r, text) if text else None
    return None


def _refutation_moves(f: CoachFacts) -> list[chess.Move] | None:
    """The refutation as moves, or None when it does not fit the position."""
    b = chess.Board(f.fen_before)
    try:
        b.push_uci(f.player_move.uci)
        moves = []
        for san in f.refutation[:3]:
            move = b.parse_san(san)
            moves.append(move)
            b.push(move)
    except ValueError:
        return None
    return moves


def explain(f: CoachFacts) -> str:
    cls = CLASS_WORD[f.classification]
    pm = fig(f.player_move.san)
    best = fig(f.best_move.san) if f.best_move else None
    ref0 = fig(f.refutation[0]) if f.refutation else None
    better = _better(f, best, pm)
    lost, gained = _net(f.material)
    m_lost, m_gained = _net(f.missed_material)
    bad = f.classification in ("inaccuracy", "mistake", "blunder")
    s: list[str | None]
    over = getattr(f, "game_over", None)
    lead = missed_leads(f.material.change, f.missed_material.change, f.missed_mate_in)

    if over == "checkmate":
        s = [f"{CLASS_WORD['best']}: {pm} — мат!"]
    elif over == "stalemate":
        s = ["Пат — ничья! Королю соперника некуда ходить, а шаха нет.", better]
    elif over == "draw":
        s = [f"{cls}: {pm} ведёт к ничьей.", better]
    elif f.allowed_mate_in:
        s = [*_mate_text(f, cls, pm, ref0), better]
    elif bad and lead and f.missed_mate_in:
        n = f.missed_mate_in
        motif = _first(f.motifs_missed, "back_rank")
        label = _phrase(motif, "label")
        s = [f"{cls}: вы пропустили мат в {n}."]
        if best:
            start = "Здесь был мат в 1" if n == 1 else f"Мат в {n} начинался с"
            sep = ": " if n == 1 else " "
            s.append(f"{start}{sep}{best}" + (f" — {label}" if label else "") + ".")
        s += [_loss_note(f, lost, gained), _tip(motif, "tip_missed", "mate_threat")]
    elif bad and lead and m_gained and _names_win(f):
        motif = f.motifs_missed[0] if f.motifs_missed else None  # no motif: still name the win
        mv = fig(motif.move_san) if motif and motif.move_san else best
        won = _items(m_gained, "acc") + (f" за {_items(m_lost, 'acc')}" if m_lost else "")
        s = [f"{cls}: ход {pm} упустил сильную возможность."]
        if mv:
            label = _phrase(motif, "label")
            s.append(f"Можно было выиграть {won}: {mv}" + (f" — {label}" if label else "") + ".")
        s += [_loss_note(f, lost, gained), _tip(motif, "tip_missed")]
    elif bad and f.material.change < 0 and lost:
        what = f"вы теряете {_items(lost, 'acc')}"
        if gained:
            what = f"соперник выигрывает {_items(lost, 'acc')} за {_items(gained, 'acc')}"
        motif = _first(f.motifs_against)
        # The reply comes from Stockfish; the real opponent may play another move.
        if ref0:
            first = f"{cls}: соперник может ответить {ref0}, и тогда {what.replace('соперник ', 'он ')}."
        else:
            first = (
                f"{cls}: "
                + what.replace("вы теряете", "вы можете потерять").replace(
                    "соперник выигрывает", "соперник может выиграть"
                )
                + "."
            )
        found = _taken_reason(f)
        if found and motif and motif.kind == "fork" and found[0].kind == "reply_attacks":
            found = None  # the fork sentence already says what the reply attacks
        if found:  # the reason is the lesson here: its own tip goes last and is cut first
            r, why = found
            s = [
                first,
                why,
                _phrase(motif, "against") or _threat(f),
                better,
                REASONS[r.kind]["tip"],
            ]
        else:
            s = [first, _phrase(motif, "against") or _threat(f), _tip(motif), better]
    elif f.classification == "inaccuracy":
        s = [f"{cls}: ход {pm} немного слабее лучшего.", *_why_sentences(f, best, pm)]
    elif bad:
        s = [f"{cls}: ход {pm} заметно ухудшает вашу позицию.", *_why_sentences(f, best, pm)]
    elif f.classification == "good":
        s = [f"{cls}: {pm}.", f"Но сильнее было {best}." if better else None]
    elif pm.endswith("#"):
        s = [f"{cls}: {pm} — мат!"]
    elif f.material.change > 0 and gained:
        won = _items(gained, "acc") + (f" за {_items(lost, 'acc')}" if lost else "")
        s = [f"{cls}: {pm} — лучший ход, он выигрывает {won}."]
    else:
        s = [f"{cls}: {pm} — лучший ход в этой позиции."]
    return " ".join([x for x in s if x][:4])
