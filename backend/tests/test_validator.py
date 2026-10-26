import pytest

from app.coach.prompt import build_messages, compact_facts, figurine_to_san
from app.coach.schema import CoachFacts
from app.coach.validator import to_display, validate


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


GOOD = (
    "Зевок: после ответа Nxh4 вы теряете ферзя. Ваш ферзь на h4 оказался под боем, "
    "его забирает конь с f3. Перед каждым ходом проверяйте, какие фигуры остались без защиты."
)


def test_good_text_passes():
    assert validate(GOOD, facts()) == []


def test_figurine_text_passes():
    assert validate("Лучше было ♘c6, а потом Bb5.", facts()) == []


def test_mate_in_from_facts_passes():
    f = facts(allowed_mate_in=2)
    assert validate("У соперника мат в 2, начиная с Nxh4.", f) == []
    assert validate("У соперника мат в 3.", f) != []


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("Вы потеряли ферзя, лучше было Bc4.", "Bc4"),
        ("Лучше было Nf3, но вы сыграли иначе.", "Nf3"),
        ("Ферзь на a7 оказался под боем.", "a7"),
        ("Вы теряете ферзя на e5.", "e5"),
        ("Оценка позиции -400 сантипешек.", "digits"),
        ("You lose the queen because the knight on f3 takes it.", "Russian"),
        ("Раз. Два. Три. Четыре. Пять. Шесть.", "too many"),
        ("Вы теряете ферзя.\n- не делайте так\n- смотрите на h4", "markdown"),
        ("**Зевок**: ферзь на h4 потерян.", "markdown"),
    ],
)
def test_bad_text_fails(text, reason):
    reasons = validate(text, facts())
    assert reasons, text
    if reason != "empty":
        assert any(reason.lower() in r.lower() for r in reasons), reasons


LIVE_BAD = [
    (
        (
            "Вы совершили грубый промах, позволив своему ферзю на h4 остаться без защиты и быть "
            "захваченным конем f3. В результате вы потеряли ценную фигуру и пешку."
        ),
        "пешк",
    ),
    ("Это вилка на ферзя и короля: конь f3 бьёт два вражеских королевских поля.", "корол"),
    (
        "Вы пропустели мат в один ход Ra8#. Нужна атака для шaha ладьёй или ферзёмом.",
        "mixed Latin",
    ),
]


@pytest.mark.parametrize(("text", "reason"), LIVE_BAD)
def test_live_bad_outputs_fail(text, reason):
    reasons = validate(text, facts(missed_mate_in=2, best_line=["Ra8#"]))
    assert any(reason in r for r in reasons), reasons


def test_number_word_must_match_mate():
    assert validate("У соперника мат в два хода.", facts(allowed_mate_in=2)) == []
    assert validate("У соперника мат в три хода.", facts(allowed_mate_in=2)) != []
    assert validate("У соперника мат в один ход.", facts()) != []


@pytest.mark.parametrize(
    "text",
    [
        "Вы потеряли ферзя. Его на h4 забирает конь с f3. Сначала проверяйте, что стоит под боем.",
        "Лучше было сыграть конём на c6, а следом слоном на b5. Так вы развиваете фигуры.",
        "Ваш ферзь на h4 попал под удар коня. Это зевок, вы теряете ферзя.",
    ],
)
def test_good_llm_like_texts_pass(text):
    assert validate(text, facts(best_line=["Nc6", "Bb5"])) == []


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


def test_role_player_move_is_not_the_opponents():
    f = facts(player_move={"san": "Nxg4", "uci": "f6g4"}, refutation=["Qxg4"])
    bad = "Соперник сделал ♘xg4, что является ошибкой."
    assert any("opponent" in r for r in validate(bad, f))
    f = facts(player_move={"san": "Qxc5", "uci": "d8c5"}, refutation=["Nxc5"])
    assert validate("Соперник сделал ход ♕xc5, что привело к потере ферзя.", f)
    assert validate("Вы сыграли ♕xc5, и соперник ответил Nxc5, забрав ферзя.", f) == []


def test_role_refutation_is_not_the_players():
    f = facts()
    assert any("player" in r for r in validate("Вы сыграли Nxh4, потеряв ферзя.", f))
    assert validate("Вы сыграли Qh4, и соперник ответил Nxh4. Так вы потеряли ферзя.", f) == []


def _stalemate(text, **kw):
    return validate(text, facts(game_over="stalemate", **kw))


def test_stalemate_is_a_draw():
    base = {
        "player_move": {"san": "Qg6", "uci": "d8g6"},
        "material": {"change": 0, "lost": [], "gained": []},
    }
    assert _stalemate("Игрок сделал ход ♕g6, который привел к проигрышу.", **base)
    assert _stalemate("Вы сыграли Qg6, и это привело к пату.", **base) == []
    assert _stalemate("Вы сыграли Qg6, это ничья.", **base) == []
    assert _stalemate("Вы сыграли Qg6, это ничья и поражение.", **base)
    assert validate("Теперь у соперника пат.", facts())


def test_classification_must_match_tone():
    assert validate("Это зевок, вы теряете ферзя.", facts(classification="good"))
    assert validate("Это отличный ход, вы теряете ферзя.", facts())


def test_praise_for_an_inaccuracy_fails():
    # Game 12, 6.Nd5: the local model called an inaccuracy "хороший".
    text = "Вы сыграли ход Qh4, который был хорошим. Лучше было Nc6."
    for cls in ("inaccuracy", "mistake", "blunder"):
        assert "praise for a bad move" in validate(text, facts(classification=cls))
    assert validate(text, facts(classification="good")) == []
    mistake = facts(classification="mistake")
    assert validate("Это не хороший ход: лучше было Nc6.", mistake) == []
    # Seen in the bench: words about the best move, not praise of the played move.
    assert validate("Вы сыграли Qh4, который не был хорошим. Лучше было Nc6.", mistake) == []
    assert validate("Вы теряете ферзя. Подумайте о Nc6, так как это был лучший ход.", mistake) == []


# Game 12, 16.cxd4: the text was cached when the engine's best move was c4;
# a new search gave Kd2, and c4 passed only as a square of Bc4 in the best line.
CXD4 = {
    "fen_before": "r4rk1/ppp2ppp/1b1p4/3P1b2/1P1p4/2P2P2/P4P1P/R1B1KB1R w KQ - 0 16",
    "side": "white",
    "player_move": {"san": "cxd4", "uci": "c3d4"},
    "classification": "inaccuracy",
    "best_move": {"san": "Kd2", "uci": "e1d2"},
    "best_line": ["Kd2", "a5", "a4", "dxc3+", "Kxc3", "Bxf2", "Bc4"],
    "refutation": ["Bxd4", "Be3", "Bxa1", "Kd2"],
    "material": {"change": -5, "lost": ["R"], "gained": []},
    "motifs_against": [],
}
CXD4_TEXT = "Лучше было сыграть c4, чтобы ваша пешка не висела."


def test_recommended_move_must_be_the_best_move():
    assert "recommended move is not the best move: c4" in validate(CXD4_TEXT, facts(**CXD4))
    with_c4 = CXD4 | {"best_move": {"san": "c4", "uci": "c3c4"}, "best_line": ["c4", "a5"]}
    assert validate(CXD4_TEXT, facts(**with_c4)) == []
    assert validate("Лучший ход был Bb5.", facts()) != []  # in the best line, but not the best move
    assert validate("Лучший ход — Nc6.", facts()) == []


def test_informal_address_fails():
    assert validate("Обращай внимание на ферзя на h4.", facts())
    assert validate("Ты теряешь ферзя.", facts())
    assert validate("Проверяйте ферзя на h4. Смотрите на поле h4.", facts()) == []


def test_reason_squares_and_pieces_are_allowed():
    reason = {
        "kind": "removed_defender",
        "squares": ["e5"],
        "pieces": [{"square": "d4", "piece": "n"}, {"square": "e5", "piece": "p"}],
        "detail": None,
    }
    f = facts(
        material={"change": 0, "lost": [], "gained": []},
        motifs_against=[],
        reasons_against=[reason],
        classification="mistake",
    )
    text = "Ваш конь ушёл с d4 и больше не защищает пешку на e5. Лучше было Nc6."
    assert validate(text, f) == []
    assert validate(text, facts(motifs_against=[], classification="mistake")) != []
    assert "reasons_against" in compact_facts(f)
