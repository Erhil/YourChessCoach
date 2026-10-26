import pytest

from app.lessons.loader import START_FEN, LessonError, load_lesson

HEAD = "---\ntitle: T\nlevel: 1\nthemes: []\nprerequisites: []\n---\n"
LINE = """Intro

```line
title: Итальянская: главная
start: startpos
side: black
moves:
- e4 | Центр.
- e5 | Тоже центр.
```

Outro
"""


def write(tmp_path, body):
    path = tmp_path / "01-x.md"
    path.write_text(HEAD + body, encoding="utf-8")
    return path


def test_line_block_is_parsed(tmp_path):
    segments = load_lesson(write(tmp_path, LINE))["segments"]
    assert [s["type"] for s in segments] == ["markdown", "line", "markdown"]
    assert segments[1] == {
        "type": "line",
        "title": "Итальянская: главная",
        "fen": START_FEN,
        "side": "black",
        "moves": [{"san": "e4", "text": "Центр."}, {"san": "e5", "text": "Тоже центр."}],
    }


@pytest.mark.parametrize(
    "bad",
    [
        LINE.replace("- e5 | Тоже центр.", "- e5 без текста"),
        LINE.replace("- e5 | Тоже центр.", "- e5 |  "),
        LINE.replace("side: black", "side: green"),
        LINE.replace("side: black\n", ""),
        LINE.replace("moves:\n- e4 | Центр.\n- e5 | Тоже центр.\n", "moves:\n"),
        LINE.replace("start: startpos", "begin: startpos"),
    ],
)
def test_malformed_line_block_names_file_and_block(tmp_path, bad):
    with pytest.raises(LessonError, match=r"01-x\.md, line block 1"):
        load_lesson(write(tmp_path, bad))


def test_section_and_openings_are_read(tmp_path):
    extra = "section: Дебюты: ловушки\nopenings: [Italian Game, Ruy Lopez]\n"
    path = tmp_path / "01-x.md"
    path.write_text(
        HEAD.replace("\n---\n", "\n" + extra + "---\n") + "Text\n",
        encoding="utf-8",
    )
    lesson = load_lesson(path)
    assert lesson["section"] == "Дебюты: ловушки"
    assert lesson["openings"] == ["Italian Game", "Ruy Lopez"]
    plain = load_lesson(write(tmp_path, "Text\n"))
    assert plain["section"] is None and plain["openings"] == []
