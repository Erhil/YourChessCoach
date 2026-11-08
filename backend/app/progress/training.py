"""A short, persistent practice session without changes to ratings or review cards."""

import json
import sqlite3
from contextlib import closing
from io import StringIO
from time import time
from typing import Literal

import chess
import chess.engine
import chess.pgn
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from app.auth.deps import UserId
from app.coach.classify import mover_view
from app.coach.facts import build_facts, cut_line
from app.coach.templates import explain, fig
from app.db import Db
from app.engines.pool import EngineUnavailableError
from app.lessons.loader import list_lessons
from app.puzzles.rating import START_RATING
from app.puzzles.routes import WINDOWS
from app.puzzles.themes import OFFERED
from app.security import ENGINE_HEAVY

router = APIRouter(prefix="/api/training")
DAY = 86400
NO_EXERCISE = "Не нашлось новой позиции подходящей сложности."
NO_DELAYED = "Для проверки не нашлось новой позиции нужной темы и сложности."
NOT_DUE = "Отложенная проверка открывается через 7 дней после занятия."
VERSION_CONFLICT = "Занятие изменилось. Обновите страницу."
MOTIF_THEMES = {
    "hanging_piece": "hangingPiece",
    "back_rank": "backRankMate",
    "discovered_attack": "discoveredAttack",
}


class Mutation(BaseModel):
    client_id: str = Field(min_length=1, max_length=100)
    expected_login: str = Field(min_length=1, max_length=100)


class Start(Mutation):
    kind: Literal["practice", "delayed"]


class Action(Mutation):
    version: int = Field(ge=1)
    action: Literal["move", "hint", "reveal", "next", "finish"]
    uci: str | None = Field(default=None, min_length=4, max_length=5)

    @model_validator(mode="after")
    def validate_move(self):
        if (self.action == "move") != (self.uci is not None):
            raise ValueError("A move requires UCI and other actions do not accept it.")
        return self


def _check_owner(db: Db, user_id: int, expected_login: str | None) -> None:
    if expected_login is not None:
        owner = db.execute("SELECT login FROM users WHERE id = ?", (user_id,)).fetchone()
        if owner is None or owner["login"] != expected_login:
            raise HTTPException(403, "Профиль изменился. Войдите в исходный профиль.")


def _session(db: Db, user_id: int, session_id: int | None = None) -> sqlite3.Row | None:
    if session_id is None:
        return db.execute(
            "SELECT * FROM training_sessions WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return db.execute(
        "SELECT * FROM training_sessions WHERE user_id = ? AND id = ?", (user_id, session_id)
    ).fetchone()


def _receipt(db: Db, user_id: int, client_id: str, payload: str) -> sqlite3.Row | None:
    row = db.execute(
        "SELECT * FROM training_receipts WHERE user_id = ? AND client_id = ?",
        (user_id, client_id),
    ).fetchone()
    if row is None:
        return None
    if row["request"] != payload:
        raise HTTPException(409, "Этот идентификатор уже использован для другого действия.")
    return _session(db, user_id, row["session_id"])


def _save_receipt(db: Db, user_id: int, client_id: str, session_id: int, payload: str) -> None:
    db.execute(
        "INSERT INTO training_receipts VALUES (?, ?, ?, ?)",
        (user_id, client_id, session_id, payload),
    )


def _position_key(board: chess.Board) -> str:
    # Move counters are irrelevant to novelty. Use the legal en passant square.
    return " ".join(board.fen().split()[:4])


def _exercise(
    db: Db, user_id: int, request: Request, theme: str | None, basic: bool
) -> dict | None:
    path = request.app.state.settings.puzzles_db_path
    if not path.is_file():
        return None
    seen_ids = {
        row[0]
        for row in db.execute(
            "SELECT puzzle_id FROM puzzle_attempts WHERE user_id = ?"
            " UNION SELECT ref FROM mistakes WHERE user_id = ? AND source = 'puzzle'",
            (user_id, user_id),
        )
    }
    seen_positions = {
        _position_key(chess.Board(row[0]))
        for row in db.execute(
            "SELECT fen FROM mistakes WHERE user_id = ?"
            " UNION SELECT fen FROM mistake_events WHERE user_id = ?",
            (user_id, user_id),
        )
    }
    for row in db.execute("SELECT snapshot FROM training_sessions WHERE user_id = ?", (user_id,)):
        snapshot = json.loads(row[0])
        for slot in snapshot["slots"][: snapshot["index"] + 1]:
            seen_positions.add(_position_key(chess.Board(slot["fen"])))
            if slot["puzzle_id"] is not None:
                seen_ids.add(slot["puzzle_id"])
    for row in db.execute("SELECT pgn FROM games WHERE user_id = ?", (user_id,)):
        game = chess.pgn.read_game(StringIO(row["pgn"]))
        if game is not None:
            board = game.board()
            seen_positions.add(_position_key(board))
            for move in game.mainline_moves():
                board.push(move)
                seen_positions.add(_position_key(board))
    solved = {
        (row["slug"], row["position"])
        for row in db.execute(
            "SELECT slug, position FROM lesson_progress WHERE user_id = ?", (user_id,)
        )
    }
    if solved:
        for lesson in list_lessons(request.app.state.settings.lessons_dir):
            positions = (s for s in lesson["segments"] if s["type"] == "chess")
            for index, position in enumerate(positions):
                if (lesson["slug"], index) in solved:
                    seen_positions.add(_position_key(chess.Board(position["fen"])))
    target = START_RATING
    if not basic:
        row = db.execute(
            "SELECT rating FROM user_ratings WHERE user_id = ? AND scope IN ('overall', ?)"
            " ORDER BY (scope = ?) DESC LIMIT 1",
            (user_id, theme, theme),
        ).fetchone()
        if row is not None:
            target = row["rating"]

    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as pdb:
        pdb.row_factory = sqlite3.Row
        # Include later learner turns from recorded puzzle lines, including legacy attempt rows.
        for puzzle_id in seen_ids:
            puzzle = pdb.execute(
                "SELECT fen, moves FROM puzzles WHERE id = ?", (puzzle_id,)
            ).fetchone()
            if puzzle is None:
                continue
            board = chess.Board(puzzle["fen"])
            for index, uci in enumerate(puzzle["moves"].split()):
                board.push_uci(uci)
                if index % 2 == 0:
                    seen_positions.add(_position_key(board))

        # Limit widening to useful ratings. A neutral exercise stays near the beginner baseline.
        window = WINDOWS[1] if basic else WINDOWS[2]
        rows = pdb.execute(
            "SELECT * FROM puzzles WHERE rating BETWEEN ? AND ?"
            " AND (? IS NULL OR id IN (SELECT puzzle_id FROM puzzle_themes WHERE theme = ?))"
            " ORDER BY abs(rating - ?), id",
            (target - window, target + window, theme, theme, target),
        )
        for puzzle in rows:
            if puzzle["id"] in seen_ids:
                continue
            board = chess.Board(puzzle["fen"])
            moves = puzzle["moves"].split()
            if len(moves) < 2:
                continue
            board.push_uci(moves[0])
            if board.is_game_over() or _position_key(board) in seen_positions:
                continue
            return {
                "fen": board.fen(),
                "puzzle_id": puzzle["id"],
                "rating": puzzle["rating"],
                "theme": theme
                or next((t for t in (puzzle["themes"] or "").split() if t in OFFERED), None),
                "original_uci": None,
            }
    return None


def _delayed(db: Db, user_id: int, request: Request, now: float) -> tuple[dict | None, str | None]:
    # Existing M40 learned cards can also provide a source when there is no due session.
    anchors = db.execute(
        "SELECT 'session:' || id AS anchor, finished_at AS at, snapshot, NULL AS motif"
        " FROM training_sessions WHERE user_id = ? AND kind = 'practice' AND finished_at <= ?"
        " UNION ALL"
        " SELECT 'card:' || id || ':' || learned_at,"
        " CAST(strftime('%s', learned_at) AS INTEGER), NULL, motif"
        " FROM mistakes WHERE user_id = ? AND source = 'puzzle'"
        " AND CAST(strftime('%s', learned_at) AS INTEGER) <= ?"
        " AND CAST(strftime('%s', due_at) AS INTEGER) <= ?"
        " ORDER BY at DESC",
        (user_id, now - 7 * DAY, user_id, now - 7 * DAY, now),
    )
    notice = NOT_DUE
    for row in anchors:
        if db.execute(
            "SELECT 1 FROM training_sessions WHERE user_id = ? AND anchor = ?",
            (user_id, row["anchor"]),
        ).fetchone():
            continue
        theme = row["motif"]
        if row["snapshot"] is not None:
            slots = [
                slot
                for slot in json.loads(row["snapshot"])["slots"]
                if slot["first_uci"] is not None
            ]
            if not slots:
                continue
            source = next((slot for slot in slots if slot["theme"] is not None), slots[0])
            theme = source["theme"]
        exercise = _exercise(db, user_id, request, theme, basic=False)
        if exercise is not None:
            return {
                "anchor": row["anchor"],
                "delay_days": round((now - row["at"]) / DAY, 1),
                "exercise": exercise,
            }, None
        # Do not substitute a different theme for the most recent due source.
        notice = NO_DELAYED if theme else NO_EXERCISE
        break
    return None, notice


def _view(row: sqlite3.Row) -> dict:
    snapshot = json.loads(row["snapshot"])
    slots = snapshot["slots"]
    current = slots[snapshot["index"]]
    state = snapshot["state"]
    position = None
    if state != "done":
        is_game = current["puzzle_id"] is None
        position = {
            "fen": current["fen"],
            "side": "white" if chess.Board(current["fen"]).turn else "black",
            "source": "game" if is_game else "exercise",
            "novelty": "personal" if is_game else "new",
            "rating": current["rating"],
        }
        if current["hint"] is not None:
            position["hint"] = current["hint"]
    counts = {"assigned": len(slots), "unfinished": len(slots)}
    for key in ("independent", "assisted"):
        counts[key] = {"answered": 0, "correct": 0}
    for slot in slots:
        if slot["first_uci"] is not None:
            group = counts["assisted" if slot["hint"] or slot["revealed"] else "independent"]
            group["answered"] += 1
            group["correct"] += slot["feedback"]["correct"]
            counts["unfinished"] -= 1
    opened = slots[: snapshot["index"] + 1]
    ratings = [slot["rating"] for slot in opened if slot["rating"] is not None]
    return {
        "id": row["id"],
        "version": row["version"],
        "kind": row["kind"],
        "total": len(slots),
        "step": snapshot["index"] + 1,
        "state": state,
        "position": position,
        "feedback": current["feedback"] if state == "feedback" else None,
        "elapsed_ms": current["elapsed_ms"],
        "counts": counts,
        "new_positions": len(ratings),
        "delay_days": snapshot["delay_days"],
        "difficulty": {"min": min(ratings), "max": max(ratings)} if ratings else None,
        "notice": snapshot["notice"],
    }


@router.get("")
def training(db: Db, user_id: UserId, request: Request, expected_login: str | None = None) -> dict:
    _check_owner(db, user_id, expected_login)
    row = _session(db, user_id)
    delayed, notice = _delayed(db, user_id, request, time())
    return {
        "session": _view(row) if row else None,
        "delayed_available": delayed is not None,
        "delayed_notice": notice,
    }


@router.post("/start")
def start(body: Start, db: Db, user_id: UserId, request: Request) -> dict:
    _check_owner(db, user_id, body.expected_login)
    payload = body.model_dump_json()
    with db:
        db.execute("BEGIN IMMEDIATE")
        replay = _receipt(db, user_id, body.client_id, payload)
        if replay is not None:
            return _view(replay)
        latest = _session(db, user_id)
        if latest is not None and latest["finished_at"] is None:
            _save_receipt(db, user_id, body.client_id, latest["id"], payload)
            return _view(latest)

        now = time()
        anchor = delay_days = notice = None
        slots = []
        if body.kind == "delayed":
            delayed, notice = _delayed(db, user_id, request, now)
            if delayed is None:
                raise HTTPException(404, notice)
            anchor, delay_days = delayed["anchor"], delayed["delay_days"]
            slots.append(delayed["exercise"])
        else:
            error = db.execute(
                "SELECT * FROM mistake_events WHERE user_id = ? AND game_id IS NOT NULL"
                " ORDER BY game_id DESC, ply DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            theme = None
            if error is not None:
                theme = MOTIF_THEMES.get(error["motif"], error["motif"])
                theme = theme if theme in OFFERED else None
                slots.append(
                    {
                        "fen": error["fen"],
                        "puzzle_id": None,
                        "rating": None,
                        "theme": theme,
                        "original_uci": error["played_uci"],
                        "event_id": error["id"],
                        "start_fen": error["start_fen"],
                        "prefix_uci": error["prefix_uci"],
                    }
                )
            exercise = _exercise(db, user_id, request, theme, basic=error is None)
            if exercise is None and theme is not None:
                exercise = _exercise(db, user_id, request, None, basic=False)
            if exercise is not None:
                slots.append(exercise)
            elif not slots:
                raise HTTPException(404, NO_EXERCISE)
            else:
                notice = NO_EXERCISE
        for slot in slots:
            slot.update(first_uci=None, feedback=None, revealed=False, hint=None, elapsed_ms=None)
        snapshot = {
            "slots": slots,
            "index": 0,
            "opened_at": time(),
            "state": "question",
            "delay_days": delay_days,
            "notice": notice,
        }
        session_id = db.execute(
            "INSERT INTO training_sessions (user_id, kind, anchor, snapshot) VALUES (?, ?, ?, ?)",
            (user_id, body.kind, anchor, json.dumps(snapshot, ensure_ascii=False)),
        ).lastrowid
        _save_receipt(db, user_id, body.client_id, session_id, payload)
        return _view(_session(db, user_id, session_id))


def _feedback(request: Request, slot: dict, uci: str | None) -> dict:
    board = chess.Board(slot.get("start_fen", slot["fen"]))
    for ply in slot.get("prefix_uci", "").split():
        board.push_uci(ply)
    pool = request.app.state.pool
    settings = request.app.state.settings
    move = None
    if uci is not None:
        try:
            move = board.parse_uci(uci)
            if not move:
                raise ValueError("null move")
        except ValueError as exc:
            raise HTTPException(422, "Этот ход невозможен в данной позиции.") from exc
    original = slot["original_uci"]
    original_text = None
    try:
        if move is not None or original is not None:
            facts = build_facts(pool, board, move or board.parse_uci(original), settings)
            correct = (
                (
                    facts.classification == "best"
                    or (original is not None and facts.classification == "good")
                )
                if move is not None
                else None
            )
            text = explain(facts)
            mate = facts.eval_before.mate
            if original is None and move is not None and mate is not None and mate > 0:
                # Win chance does not distinguish two moves that both force mate.
                correct = facts.game_over == "checkmate" or move.uci() == facts.best_move.uci
                if not correct and mate > 1 and (facts.eval_after.mate or 0) > 0:
                    after = board.copy()
                    after.push(move)
                    _, lines = pool.analyse(after, settings.coach_depth)
                    if not lines:
                        raise EngineUnavailableError()
                    remaining = mover_view(lines[0]["score"], board.turn)["mate"]
                    # The score after the move counts only the attacker's remaining moves.
                    correct = remaining is not None and 0 < remaining < mate
                if not correct and facts.classification == "best":
                    text = f"Мат в {mate} начинается с хода {fig(facts.best_move.san)}."
            if original is not None and uci is not None and original != uci:
                original_text = explain(
                    build_facts(pool, board, board.parse_uci(original), settings)
                )
            walker = board.copy()
            if correct:
                line = [walker.push_uci(uci).uci()]
                line.extend(walker.push_san(san).uci() for san in facts.refutation)
            else:
                line = [walker.push_san(san).uci() for san in facts.best_line]
        else:
            _, lines = pool.analyse(board, settings.coach_depth)
            if not lines or not lines[0]["pv_uci"]:
                raise EngineUnavailableError()
            line = cut_line(board, lines[0]["pv_uci"])
            text = (
                f"Сильный ход — {fig(board.san(board.parse_uci(line[0])))}. Посмотрите продолжение."
            )
            correct = None
    except (EngineUnavailableError, chess.engine.EngineError, TimeoutError) as exc:
        raise HTTPException(503, "Stockfish недоступен. Повторите действие позже.") from exc
    feedback = {"correct": correct, "text": text, "line": line}
    if uci is not None:
        feedback["played_uci"] = uci
    if original is not None:
        feedback["original_uci"] = original
    if original_text is not None:
        feedback["original_text"] = original_text
    return feedback


@router.post("/{session_id}/action", dependencies=ENGINE_HEAVY)
def action(session_id: int, body: Action, db: Db, user_id: UserId, request: Request) -> dict:
    _check_owner(db, user_id, body.expected_login)
    payload = f"{session_id}:{body.model_dump_json()}"
    replay = _receipt(db, user_id, body.client_id, payload)
    if replay is not None:
        return _view(replay)
    row = _session(db, user_id, session_id)
    if row is None:
        raise HTTPException(404, "Занятие не найдено.")
    if row["version"] != body.version:
        # A concurrent duplicate may have committed after the first receipt read.
        replay = _receipt(db, user_id, body.client_id, payload)
        if replay is not None:
            return _view(replay)
        raise HTTPException(409, VERSION_CONFLICT)

    now = time()
    snapshot = json.loads(row["snapshot"])
    slot = snapshot["slots"][snapshot["index"]]
    state = snapshot["state"]
    finished = False
    if state == "done":
        raise HTTPException(409, "Занятие уже закончено.")
    if body.action == "finish":
        finished = True
        if state == "question":
            slot["elapsed_ms"] = round(max(0, now - snapshot["opened_at"]) * 1000)
    elif body.action == "next" and state == "feedback":
        finished = snapshot["index"] + 1 == len(snapshot["slots"])
        if not finished:
            snapshot.update(index=snapshot["index"] + 1, opened_at=now, state="question")
    elif body.action == "hint" and state == "question" and row["kind"] == "practice":
        slot["hint"] = "Проверьте шахи и взятия. Как соперник может ответить на ваш ход?"
    elif body.action in ("move", "reveal") and state == "question":
        slot["feedback"] = _feedback(request, slot, body.uci)
        slot["first_uci"] = body.uci
        slot["revealed"] = body.action == "reveal"
        slot["elapsed_ms"] = round(max(0, now - snapshot["opened_at"]) * 1000)
        snapshot["state"] = "feedback"
    else:
        raise HTTPException(409, "Это действие недоступно на текущем шаге.")
    if finished:
        snapshot["state"] = "done"
    # Engine analysis is outside the write transaction. Only one action can commit a version.
    with db:
        db.execute("BEGIN IMMEDIATE")
        replay = _receipt(db, user_id, body.client_id, payload)
        if replay is not None:
            return _view(replay)
        result = db.execute(
            "UPDATE training_sessions SET snapshot = ?, version = version + 1, finished_at = ?"
            " WHERE id = ? AND user_id = ? AND version = ?",
            (
                json.dumps(snapshot, ensure_ascii=False),
                now if finished else None,
                session_id,
                user_id,
                body.version,
            ),
        )
        if result.rowcount != 1:
            raise HTTPException(409, VERSION_CONFLICT)
        _save_receipt(db, user_id, body.client_id, session_id, payload)
        return _view(_session(db, user_id, session_id))
