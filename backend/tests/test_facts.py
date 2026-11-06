import json
from pathlib import Path

import chess
import pytest
from fastapi.testclient import TestClient

from app.coach.facts import (
    _reasons_against,
    _reasons_missed,
    build_facts,
    cut_line,
    line_material,
    settled_material,
    threat_missed,
)
from app.coach.schema import Threat
from app.coach.templates import explain
from app.config import settings
from app.engines.pool import EnginePool
from app.main import create_app

CASES = json.loads((Path(__file__).parent / "fixtures" / "facts.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pool():
    p = EnginePool(settings.engines_dir, 1, 2, 64)
    yield p
    p.close()


def kinds(motifs):
    return [x.kind for x in motifs]


@pytest.mark.engine
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_facts(pool, case):
    board = chess.Board(case["fen"])
    assert board.is_valid()
    f = build_facts(pool, board, chess.Move.from_uci(case["move"]))
    e = case["expect"]
    if "classification_in" in e:
        assert f.classification in e["classification_in"], f.model_dump()
    if "lost_has" in e:
        assert e["lost_has"] in f.material.lost
    if "against_has" in e:
        assert e["against_has"] in kinds(f.motifs_against)
    if "missed_has" in e:
        assert e["missed_has"] in kinds(f.motifs_missed)
    if "reasons_against_has" in e:
        assert e["reasons_against_has"] in kinds(f.reasons_against), f.reasons_against
    if "reasons_missed_has" in e:
        assert e["reasons_missed_has"] in kinds(f.reasons_missed), f.reasons_missed
    assert len(f.reasons_against) <= 3 and len(f.reasons_missed) <= 3
    if f.classification in ("best", "good"):
        assert not f.reasons_against and not f.reasons_missed
    json.loads(f.model_dump_json())["reasons_against"]
    if e.get("no_missed_motifs"):
        assert f.motifs_missed == []
    if e.get("no_loss"):
        assert f.material.lost == [] or f.material.change >= 0
    if "best_move" in e:
        assert f.best_move.uci == e["best_move"]
    if "allowed_mate_in" in e:
        assert f.allowed_mate_in == e["allowed_mate_in"]
    if "missed_mate_in" in e:
        assert f.missed_mate_in == e["missed_mate_in"]
    if "refutation" in e:
        assert f.refutation == e["refutation"]
    if "eval_after_mate" in e:
        assert f.eval_after.mate == e["eval_after_mate"]
    if "eval_after_cp" in e:
        assert f.eval_after.cp == e["eval_after_cp"]
    if "lesson" in e:
        assert (f.lesson.slug if f.lesson else None) == e["lesson"]
    if "game_over" in e:
        assert f.game_over == e["game_over"]
    if "material_lost" in e:
        assert f.material.lost == e["material_lost"], f.material
    if "material_change" in e:
        assert f.material.change == e["material_change"], f.material
    if "material_change_max" in e:
        assert f.material.change <= e["material_change_max"], f.material
    if "gained_not_has" in e:
        assert e["gained_not_has"] not in f.material.gained, f.material
    if "no_against" in e:
        assert not set(e["no_against"]) & set(kinds(f.motifs_against))
    if e.get("lesson_not_null"):
        assert f.lesson is not None
    if "lesson_not" in e:
        assert (f.lesson.slug if f.lesson else None) != e["lesson_not"]
    if "threat" in e:
        assert (f.threat is not None) == e["threat"]
    if "threat_move" in e:
        assert f.threat.move_san == e["threat_move"]
    if "threat_mate_in" in e:
        assert f.threat.mate_in == e["threat_mate_in"]


def test_cut_line_keeps_the_recapture():
    b = chess.Board()
    line = ["e2e4", "d7d5", "e4d5", "d8d5", "g1f3", "d5a5", "a2a3"]
    assert cut_line(b, line) == line[:5]  # stops at the quiet Nf3, after the recapture
    assert cut_line(b, line[:3]) == line[:3]


def test_material_promotion_then_capture_costs_a_pawn():
    b = chess.Board("1r2k3/P7/8/8/8/8/8/4K3 w - - 0 1")
    m = line_material(b, ["a7a8q", "b8a8"], chess.WHITE)
    assert (m.change, m.lost, m.gained) == (-1, ["P"], [])


def test_material_opponent_promotes():
    b = chess.Board("4k3/8/8/8/8/8/p7/7K w - - 0 1")
    m = line_material(b, ["h1g1", "a2a1q"], chess.WHITE)
    assert m.change == -8


def test_material_even_trade_cancels():
    b = chess.Board("r1bqkbnr/pppp1ppp/2n5/8/3NP3/8/PPP2PPP/RNBQKB1R b KQkq - 0 1")
    m = line_material(b, ["c6d4", "d1d4"], chess.BLACK)
    assert (m.change, m.lost, m.gained) == (0, [], [])


@pytest.mark.engine
def test_illegal_move_is_value_error(pool):
    with pytest.raises(ValueError):
        build_facts(pool, chess.Board(), chess.Move.from_uci("e2e5"))


@pytest.fixture
def client():
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.mark.engine
def test_route_returns_facts_and_template_explanation(client):
    case = CASES[0]
    r = client.post("/api/coach/move", json={"fen": case["fen"], "move": case["move"]})
    assert r.status_code == 200
    body = r.json()
    assert body["explanation"]["source"] == "template"
    assert body["explanation"]["text"].strip()
    assert body["facts"]["classification"] == "blunder"


@pytest.mark.parametrize(
    "body",
    [
        {"fen": "not a fen", "move": "e2e4"},
        {"move": "e2e4"},
        {"fen": chess.STARTING_FEN, "move": "e2e5"},
        {"fen": chess.STARTING_FEN, "move": "zz"},
    ],
)
def test_route_invalid_input_is_422(client, body):
    assert client.post("/api/coach/move", json=body).status_code == 422


def test_cut_line_goes_on_after_a_check():
    line = ["e2e4", "e7e5", "f2f3", "d8h4", "g2g3", "h4g3"]  # 4th ply Qh4+
    assert cut_line(chess.Board(), line) == line


def test_cut_line_goes_on_while_a_piece_hangs():
    # 4th ply: the pawn e4 hangs to Nf6. 5.Nc3 guards it, but the pawn e5 still hangs to Nf3.
    line = ["e2e4", "e7e5", "g1f3", "g8f6", "b1c3", "b8c6", "f1c4"]
    assert cut_line(chess.Board(), line) == line[:6]
    # The queen d5 hangs to Nc3: the line goes on to the queen move.
    line = ["e2e4", "d7d5", "e4d5", "d8d5", "b1c3", "d5a5", "a2a3"]
    assert cut_line(chess.Board(), line) == line[:6]


def test_cut_line_goes_on_to_the_recapture_after_a_trade():
    # 2...f6 3.Nxe5 Qe7 4.Nf3 Qxe4+: White's knight leaves, the pawn e4 hangs: Black wins it back.
    b = chess.Board()
    for san in ("e4", "e5", "Nf3"):
        b.push_san(san)
    line = ["f7f6", "f3e5", "d8e7", "e5f3", "e7e4", "f1e2"]
    cut = cut_line(b, line)
    # The old rule stopped after 4.Nf3 with a pawn lost. 5...Qxe4+ is a check, 6.Be2 is quiet.
    assert cut == line, cut
    assert line_material(b, cut, chess.BLACK).change == 0


def test_cut_line_still_stops_at_a_quiet_ply():
    line = ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6"]
    assert cut_line(chess.Board(), line) == line[:4]


def _after_moves(moves, played):
    b = chess.Board()
    for san in moves.split():
        b.push_san(san)
    return b, b.parse_san(played)


@pytest.mark.engine
def test_lost_knight_leads_and_no_false_pin(pool):
    # Italian, 4.Ng5?? Qxg5: the text must name the lost knight, not a "pin" of the d2 pawn
    b, mv = _after_moves("e4 e5 Nf3 Nc6 Bc4 Bc5", "Ng5")
    f = build_facts(pool, b, mv)
    assert f.classification == "blunder"
    assert kinds(f.motifs_against)[0] == "hanging_piece"
    # Not the false pin of the d2 pawn to c1. A later pin of e4 to the unguarded Bc4 is real.
    pinned = [t["square"] for m in f.motifs_against if m.kind == "pin" for t in m.targets]
    assert "d2" not in pinned and "c1" not in pinned


@pytest.mark.engine
def test_missed_queen_win_is_not_a_false_pin(pool):
    # Black plays Ke7?? after Ng5: Qxg5 wins a knight; it is not a "pin" of the d2 pawn
    b, mv = _after_moves("e4 e5 Nf3 Nc6 Bc4 Bc5 Ng5", "Ke7")
    f = build_facts(pool, b, mv)
    assert "pin" not in kinds(f.motifs_missed)


def _reasons(moves, played, ucis, best, cls="inaccuracy", loss=0):
    b, mv = _after_moves(moves, played)
    return _reasons_against(b, mv, ucis, chess.Move.from_uci(best), cls, loss)


def test_fork_reply_is_kept_for_an_inaccuracy():
    # ...Na5 allows b4: the line ends with bxa5, so the attack on the a5 knight is real
    out = _reasons("e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3", "Na5", ["b2b4", "c5b6", "b4a5"], "a7a5")
    assert "reply_attacks" in [r.kind for r in out]


def test_trap_reply_attack_is_kept():
    # ...Nd4 trap: 4.Nxe5? Qg5, and the line takes the e5 knight three plies later
    out = _reasons("e4 e5 Nf3 Nc6 Bc4 Nd4", "Nxe5", ["d8g5", "e1g1", "g5e5"], "f3d4", "blunder")
    assert "reply_attacks" in [r.kind for r in out]


def test_reply_attack_without_a_capture_is_dropped_for_an_inaccuracy():
    out = _reasons("e4 e5 Nf3 Nc6 Bc4 Nd4", "Nxe5", ["d8g5", "e1g1", "g5g6"], "f3d4")
    assert "reply_attacks" not in [r.kind for r in out]


@pytest.mark.engine
def test_trade_on_best_square_keeps_the_development_reason(pool):
    # bxc3? instead of Nxc3: the knight can be traded on c3, but Nxc3 still develops a piece
    b = chess.Board("r1bqk1nr/pppp1pbp/2n3p1/8/2B1P3/2p2N2/PP3PPP/RNBQ1RK1 w kq - 0 7")
    f = build_facts(pool, b, b.parse_san("bxc3"))
    assert "development" in [r.kind for r in f.reasons_missed]


@pytest.mark.engine
def test_threat_the_move_already_answers_is_not_reported(pool):
    # 1.e4 e5 2.Nf3 f6?: the move guards e5, so Nxe5 is no longer the threat
    b, mv = _after_moves("e4 e5 Nf3", "f6")
    f = build_facts(pool, b, mv)
    assert f.threat is None


def test_threat_is_dropped_when_the_move_cut_the_loss():
    b, mv = _after_moves("e4 e5 Nf3", "a6")
    after = b.copy()
    after.push(mv)
    reply = chess.Move.from_uci("f3e5")
    pawn = Threat(move_san="Nxe5", mate_in=None, material=1)
    assert threat_missed(after, reply, pawn, -1)  # the move left the loss as it was
    assert not threat_missed(after, reply, pawn, 0)  # the loss is gone
    assert threat_missed(
        after, reply, Threat(move_san="Nxe5", mate_in=2, material=None), 5
    )  # a mate stays


def test_traded_piece_has_no_development_or_center_reason():
    # Case 31: Nxc6 is answered by bxc6 at once, so "presses on the centre" is wrong
    b = chess.Board("r1bqk2r/pppp1ppp/2n2n2/8/1b1NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 3 6")
    out = _reasons_missed(b, b.parse_san("Bd3"), b.parse_san("Nxc6"))
    assert "center" not in [r.kind for r in out] and "best_attacks" not in [r.kind for r in out]


def test_e5_instead_of_bc4_attacks_the_knight():
    # Case why_bishop_c4_e5_was_better: several best moves are close here, and the engine
    # sometimes picks one other than e5. So the reason is checked with e5 given as the best move.
    b = chess.Board("rnbqkb1r/ppp1pppp/5n2/3p4/3PP3/8/PPP2PPP/RNBQKBNR w KQkq - 1 3")
    out = _reasons_missed(b, b.parse_san("Bc4"), b.parse_san("e5"))
    assert "best_attacks" in [r.kind for r in out]


@pytest.mark.engine
def test_best_defends_text_does_not_say_under_attack(pool):
    # Case 20: after d5 the pawn f7 is attacked, but it does not hang
    b, mv = _after_moves("e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5", "h6")
    f = build_facts(pool, b, mv)
    text = explain(f)
    assert "под боем" not in text.split("Лучше было")[-1], text
    assert "больше не висит" in text, text


@pytest.mark.engine
@pytest.mark.parametrize(
    ("moves", "played"), [("e4 e5 Nf3 Nc6 Bc4", "Qf6"), ("e4 e5 Nf3 Nc6 Bb5", "f6")]
)
def test_quiet_inaccuracy_does_not_invent_a_win(pool, moves, played):
    # Cases 17 and 23: the best move is a development move, not a win of a pawn
    b, mv = _after_moves(moves, played)
    text = explain(build_facts(pool, b, mv))
    assert "выиграть" not in text and "упустил" not in text, text


@pytest.mark.engine
def test_isolated_pawn_reason_for_bxc3(pool):
    # Case g1.7: bxc3 leaves a2 isolated; the text says so and shows no invented win
    b = chess.Board("r1bqk1nr/pppp1pbp/2n3p1/8/2B1P3/2p2N2/PP3PPP/RNBQ1RK1 w kq - 0 7")
    f = build_facts(pool, b, b.parse_san("bxc3"))
    text = explain(f)
    assert f.reasons_against and f.reasons_against[0].kind == "isolated_pawn", f.reasons_against
    assert "пешка на a2 осталась изолированной" in text and "упустил" not in text, text


ELEPHANT = [
    "Nxd5",
    "Nxd5",
    "Bxd8",
    "Bb4+",
    "Qd2",
    "Bxd2+",
    "Kxd2",
    "Kxd8",
    "e3",
    "a6",
    "Nf3",
    "N7b6",
]


def _elephant_trap():
    b = chess.Board()
    for san in ["d4", "d5", "c4", "e6", "Nc3", "Nf6", "Bg5", "Nbd7", "cxd5", "exd5"]:
        b.push_san(san)
    c, ucis = b.copy(), []
    for san in ELEPHANT:
        mv = c.parse_san(san)
        ucis.append(mv.uci())
        c.push(mv)
    return b, ucis


def test_material_is_not_claimed_in_the_middle_of_an_exchange():
    b, ucis = _elephant_trap()
    # Ends on ...Bxd2+: Kxd2 is still to come, so no count is safe.
    mat = settled_material(b, cut_line(b, ucis[:6]), chess.WHITE)
    assert (mat.change, mat.lost, mat.gained) == (0, [], []), mat
    # Ends on ...Kxd8: nothing hangs, the exchange is over: a knight for a pawn.
    mat = settled_material(b, cut_line(b, ucis[:8]), chess.WHITE)
    assert mat.lost == ["N"] and mat.gained == ["P"], mat


def test_material_is_claimed_after_a_capture_that_cannot_be_won_back():
    # 2...Qh4?? 3.Nxh4: the PV may end on the capture; the queen is lost all the same.
    b = chess.Board("rnb1kbnr/pppp1ppp/8/4p3/4P2q/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3")
    mat = settled_material(b, ["f3h4"], chess.BLACK)
    assert mat.lost == ["Q"], mat


def test_material_is_claimed_when_the_exchange_is_over():
    b, ucis = _elephant_trap()
    cut = cut_line(b, ucis)
    assert cut == ucis[:9]  # stops at the quiet e3
    mat = settled_material(b, cut, chess.WHITE)
    assert mat.lost == ["N"] and mat.gained == ["P"]  # a knight for a pawn, not bishop and knight


def test_material_is_not_claimed_when_the_pv_ends_after_a_capture():
    b = chess.Board()
    mat = settled_material(b, ["e2e4", "d7d5", "e4d5"], chess.WHITE)
    assert (mat.change, mat.lost, mat.gained) == (0, [], [])


@pytest.mark.engine
@pytest.mark.parametrize("level", [1, 2, 3])
def test_hidden_explanation_keeps_facts_without_calling_llm(tmp_path, level):
    from dataclasses import replace

    class SpyLLM:
        calls = 0

        def chat(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("hidden prose must not be generated")

    app = create_app(replace(settings, app_db_path=tmp_path / "hidden.db", llm_enabled=True))
    with TestClient(app) as client:
        spy = SpyLLM()
        app.state.llm = spy
        case = CASES[0] if level == 1 else {"fen": chess.STARTING_FEN, "move": "e2e4"}
        response = client.post(
            "/api/coach/move", json={"fen": case["fen"], "move": case["move"], "help_level": level}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["facts"]["classification"] in (("blunder",) if level == 1 else ("best", "good"))
        assert body["facts"]["best_move"]
        assert body["explanation"]["source"] == "template"
        assert body["explanation"]["text"]
        assert spy.calls == 0
