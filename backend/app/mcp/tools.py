"""Tools of the senior coach. Each tool reads the data of ONE user (the key owner) and returns plain data.

Chess claims come only from Stockfish and python-chess (through the review and engine modules).
"""

import functools
import io
import json
import math
import sqlite3
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import chess
import chess.pgn
from fastapi import FastAPI, HTTPException

from app.activity.achievements import earned_titles
from app.activity.days import activity_state, server_tz
from app.db import TRAINING_GAME
from app.engines.pool import EngineUnavailableError
from app.lessons.loader import is_completed, list_lessons, position_count
from app.mcp.plan import insert_plan, latest_plan
from app.mistakes.srs import now_utc
from app.openings.lookup import family_of, find_opening
from app.openings.names import ru_name
from app.puzzles.routes import _opening_counts
from app.puzzles.themes import OFFERED, theme_name
from app.review.routes import BAD, ReviewRequest, review
from app.security import COACH_BUSY

MAX_DEPTH = 18
MOVETIME_MS = 3000  # like /api/analyze: the search stops at this time
MAX_FEN = 100
MAX_GAME_ID = 2**62
DEFAULT_DEPTH = 14
MAX_GAMES_SCANNED = 300
MAX_SUMMARY = 1500
MAX_THEMES, MAX_LESSONS, MAX_OPENINGS = 3, 6, 3
PV_MOVES = 8
SOLVED_CHUNK = 500


class ToolError(Exception):
    """A problem the model can read and fix: it goes back as an `isError` tool result."""


@dataclass
class Ctx:
    app: FastAPI
    db: sqlite3.Connection
    user_id: int

    @property
    def settings(self):
        return self.app.state.settings

    @contextmanager
    def engine_slot(self):
        slots = self.app.state.engine_slots
        if not slots.acquire(self.user_id):
            raise ToolError(COACH_BUSY)
        try:
            yield
        finally:
            slots.release(self.user_id)


# ---------------------------------------------------------------- shared helpers


def _book(ctx: Ctx) -> Path | None:
    path = ctx.settings.app_data_dir / "openings.tsv"
    return path if path.is_file() else None


def _families(ctx: Ctx) -> dict[str, int]:
    path = ctx.settings.puzzles_db_path
    return _opening_counts(str(path), path.stat().st_mtime) if path.is_file() else {}


def _uci_moves(pgn: str) -> list[str]:
    game = chess.pgn.read_game(io.StringIO(pgn))
    return [m.uci() for m in game.mainline_moves()] if game else []


@functools.lru_cache(maxsize=2048)
def _opening_cached(book: str, mtime: float, pgn: str) -> dict | None:
    try:
        found = find_opening(Path(book), _uci_moves(pgn))
    except ValueError:
        return None
    return {**found, "family": family_of(found["name"])} if found else None


def _opening(ctx: Ctx, pgn: str) -> dict | None:
    """{eco, name, family} of the opening a game passes through, or None. Cached by the PGN."""
    book = _book(ctx)
    if book is None:
        return None
    return _opening_cached(str(book), book.stat().st_mtime, pgn)


def _int(name: str, value, low: int, high: int, clamp: bool = False) -> int:
    """A finite integer; out of range is an error, or is clamped."""
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{name} must be an integer")
    if clamp:
        return max(low, min(value, high))
    if not low <= value <= high:
        raise ToolError(f"{name} must be from {low} to {high}")
    return value


def _outcome(result: str, color: str) -> str:
    if result == "1/2-1/2":
        return "draws"
    if result == "*":
        return "unfinished"
    return "wins" if (result == "1-0") == (color == "white") else "losses"


def _valid_values(ctx: Ctx) -> dict:
    families = _families(ctx)
    return {
        "themes": [{"key": k, "name": theme_name(k)} for k in sorted(OFFERED)],
        "lessons": [
            {"slug": x["slug"], "title": x["title"]} for x in list_lessons(ctx.settings.lessons_dir)
        ],
        "openings": [
            {"key": k, "name": ru_name(k.replace("_", " "))}
            for k in sorted(families, key=lambda k: -families[k])
        ],
    }


def _eval_words(cp: int | None, mate: int | None) -> str:
    """The White-view score in words for a beginner."""
    if mate is not None:
        if mate == 0:
            return "мат"
        side = "белых" if mate > 0 else "чёрных"
        return f"у {side} мат в {abs(mate)}"
    cp = cp or 0
    side = "белых" if cp > 0 else "чёрных"
    size = abs(cp)
    if size < 30:
        return "позиция примерно равная"
    if size < 100:
        return f"небольшое преимущество у {side}"
    if size < 300:
        return f"заметное преимущество у {side}"
    return f"у {side} решающее преимущество"


# ---------------------------------------------------------------- get_profile


def _solved_by_theme(ctx: Ctx) -> dict[str, int] | None:
    """Solved puzzles per theme. The themes live in the puzzle database; None when it is missing."""
    path = ctx.settings.puzzles_db_path
    if not path.is_file():
        return None
    ids = [
        r[0]
        for r in ctx.db.execute(
            "SELECT DISTINCT puzzle_id FROM puzzle_attempts WHERE user_id = ? AND solved = 1",
            (ctx.user_id,),
        )
    ]
    counts: Counter = Counter()
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        for i in range(0, len(ids), SOLVED_CHUNK):
            part = ids[i : i + SOLVED_CHUNK]
            marks = ",".join("?" * len(part))
            sql = f"SELECT themes FROM puzzles WHERE id IN ({marks})"
            for (themes,) in conn.execute(sql, part):
                counts.update(set((themes or "").split()))
    finally:
        conn.close()
    return dict(counts)


def _games_block(ctx: Ctx) -> tuple[dict, list[dict]]:
    total = ctx.db.execute(
        "SELECT COUNT(*) FROM games WHERE user_id = ?", (ctx.user_id,)
    ).fetchone()[0]
    rows = ctx.db.execute(
        f"SELECT player_color, level, result, moves_count, pgn, {TRAINING_GAME} AS training"
        " FROM games WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (ctx.user_id, MAX_GAMES_SCANNED),
    ).fetchall()
    by_group: dict[tuple, Counter] = defaultdict(Counter)
    by_opening: dict[tuple, Counter] = defaultdict(Counter)
    training = ctx.db.execute(
        f"SELECT COUNT(*) FROM games WHERE user_id = ? AND result != '*' AND {TRAINING_GAME}",
        (ctx.user_id,),
    ).fetchone()[0]
    for g in rows:
        outcome = _outcome(g["result"], g["player_color"])
        # The result of a training game does not count; its opening is still the repertoire.
        if not g["training"]:
            group = by_group[(g["player_color"], g["level"])]
            group["games"] += 1
            group[outcome] += 1
        found = _opening(ctx, g["pgn"])
        if found:
            entry = by_opening[(found["family"], g["player_color"])]
            entry["games"] += 1
            finished_training = g["training"] and outcome != "unfinished"
            entry["training" if finished_training else outcome] += 1
    plies = [g["moves_count"] for g in rows]
    counts = ("games", "wins", "losses", "draws")
    games = {
        "count": total,
        "training": training,
        "scanned": len(rows),
        "average_plies": round(sum(plies) / len(plies), 1) if plies else None,
        "by_color_and_level": [
            {"color": c, "level": lv, **{k: v[k] for k in counts}}
            for (c, lv), v in sorted(by_group.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0))
        ],
    }
    openings = [
        {
            "family": fam,
            "key": fam.replace(" ", "_"),
            "name": ru_name(fam),
            "color": color,
            **{k: v[k] for k in (*counts, "training")},
        }
        for (fam, color), v in sorted(by_opening.items(), key=lambda kv: -kv[1]["games"])
    ]
    return games, openings


def _mistakes_block(ctx: Ctx) -> dict:
    db, uid = ctx.db, ctx.user_id

    def grouped(column: str) -> dict:
        sql = (
            f"SELECT {column}, COUNT(*) FROM mistakes WHERE user_id = ?"
            f" GROUP BY {column} ORDER BY COUNT(*) DESC"
        )
        return {r[0] or "unknown": r[1] for r in db.execute(sql, (uid,))}

    def count(where: str, *args) -> int:
        sql = f"SELECT COUNT(*) FROM mistakes WHERE user_id = ? AND {where}"
        return db.execute(sql, (uid, *args)).fetchone()[0]

    return {
        "total": count("1 = 1"),
        "learned": count("learned_at IS NOT NULL"),
        "due": count("due_at <= ? AND learned_at IS NULL", now_utc()),
        "by_motif": grouped("motif"),
        "by_classification": grouped("classification"),
    }


def _puzzles_block(ctx: Ctx) -> dict:
    db, uid = ctx.db, ctx.user_id
    overall = db.execute(
        "SELECT rating, attempts FROM user_ratings WHERE user_id = ? AND scope = 'overall'", (uid,)
    ).fetchone()
    solved = _solved_by_theme(ctx)
    themes = [
        {
            "key": r["scope"],
            "name": theme_name(r["scope"]),
            "rating": round(r["rating"]),
            "attempts": r["attempts"],
            "solved": None if solved is None else solved.get(r["scope"], 0),
        }
        for r in db.execute(
            "SELECT scope, rating, attempts FROM user_ratings"
            " WHERE user_id = ? AND scope != 'overall' ORDER BY rating, scope",
            (uid,),
        )
        if r["scope"] in OFFERED
    ]
    return {
        "overall_rating": round(overall["rating"]) if overall else None,
        "overall_attempts": overall["attempts"] if overall else 0,
        "themes_weakest_first": themes,
    }


def _lessons_block(ctx: Ctx) -> dict:
    solved = {
        r[0]: r[1]
        for r in ctx.db.execute(
            "SELECT slug, COUNT(*) FROM lesson_progress WHERE user_id = ? GROUP BY slug",
            (ctx.user_id,),
        )
    }
    done, todo = [], []
    for x in list_lessons(ctx.settings.lessons_dir):
        n = solved.get(x["slug"], 0)
        item = {
            "slug": x["slug"],
            "title": x["title"],
            "section": x["section"],
            "level": x["level"],
        }
        if is_completed(x, n):
            done.append(item)
        else:
            todo.append({**item, "solved_positions": n, "positions": position_count(x)})
    return {"done": done, "not_done": todo}


def _activity_block(ctx: Ctx) -> dict:
    """Activity in the server time zone: the week, the last active date, stored achievements."""
    state = activity_state(ctx.db, ctx.user_id, server_tz(), now_utc())
    wk, today, active = state.week, state.today, state.active
    return {
        "week": {k: wk[k] for k in ("goal", "active_days", "met", "streak_weeks")},
        "last_active_date": max(active).isoformat() if active else None,
        "active_days_last_28": sum(today - d < timedelta(days=28) for d in active if d <= today),
        "achievements_earned": earned_titles(ctx.db, ctx.user_id),
    }


def get_profile(ctx: Ctx) -> dict:
    with ctx.engine_slot():  # parsing many games is heavy work too
        games, openings = _games_block(ctx)
    return {
        "games": games,
        "openings_played": openings,
        "mistakes_deck": _mistakes_block(ctx),
        "puzzles": _puzzles_block(ctx),
        "lessons": _lessons_block(ctx),
        "activity": _activity_block(ctx),
        "plan": latest_plan(ctx.db, ctx.user_id),
        "valid_values_for_save_plan": _valid_values(ctx),
    }


# ---------------------------------------------------------------- games


def list_games(ctx: Ctx, limit: int = 20) -> list[dict]:
    limit = _int("limit", limit, 1, 100, clamp=True)
    rows = ctx.db.execute(
        "SELECT id, created_at, player_color, level, result, termination, moves_count, pgn,"
        f" takebacks, hints, {TRAINING_GAME} AS training"
        " FROM games WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (ctx.user_id, limit),
    ).fetchall()
    out = []
    with ctx.engine_slot():
        found_all = [_opening(ctx, g["pgn"]) for g in rows]
    for g, found in zip(rows, found_all, strict=True):
        out.append(
            {
                "id": g["id"],
                "date": g["created_at"],
                "color": g["player_color"],
                "level": g["level"],
                "result": g["result"],
                "termination": g["termination"],
                "plies": g["moves_count"],
                "opening": ru_name(found["name"]) if found else None,
                "training": bool(g["training"]),
                "takebacks": g["takebacks"],
                "hints": g["hints"],
            }
        )
    return out


def review_game(ctx: Ctx, game_id: int) -> dict:
    game_id = _int("game_id", game_id, 1, MAX_GAME_ID)
    row = ctx.db.execute(
        f"SELECT pgn, player_color, result, moves_count, takebacks, hints, {TRAINING_GAME}"
        " AS training FROM games WHERE id = ? AND user_id = ?",
        (game_id, ctx.user_id),
    ).fetchone()
    if row is None:
        raise ToolError(f"Game {game_id} not found")
    request = SimpleNamespace(app=ctx.app)
    # The pgn is passed, not the game id: a review by game id also adds cards to the mistakes deck.
    body = ReviewRequest(pgn=row["pgn"], side=row["player_color"])
    with ctx.engine_slot():
        try:
            data = review(body, request, ctx.db, ctx.user_id)
        except HTTPException as exc:
            raise ToolError(str(exc.detail)) from exc
        except EngineUnavailableError as exc:
            raise ToolError(str(exc)) from exc
    side = data["side"]
    found = _opening(ctx, row["pgn"])
    return {
        "game_id": game_id,
        "side": side,
        "result": row["result"],
        "plies": row["moves_count"],
        "opening": ru_name(found["name"]) if found else None,
        "training": bool(row["training"]),
        "takebacks": row["takebacks"],
        "hints": row["hints"],
        "summary": data["summary"],
        "bad_moves": [
            {
                "ply": m["ply"],
                "move_number": (m["ply"] + 1) // 2,
                "san": m["san"],
                "classification": m["classification"],
            }
            for m in data["moves"]
            if m["color"] == side and m["classification"] in BAD
        ],
        "key_moments": [_moment(m) for m in data["key_moments"]],
    }


def _moment(m: dict) -> dict:
    f = m["facts"]
    return {
        "ply": m["ply"],
        "move_number": (m["ply"] + 1) // 2,
        "san": m["san"],
        "classification": f.classification,
        "best_move": f.best_move.san if f.best_move else None,
        "best_line": f.best_line[:PV_MOVES],
        "refutation": f.refutation[:PV_MOVES],
        "eval_before": _eval_words(f.eval_before.cp, f.eval_before.mate),
        "eval_after": _eval_words(f.eval_after.cp, f.eval_after.mate),
        "missed_mate_in": f.missed_mate_in,
        "allowed_mate_in": f.allowed_mate_in,
        "motifs_missed": [x.kind for x in f.motifs_missed],
        "motifs_against": [x.kind for x in f.motifs_against],
        "explanation": m["explanation"]["text"],
    }


def analyse_position(ctx: Ctx, fen: str, depth: int = DEFAULT_DEPTH) -> dict:
    if not isinstance(fen, str) or len(fen) > MAX_FEN:
        raise ToolError(f"fen must be a string of at most {MAX_FEN} characters")
    depth = _int("depth", depth, 1, MAX_DEPTH, clamp=True)
    try:
        board = chess.Board(fen)
    except ValueError as exc:
        raise ToolError(f"Bad FEN: {exc}") from exc
    if not board.is_valid():
        raise ToolError("The position is not legal")
    turn = "white" if board.turn == chess.WHITE else "black"
    if board.is_game_over():
        return {"fen": board.fen(), "turn": turn, "game_over": board.result(), "lines": []}
    with ctx.engine_slot():
        try:
            reached, lines = ctx.app.state.pool.analyse(board, depth, MOVETIME_MS, 3)
        except EngineUnavailableError as exc:
            raise ToolError(str(exc)) from exc
    return {
        "fen": board.fen(),
        "turn": turn,
        "depth": reached,
        "note": "cp and mate are from the White point of view",
        "lines": [
            {
                "rank": ln["rank"],
                "move": ln["pv_san"][0] if ln["pv_san"] else None,
                "pv": ln["pv_san"][:PV_MOVES],
                "cp": ln["score"]["cp"],
                "mate": ln["score"]["mate"],
                "in_words": _eval_words(ln["score"]["cp"], ln["score"]["mate"]),
            }
            for ln in lines
        ],
    }


# ---------------------------------------------------------------- plan


def get_plan(ctx: Ctx) -> dict:
    return {"plan": latest_plan(ctx.db, ctx.user_id)}


def _pick(name: str, value, limit: int, allowed: list[str]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ToolError(f"{name} must be a list of strings")
    value = list(dict.fromkeys(value))
    if len(value) > limit:
        raise ToolError(f"{name}: at most {limit} values, got {len(value)}")
    bad = [x for x in value if x not in allowed]
    if bad:
        raise ToolError(f"{name}: unknown values {bad}. Allowed values: {json.dumps(allowed)}")
    return value


def save_plan(ctx: Ctx, summary: str, focus_themes: list, lessons: list, openings: list) -> dict:
    if not isinstance(summary, str) or not summary.strip():
        raise ToolError("summary must be a non-empty string")
    if len(summary) > MAX_SUMMARY:
        raise ToolError(f"summary is {len(summary)} characters; the limit is {MAX_SUMMARY}")
    valid = _valid_values(ctx)
    themes = _pick("focus_themes", focus_themes, MAX_THEMES, [t["key"] for t in valid["themes"]])
    slugs = _pick("lessons", lessons, MAX_LESSONS, [x["slug"] for x in valid["lessons"]])
    fams = _pick("openings", openings, MAX_OPENINGS, [o["key"] for o in valid["openings"]])
    return {"plan": insert_plan(ctx.db, ctx.user_id, summary.strip(), themes, slugs, fams)}
