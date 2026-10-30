import pytest

from app.coach.prompt import build_messages, figurine_to_san
from app.coach.schema import CoachFacts
from app.coach.validator import render_response, to_display


def facts(**kw) -> CoachFacts:
    base = {
        "fen_before": "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
        "side": "black",
        "player_move": {"san": "Qh4", "uci": "d8h4"},
        "classification": "blunder",
        "win_chance_drop": 40.0,
        "eval_before": {"cp": 20, "mate": None},
        "eval_after": {"cp": -400, "mate": None},
        "best_move": {"san": "Nc6", "uci": "b8c6"},
        "best_line": ["Nc6", "Bb5"],
        "refutation": ["Nxh4"],
        "material": {"change": -9, "lost": ["Q"], "gained": []},
        "missed_material": {"change": 0, "lost": [], "gained": []},
        "motifs_against": [
            {
                "kind": "hanging_piece",
                "by": {"square": "f3", "piece": "N"},
                "targets": [{"square": "h4", "piece": "q"}],
                "move_san": None,
            }
        ],
        "motifs_missed": [],
        "allowed_mate_in": None,
        "missed_mate_in": None,
        "threat": None,
        "lesson": None,
    }
    return CoachFacts.model_validate(base | kw)


def test_to_display_uses_figurines():
    assert to_display("Ответ Nxh4 и ход Qh4+.") == "Ответ ♘xh4 и ход ♕h4+."
    assert to_display("Пешка e4 и O-O.") == "Пешка e4 и O-O."


def test_figurine_to_san():
    assert figurine_to_san("♘c7+ и e8=♕") == "Nc7+ и e8=Q"


def test_prompt_is_compact_and_latin():
    system, user = build_messages(facts())
    assert "Nxh4" in user
    assert "♘" not in user
    assert "fen_before" not in user
    assert "SAN" in system


@pytest.mark.parametrize(
    "payload",
    [
        "null",
        "[]",
        '{"tip":true}',
        '{"tip":null}',
        '{"tip":"unknown"}',
        '{"tip":"none","text":"Вы выигрываете ферзя."}',
    ],
)
def test_only_known_advice_selection_is_accepted(payload):
    with pytest.raises(ValueError):
        render_response(payload, facts())
