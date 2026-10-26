import json
import re
from pathlib import Path

import chess
import pytest

from app.coach.facts import build_facts
from app.coach.motifs import Motif
from app.coach.schema import CoachFacts
from app.coach.templates import REASONS, explain, fig
from app.config import settings
from app.engines.pool import EnginePool

CASES = json.loads((Path(__file__).parent / "fixtures" / "facts.json").read_text(encoding="utf-8"))
SQ = r"[a-h][1-8]"


def sp(square, piece):
    return {"square": square, "piece": piece}


SAMPLES = {
    "hanging_piece": Motif("hanging_piece", sp("f3", "N"), [sp("h4", "q")], None),
    "fork": Motif("fork", sp("c7", "N"), [sp("e8", "k"), sp("a8", "r")], "Nc7+"),
    "pin": Motif("pin", sp("b5", "B"), [sp("c6", "n"), sp("e8", "k")], "Bb5"),
    "skewer": Motif("skewer", sp("a1", "R"), [sp("a5", "q"), sp("a8", "r")], "Ra1"),
    "discovered_attack": Motif("discovered_attack", sp("d1", "R"), [sp("d8", "q")], "Nc7"),
    "back_rank": Motif("back_rank", sp("a8", "R"), [sp("g8", "k")], "Ra8#"),
    "mate_threat": Motif("mate_threat", sp("h5", "Q"), [sp("f7", "k")], "Qxf7#"),
    "losing_exchange": Motif("losing_exchange", sp("d5", "Q"), [sp("d5", "p")], "Qxd5", -8),
}


def mk(**kw):
    base = {
        "fen_before": chess.STARTING_FEN,
        "side": "white",
        "player_move": {"san": "Nf3", "uci": "g1f3"},
        "classification": "blunder",
        "win_chance_drop": 40.0,
        "eval_before": {"cp": 20, "mate": None},
        "eval_after": {"cp": -400, "mate": None},
        "best_move": {"san": "Nc3", "uci": "b1c3"},
        "best_line": ["Nc3", "e5"],
        "refutation": ["Nxh4"],
        "material": {"change": 0, "lost": [], "gained": []},
        "missed_material": {"change": 0, "lost": [], "gained": []},
        "motifs_against": [],
        "motifs_missed": [],
        "allowed_mate_in": None,
        "missed_mate_in": None,
        "threat": None,
        "lesson": None,
    }
    return CoachFacts.model_validate(base | kw)


def loss(lost, gained=(), change=-9, **kw):
    mat = {"change": change, "lost": list(lost), "gained": list(gained)}
    return mk(material=mat, **kw)


def won(gained, lost=(), change=5, **kw):
    mat = {"change": change, "lost": list(lost), "gained": list(gained)}
    return mk(missed_material=mat, **kw)


def check(text, f):
    assert text.strip() and re.search("[а-яА-Я]", text), text
    n = len(re.split(r"(?<=[.!?])\s+", text.strip()))
    assert 1 <= n <= 4, text
    assert not re.search(r"(?<![A-Za-z])[KQRBN][a-h]?[1-8]?x?[a-h][1-8]", text), text
    assert not re.search(r"=[KQRBN]", text), text
    bare = re.sub(r"(?i)мат в \d+", "мат", re.sub(SQ, "", text))
    assert not re.search(r"\d", bare), text
    assert not re.search(r"\bcp\b|сантипешк|%", text), text
    allowed = set(re.findall(SQ, f.model_dump_json(exclude={"fen_before"})))
    assert set(re.findall(SQ, text)) <= allowed, text


def rs(kind, squares, pieces, detail=None):
    return {"kind": kind, "squares": squares, "pieces": pieces, "detail": detail}


AGAINST = {
    "removed_defender": (
        rs("removed_defender", ["e5"], [sp("f3", "N"), sp("e5", "P")]),
        "Ваш конь ушёл с f3 и больше не защищает вашу пешку на e5 — соперник может её забрать.",
    ),
    "reply_attacks": (
        rs("reply_attacks", ["f6"], [sp("e5", "p"), sp("f6", "N")]),
        "нападёт на вашего коня на f6",
    ),
    "reply_check": (rs("reply_attacks", ["e1"], [sp("d8", "q"), sp("e1", "K")], "check"), "шах"),
    "pawn_shield": (rs("pawn_shield", ["h2"], [sp("h2", "P")]), "Пешка с h2 прикрывала"),
    "opened_line": (
        rs("opened_line", ["b5", "e8"], [sp("b5", "b")]),
        "слон соперника на b5 теперь нападает на поле e8",
    ),
    "lost_castling": (rs("lost_castling", ["e2"], [sp("e2", "K")]), "рокироваться уже нельзя"),
    "queen_early": (rs("queen_early", ["h5"], [sp("d1", "Q")]), "Ферзь вышел слишком рано"),
    "same_piece_twice": (rs("same_piece_twice", ["g5"], [sp("f3", "N")]), "уже ходила"),
    "edge_knight": (rs("edge_knight", ["a3"], [sp("b1", "N")]), "Конь на a3 стоит у края"),
    "blocks_center_pawn": (
        rs("blocks_center_pawn", ["d3"], [sp("f1", "B")]),
        "Фигура на d3 закрывает",
    ),
    "doubled_pawns": (
        rs("doubled_pawns", ["c2", "c3"], [sp("c2", "P"), sp("c3", "P")], "c"),
        "После ♘f3 у вас сдвоенные пешки на линии c: они не защищают друг друга",
    ),
    "isolated_pawn": (
        rs("isolated_pawn", ["a2"], [sp("a2", "P")]),
        "После ♘f3 пешка на a2 осталась изолированной: рядом нет пешек",
    ),
}
IDEAS = {
    "best_attacks": (
        rs("best_attacks", ["c6"], [sp("e5", "P"), sp("c6", "n")]),
        "Лучше было e5: пешка нападает на коня соперника на c6.",
    ),
    "best_check": (rs("best_attacks", ["e8"], [sp("b5", "B"), sp("e8", "k")], "check"), "шах"),
    "best_defends": (
        rs("best_defends", ["f3"], [sp("f3", "N")]),
        "ваш конь на f3 больше не висит",
    ),
    "best_retreat": (
        rs("best_defends", ["g1"], [sp("g1", "N")], "retreat"),
        "ваш конь уходит на g1 и больше не висит",
    ),
    "development": (rs("development", ["c3"], [sp("c3", "N")]), "конь вступает в игру"),
    "castles": (rs("castles", ["g1"], [sp("g1", "K")], "kingside"), "король уходит в безопасное"),
    "center_pawn": (rs("center", ["e4"], [sp("e4", "P")]), "пешка занимает центр"),
    "center_piece": (rs("center", ["c3"], [sp("c3", "N")]), "конь давит на центр"),
}


def cases():
    out = {}
    for name, (r, expect) in AGAINST.items():
        out[f"reason-{name}"] = (
            mk(classification="mistake", refutation=["e5"], reasons_against=[r]),
            expect,
        )
    for name, (r, expect) in IDEAS.items():
        out[f"idea-{name}"] = (
            mk(
                classification="inaccuracy",
                best_move={"san": "e5", "uci": "e4e5"},
                reasons_missed=[r],
            ),
            expect,
        )
    for k, word in enumerate(("ни одного поля", "всего одно поле", "всего два поля"), start=0):
        out[f"passive-{k}"] = (
            mk(
                classification="inaccuracy",
                reasons_against=[rs("passive_piece", ["e2"], [sp("e2", "B")], str(k))],
            ),
            f"После ♘f3 слон {'не бьёт ' if k == 0 else 'бьёт '}{word} и почти не участвует",
        )
    for k, word in ((3, "три поля"), (4, "четыре поля")):
        out[f"passive-{k}"] = (
            mk(
                classification="inaccuracy",
                reasons_against=[rs("passive_piece", ["a1"], [sp("a1", "R")], str(k))],
            ),
            f"ладья бьёт всего {word} и почти не участвует",
        )
    for kind, m in SAMPLES.items():
        out[f"against-{kind}"] = (loss(["Q"], motifs_against=[m]), "ферзя")
        out[f"missed-{kind}"] = (
            won(["R"], classification="mistake", motifs_missed=[m]),
            "ладью",
        )
    hang, fork, pin = SAMPLES["hanging_piece"], SAMPLES["fork"], SAMPLES["pin"]
    thr = {"move_san": "Ng5", "mate_in": None, "material": 3}
    out |= {
        "hanging-text": (
            loss(["Q"], motifs_against=[hang]),
            "Ваш ферзь на h4 оказался под боем: конь с f3 может забрать его.",
        ),
        "fork-text": (
            loss(["R"], motifs_against=[fork]),
            "После ♘c7+ будет вилка: конь на c7 нападает сразу на короля и ладью.",
        ),
        "pin-text": (
            loss(["N"], motifs_against=[pin]),
            "слон на b5 не даёт коню на c6 уйти — за ним король.",
        ),
        "missed-fork-text": (
            won(["R"], classification="mistake", motifs_missed=[fork]),
            "Можно было выиграть ладью: ♘c7+ — вилка короля и ладьи.",
        ),
        "mate-1": (mk(allowed_mate_in=1, refutation=["Qxh7#"]), "у соперника мат в 1: ♕xh7#."),
        "mate-2": (mk(allowed_mate_in=2, refutation=["Qh5+", "g6"]), "мат в 2, начиная с ♕h5+"),
        "mate-back-rank": (
            mk(allowed_mate_in=1, refutation=["Ra8#"], motifs_against=[SAMPLES["back_rank"]]),
            "последней горизонтали",
        ),
        "mate-no-refutation": (mk(allowed_mate_in=3, refutation=[]), "мат в 3"),
        "mate-threat": (
            mk(
                allowed_mate_in=1,
                refutation=["Qxf7#"],
                threat={"move_san": "Qxf7#", "mate_in": 1, "material": None},
            ),
            "мат в 1: ♕xf7#. Перед каждым ходом ищите шахи",
        ),
        "threat": (loss(["N"], threat=thr), "Вы не заметили угрозу соперника: ♘g5."),
        "loss-no-motif": (
            loss(["N"], change=-3),
            "соперник может ответить ♘xh4, и тогда вы теряете коня.",
        ),
        "loss-two-pawns": (loss(["P", "P"], change=-2), "вы теряете две пешки"),
        "loss-two-knights": (loss(["N", "N"], change=-6), "двух коней"),
        "loss-trade-cancel": (loss(["N", "P"], ["N"], change=-1), "вы теряете пешку"),
        "loss-trade-rook-bishop": (
            loss(["R"], ["B"], change=-2),
            "и тогда он выигрывает ладью за слона",
        ),
        "loss-no-best": (
            loss(["B"], change=-3, best_move=None, refutation=[]),
            "Зевок: вы можете потерять слона.",
        ),
        "loss-inaccuracy": (loss(["P"], change=-1, classification="inaccuracy"), "Неточность"),
        "missed-mate-1": (
            mk(
                missed_mate_in=1,
                classification="mistake",
                best_move={"san": "Ra8#", "uci": "a1a8"},
                motifs_missed=[SAMPLES["back_rank"]],
            ),
            "Здесь был мат в 1: ♖a8# — мат по последней горизонтали.",
        ),
        "missed-mate-3": (
            mk(missed_mate_in=3, best_move={"san": "Qh5+", "uci": "d1h5"}),
            "Мат в 3 начинался с ♕h5+",
        ),
        "missed-mate-no-best": (mk(missed_mate_in=2, best_move=None), "пропустили мат в 2"),
        "inaccuracy": (mk(classification="inaccuracy"), "Неточность"),
        "inaccuracy-no-best": (mk(classification="inaccuracy", best_move=None), "Неточность"),
        "mistake-generic": (mk(classification="mistake"), "Ошибка"),
        "blunder-generic": (mk(), "Зевок"),
        "good": (mk(classification="good"), "Хороший ход: ♘f3. Но сильнее было ♘c3."),
        "good-no-best": (mk(classification="good", best_move=None), "Хороший ход"),
        "best": (mk(classification="best", best_move=None), "Отличный ход"),
        "best-mate": (
            mk(classification="best", player_move={"san": "Qxf7#", "uci": "h5f7"}),
            "мат!",
        ),
        "best-wins": (
            mk(
                classification="best",
                best_move=None,
                material={"change": 9, "lost": [], "gained": ["Q"]},
            ),
            "выигрывает ферзя",
        ),
        "promotion": (
            loss(["P"], change=-1, player_move={"san": "e8=Q+", "uci": "e7e8q"}),
            "Зевок: соперник может ответить",
        ),
    }
    return out


CASE_MAP = cases()


@pytest.mark.parametrize("name", list(CASE_MAP))
def test_template(name):
    f, expect = CASE_MAP[name]
    text = explain(f)
    check(text, f)
    assert expect in text, text


def test_reason_sentence_goes_before_better_move_and_tip():
    r, _ = AGAINST["queen_early"]
    f = mk(
        classification="inaccuracy", reasons_against=[r], reasons_missed=[IDEAS["development"][0]]
    )
    text = explain(f)
    check(text, f)
    assert text.index("Ферзь вышел") < text.index("Лучше было ♘c3: конь вступает в игру.")
    assert text.endswith(REASONS["queen_early"]["tip"]), text


def test_material_loss_text_keeps_priority_over_reasons():
    r, _ = AGAINST["queen_early"]
    f = loss(["Q"], motifs_against=[SAMPLES["hanging_piece"]], reasons_against=[r])
    assert "вы теряете ферзя" in explain(f) and "Ферзь вышел" not in explain(f)


# The refutation is replayed on the board, so these tests need a legal line.
# White Nf3 guards the pawn e5; after Nf3-g1 the bishop g7 takes it for nothing.
DEFENDER_FEN = "4k3/6b1/8/4P3/8/5N2/8/4K3 w - - 0 1"
DEFENDER_MOVE = {"san": "Ng1", "uci": "f3g1"}
# White rook h8 is attacked by the knight f7 and the king moves away.
ROOK_FEN = "7R/k4n2/8/8/8/8/8/4K3 w - - 0 1"
ROOK_MOVE = {"san": "Ke2", "uci": "e1e2"}


def test_material_loss_names_taken_defended_piece():
    r, _ = AGAINST["removed_defender"]
    f = loss(
        ["P"],
        change=-1,
        fen_before=DEFENDER_FEN,
        player_move=DEFENDER_MOVE,
        refutation=["Bxe5"],
        reasons_against=[r],
    )
    text = explain(f)
    check(text, f)
    assert "больше не защищает вашу пешку на e5" in text, text
    assert text.index("вы теряете") < text.index("больше не защищает")
    assert explain(f.model_copy(update={"reasons_against": []})) != text


def test_material_loss_skips_reason_the_refutation_does_not_take():
    r, _ = AGAINST["removed_defender"]
    f = loss(
        ["P"],
        change=-1,
        fen_before=DEFENDER_FEN,
        player_move=DEFENDER_MOVE,
        refutation=["Bf6"],
        reasons_against=[r],
    )
    assert "больше не защищает" not in explain(f)


def test_missed_fork_outranks_small_loss():
    f = won(
        ["R"],
        classification="blunder",
        motifs_missed=[SAMPLES["fork"]],
        material={"change": -1, "lost": ["P"], "gained": []},
        motifs_against=[SAMPLES["hanging_piece"]],
    )
    text = explain(f)
    check(text, f)
    assert "Можно было выиграть ладью: ♘c7+" in text, text
    assert "теряете" not in text, text


def test_big_loss_is_named_after_missed_chance():
    f = won(
        ["R"],
        classification="blunder",
        motifs_missed=[SAMPLES["fork"]],
        material={"change": -3, "lost": ["N"], "gained": []},
    )
    text = explain(f)
    check(text, f)
    assert "Можно было выиграть ладью" in text and "Кроме того, вы можете потерять коня." in text, (
        text
    )


def test_bigger_loss_outranks_small_missed_chance():
    f = loss(["Q"], classification="blunder", motifs_missed=[SAMPLES["fork"]])
    f = f.model_copy(update={"missed_material": won(["P"], change=1).missed_material})
    assert "вы теряете ферзя" in explain(f)


class OverFacts(CoachFacts):
    game_over: str | None = None


@pytest.mark.parametrize(
    ("over", "expect"),
    [
        ("stalemate", "Пат — ничья! Королю соперника некуда ходить, а шаха нет. Лучше было ♘c3."),
        ("checkmate", "Отличный ход: ♘f3 — мат!"),
        ("draw", "ведёт к ничьей"),
    ],
)
def test_game_over(over, expect):
    f = OverFacts.model_validate(mk().model_dump() | {"game_over": over})
    text = explain(f)
    check(text, f)
    assert expect in text, text


def test_fig():
    assert fig("Nxe5+") == "♘xe5+"
    assert fig("e8=Q+") == "e8=♕+"
    assert fig("exd5") == "exd5"
    assert fig("O-O") == "O-O"


@pytest.fixture(scope="module")
def pool():
    p = EnginePool(settings.engines_dir, 1, 2, 64)
    yield p
    p.close()


@pytest.mark.engine
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_real_facts(pool, case):
    f = build_facts(pool, chess.Board(case["fen"]), chess.Move.from_uci(case["move"]))
    text = explain(f)
    print(f"\n[{case['id']}] {text}")
    check(text, f)


def test_material_loss_names_the_taken_piece_without_repeating_the_reply():
    r = rs("reply_attacks", ["d8", "h8"], [sp("f7", "N"), sp("d8", "q"), sp("h8", "r")])
    f = loss(
        ["R"],
        change=-5,
        fen_before=ROOK_FEN,
        player_move=ROOK_MOVE,
        refutation=["Nxh8"],
        reasons_against=[r],
    )
    text = explain(f)
    check(text, f)
    assert text.count("может ответить ♘xh8") == 1 and "Если соперник ответит" not in text, text
    assert "нападёт на вашу ладью на h8" in text, text
    assert "тратить ход" not in text, text
    assert text.endswith(REASONS["reply_attacks"]["tip"]), text


def test_material_loss_skips_the_reply_sentence_after_a_fork():
    r = rs("reply_attacks", ["d8", "h8"], [sp("f7", "N"), sp("d8", "q"), sp("h8", "r")])
    f = loss(
        ["R"],
        change=-5,
        fen_before=ROOK_FEN,
        player_move=ROOK_MOVE,
        refutation=["Nxh8"],
        reasons_against=[r],
        motifs_against=[Motif("fork", sp("f7", "N"), [sp("d8", "q"), sp("h8", "r")], "Nxf7")],
    )
    text = explain(f)
    check(text, f)
    assert "будет вилка" in text and "нападёт на вашу" not in text, text


def test_mate_move_is_named_once_when_it_is_also_the_missed_threat():
    f = mk(
        classification="blunder",
        allowed_mate_in=1,
        refutation=["Qxf7#"],
        threat={"move_san": "Qxf7#", "mate_in": 1, "material": None},
    )
    text = explain(f)
    assert text.count("♕xf7#") == 1, text
    assert "Вы не заметили" not in text


@pytest.mark.engine
def test_scholars_mate_names_the_mating_move_once(pool):
    b = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3")
    text = explain(build_facts(pool, b, b.parse_san("Nf6")))
    assert "мат в 1" in text and text.count("♕xf7#") == 1, text


# Visible text of the second-round review fixes.
ITALIAN_B = "r1bqk1nr/pppp1ppp/2n5/2b1p1N1/2B1P3/8/PPPP1PPP/RNBQK2R b KQkq - 5 4"
NH6 = {"san": "Nh6", "uci": "g8h6"}
QXG5 = {"san": "Qxg5", "uci": "d8g5"}


def test_best_defends_says_the_piece_no_longer_hangs():
    # Case 20: after d5 the pawn f7 is still attacked, but it no longer hangs
    for name in ("best_defends", "best_retreat"):
        r, expect = IDEAS[name]
        text = explain(mk(classification="inaccuracy", best_move=QXG5, reasons_missed=[r]))
        assert expect in text and "под боем" not in text, text


def test_missed_win_without_a_motif_needs_a_capture_as_the_best_move():
    miss = {"change": 3, "lost": [], "gained": ["N"]}
    f = mk(
        fen_before=ITALIAN_B, side="black", player_move=NH6, best_move=QXG5, missed_material=miss
    )
    text = explain(f)
    check(text, f)
    assert "Можно было выиграть коня: ♕xg5" in text, text  # a capture: the win is named
    # Case 23: f6 instead of Nf6 (not a capture): no invented win
    quiet = {"change": 1, "lost": [], "gained": ["P"]}
    f = mk(
        fen_before="r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3",
        side="black",
        classification="mistake",
        player_move={"san": "f6", "uci": "f7f6"},
        best_move={"san": "Nf6", "uci": "g8f6"},
        missed_material=quiet,
        reasons_missed=[IDEAS["development"][0]],
    )
    text = explain(f)
    assert "выиграть" not in text and "Лучше было ♘f6: конь вступает в игру." in text, text


def test_missed_win_is_not_named_when_the_played_move_wins_the_same():
    # Case g1.7: bxc3 takes a pawn, and so does the best move Nxc3
    f = mk(
        fen_before="r1bqk1nr/pppp1pbp/2n3p1/8/2B1P3/2p2N2/PP3PPP/RNBQ1RK1 w kq - 0 7",
        classification="inaccuracy",
        player_move={"san": "bxc3", "uci": "b2c3"},
        best_move={"san": "Nxc3", "uci": "b1c3"},
        material={"change": 1, "lost": [], "gained": ["P"]},
        missed_material={"change": 1, "lost": [], "gained": ["P"]},
    )
    assert "упустил" not in explain(f)


def test_taken_reason_ignores_an_even_trade():
    # The knight e5 is attacked, but ...Nxe5 dxe5 is an even trade: no "cannot be saved" text
    r = rs("reply_attacks", ["e5"], [sp("c6", "n"), sp("e5", "N")])
    f = loss(
        ["N"],
        change=-3,
        fen_before="4k3/8/2n5/4N3/3P4/8/8/4K3 w - - 0 1",
        player_move={"san": "Ke2", "uci": "e1e2"},
        refutation=["Nxe5", "dxe5"],
        reasons_against=[r],
    )
    assert "спасти" not in explain(f)
    lone = "4k3/8/2n5/4N3/8/8/8/4K3 w - - 0 1"
    real = f.model_copy(update={"fen_before": lone, "refutation": ["Nxe5"]})
    assert "и спасти его не удастся" in explain(real)  # nothing recaptures: the knight is lost


def test_passive_piece_has_a_tip_and_is_not_shown_with_a_material_loss():
    r = rs("passive_piece", ["e2"], [sp("e2", "B")], "3")
    f = mk(classification="inaccuracy", reasons_against=[r])
    text = explain(f)
    check(text, f)
    assert text.endswith(REASONS["passive_piece"]["tip"]), text
    lost = loss(["N"], change=-3, reasons_against=[r])
    assert "почти не участвует" not in explain(lost)


@pytest.mark.engine
def test_passive_piece_reason_for_a_boxed_in_bishop(pool):
    # Be2 attacks 4 squares (d1, f1, d3, f3); the best move Nxe5 opens a knight to 8 squares
    b = chess.Board("rnbqk2r/ppppbppp/5n2/4p3/4P3/3P1N2/PPP2PPP/RNBQKB1R w KQkq - 0 5")
    f = build_facts(pool, b, b.parse_san("Be2"))
    assert f.reasons_against and f.reasons_against[0].kind == "passive_piece", f.reasons_against
    assert f.reasons_against[0].detail == "4"  # the text may lead with the missed pawn instead


@pytest.mark.engine
def test_passive_piece_reason_is_not_given_for_a_blunder(pool):
    b = chess.Board()
    for san in ["e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6"]:
        b.push_san(san)
    f = build_facts(pool, b, b.parse_san("Rg1"))  # a blunder; the rook on g1 attacks 3 squares
    assert f.classification == "blunder"
    assert all(r.kind != "passive_piece" for r in f.reasons_against)


def test_refutation_is_a_possibility_not_a_fact():
    # The reply is the engine's strongest move; the human-like opponent may play another one.
    for f in (loss(["N"], change=-3), loss(["P"], change=-1, classification="mistake")):
        text = explain(f)
        assert "может ответить ♘xh4" in text and "после ответа" not in text.lower(), text
    text = explain(loss(["R"], ["B"], change=-2))
    assert "может ответить ♘xh4, и тогда он выигрывает ладью за слона" in text, text
    # A forced mate stays a fact.
    mate = explain(mk(allowed_mate_in=1, refutation=["Qxf7#"]))
    assert "у соперника мат в 1: ♕xf7#" in mate and "может" not in mate.split(".")[0], mate
