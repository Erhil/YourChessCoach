import re
from pathlib import Path

FILE_RE = re.compile(r"^(\d+)-(.+)\.md$")
BLOCK_RE = re.compile(r"^```(chess|line)[ \t]*\n(.*?)^```[ \t]*$", re.DOTALL | re.MULTILINE)
CHESS_KEYS = {"fen", "task", "solution", "hint"}
LINE_KEYS = {"title", "start", "side"}
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class LessonError(ValueError):
    pass


def _parse_value(raw: str):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return [x.strip().strip("\"'") for x in raw[1:-1].split(",") if x.strip()]
    return raw.strip("\"'")


def _split_front_matter(text: str, name: str) -> tuple[dict, str]:
    parts = text.lstrip("﻿").split("---", 2)
    if len(parts) < 3 or parts[0].strip():
        raise LessonError(f"{name}: front matter between '---' lines is missing")
    meta = {}
    for line in parts[1].splitlines():
        if line.strip():
            key, sep, value = line.partition(":")
            if not sep:
                raise LessonError(f"{name}: bad front matter line {line!r}")
            meta[key.strip()] = _parse_value(value)
    return meta, parts[2]


def _parse_block(body: str, name: str, index: int) -> dict:
    fields = {}
    for line in body.splitlines():
        if line.strip():
            key, sep, value = line.partition(":")
            if not sep or key.strip() not in CHESS_KEYS:
                raise LessonError(f"{name}, chess block {index}: bad line {line!r}")
            fields[key.strip()] = value.strip()
    missing = CHESS_KEYS - fields.keys()
    if missing:
        raise LessonError(f"{name}, chess block {index}: missing {sorted(missing)}")
    fields["solution"] = fields["solution"].split()
    if not fields["solution"]:
        raise LessonError(f"{name}, chess block {index}: empty solution")
    return {"type": "chess", **fields}


def _parse_line_block(body: str, name: str, index: int) -> dict:
    where = f"{name}, line block {index}"
    fields, moves, in_moves = {}, [], False
    for line in body.splitlines():
        if not line.strip():
            continue
        if in_moves and line.lstrip().startswith("-"):
            san, sep, text = line.lstrip()[1:].partition("|")
            if not sep or not san.strip() or not text.strip():
                raise LessonError(f"{where}: move must be '- SAN | text', got {line!r}")
            moves.append({"san": san.strip(), "text": text.strip()})
            continue
        key, sep, value = line.partition(":")
        key = key.strip()
        if (
            not sep
            or (key not in LINE_KEYS and key != "moves")
            or (key == "moves" and value.strip())
        ):
            raise LessonError(f"{where}: bad line {line!r}")
        if key == "moves":
            in_moves = True
        else:
            fields[key] = value.strip()
    missing = LINE_KEYS - fields.keys()
    if missing or not in_moves:
        raise LessonError(
            f"{where}: missing {sorted(missing | ({'moves'} if not in_moves else set()))}"
        )
    if fields["side"] not in ("white", "black"):
        raise LessonError(f"{where}: side must be white or black")
    if not moves:
        raise LessonError(f"{where}: no moves")
    fen = START_FEN if fields["start"] == "startpos" else fields["start"]
    return {
        "type": "line",
        "title": fields["title"],
        "fen": fen,
        "side": fields["side"],
        "moves": moves,
    }


def load_lesson(path: Path) -> dict:
    match = FILE_RE.match(path.name)
    if not match:
        raise LessonError(f"{path.name}: file name must be NN-slug.md")
    meta, body = _split_front_matter(path.read_text(encoding="utf-8"), path.name)
    segments, pos = [], 0
    for index, block in enumerate(BLOCK_RE.finditer(body), start=1):
        text = body[pos : block.start()].strip()
        if text:
            segments.append({"type": "markdown", "text": text})
        parse = _parse_block if block.group(1) == "chess" else _parse_line_block
        segments.append(parse(block.group(2), path.name, index))
        pos = block.end()
    tail = body[pos:].strip()
    if tail:
        segments.append({"type": "markdown", "text": tail})
    try:
        level = int(meta.get("level", ""))
    except ValueError:
        raise LessonError(f"{path.name}: level must be an integer") from None
    return {
        "slug": match.group(2),
        "number": int(match.group(1)),
        "title": meta.get("title", ""),
        "level": level,
        "themes": meta.get("themes", []),
        "prerequisites": meta.get("prerequisites", []),
        "section": meta.get("section") or None,
        "openings": meta.get("openings", []),
        "segments": segments,
    }


def list_lessons(lessons_dir: Path) -> list[dict]:
    files = sorted(p for p in lessons_dir.glob("*.md") if FILE_RE.match(p.name))
    return sorted((load_lesson(p) for p in files), key=lambda x: x["number"])


def position_count(lesson: dict) -> int:
    return sum(s["type"] == "chess" for s in lesson["segments"])


def is_completed(lesson: dict, solved: int) -> bool:
    n = position_count(lesson)
    return n > 0 and solved >= n
