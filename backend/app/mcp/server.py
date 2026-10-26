"""A small MCP server over Streamable HTTP: JSON-RPC in a POST, JSON out, no sessions, no SSE.

Why not the official SDK: its server wants its own ASGI app, lifespan and host checks, and the
user id must reach each tool call. Here the route owns authentication (bearer key -> user id)
and the surface is six tools and one prompt. Clients that speak Streamable HTTP work with it.
"""

import json
import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.auth import service
from app.db import connect
from app.mcp import tools
from app.mcp.tools import Ctx, ToolError
from app.security import TOO_MANY_LOGINS, client_ip, limiter_ip

log = logging.getLogger("app.mcp")
router = APIRouter()

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "chess-coach", "version": "1.0"}
BAD_KEY = "Нужен ключ MCP: заголовок Authorization: Bearer <ключ>"

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602

INSTRUCTIONS = (
    "Senior coach for one chess beginner. Call get_profile first. Every chess claim must come from "
    "review_game or analyse_position (Stockfish), never from your own calculation. You only read "
    "data and save one plan with save_plan."
)

READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
_STR_LIST = {"type": "array", "items": {"type": "string"}}
TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_profile",
        "description": (
            "Profile of the player: games (results by color and level without training games; "
            "count of all games and of finished training games), openings played (games include "
            "training games; wins, losses and draws do not; training is their count), "
            "mistakes deck by motif, puzzle ratings by theme (weakest first), lessons done and "
            "not done, activity (this week: goal, active days, met, streak_weeks; the last active "
            "date; active days in the last 28 days; titles of the achievements that the app "
            "awarded; server time zone), the current plan, and the valid values for save_plan."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"title": "Player profile", **READ_ONLY},
    },
    {
        "name": "list_games",
        "description": (
            "Latest games of the player: id, date, color, level, result, plies, opening, "
            "takebacks, hints, training (true: the game has takebacks or hints; its result "
            "does not count)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
        },
        "annotations": {"title": "List games", **READ_ONLY},
    },
    {
        "name": "review_game",
        "description": (
            "Engine review of one game of the player: bad moves and key moments with the best "
            "move, the engine line and a short explanation; training, takebacks and hints of the "
            "game. Slow: it runs Stockfish."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"game_id": {"type": "integer"}},
            "required": ["game_id"],
        },
        "annotations": {"title": "Review a game", **READ_ONLY},
    },
    {
        "name": "analyse_position",
        "description": (
            "Stockfish: top 3 lines of a position (FEN) with SAN moves, evaluation in words for a "
            "beginner and in cp/mate (White point of view)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "fen": {"type": "string"},
                "depth": {"type": "integer", "minimum": 1, "maximum": tools.MAX_DEPTH},
            },
            "required": ["fen"],
        },
        "annotations": {"title": "Analyse a position", **READ_ONLY},
    },
    {
        "name": "get_plan",
        "description": "The latest saved plan of the player, or null.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"title": "Current plan", **READ_ONLY},
    },
    {
        "name": "save_plan",
        "description": (
            "Save a new plan (older plans stay in history). The app shows it on the Today page. "
            "Use only values from get_profile.valid_values_for_save_plan. "
            f"summary: a short text for a beginner, at most {tools.MAX_SUMMARY} characters."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "maxLength": tools.MAX_SUMMARY},
                "focus_themes": {**_STR_LIST, "maxItems": tools.MAX_THEMES},
                "lessons": {**_STR_LIST, "maxItems": tools.MAX_LESSONS},
                "openings": {**_STR_LIST, "maxItems": tools.MAX_OPENINGS},
            },
            "required": ["summary", "focus_themes", "lessons", "openings"],
        },
        "annotations": {
            "title": "Save plan",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    },
]

WEEKLY_REVIEW = """Ты — старший шахматный тренер для начинающего. Сделай недельный разбор.

1. Вызови get_profile: партии, дебюты, колода ошибок, рейтинги по темам, уроки, текущий план.
2. Вызови list_games и разбери 3–5 последних партий через review_game.
3. Найди повторяющиеся слабые места: мотивы ошибок, фаза партии, дебюты. Тренировочная партия \
(training: true) — партия с возвратом хода или подсказкой тренера. Её результат не учитывай, \
а её ошибки используй для плана: они тоже полезны.
4. Все шахматные утверждения бери только из инструментов (review_game, analyse_position). \
Свой расчёт не выдавай за факт.
5. Вызови save_plan: краткая сводка для новичка простыми словами (что получается, что \
исправить, 2–4 предложения), до 3 тем, до 6 уроков, до 3 дебютов. Бери значения только из \
get_profile.valid_values_for_save_plan.
6. Коротко перескажи план человеку."""

PROMPTS: list[dict[str, Any]] = [
    {
        "name": "weekly_review",
        "title": "Недельный разбор",
        "description": "Разобрать последние партии, найти слабые места и сохранить план.",
        "arguments": [],
    }
]


def _tool_result(data: Any, is_error: bool = False) -> dict:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _call_tool(ctx: Ctx, params: dict) -> dict:
    name, args = params.get("name"), params.get("arguments") or {}
    if not isinstance(name, str):
        raise RpcError(INVALID_PARAMS, "name must be a string")
    impl = {
        "get_profile": tools.get_profile,
        "list_games": tools.list_games,
        "review_game": tools.review_game,
        "analyse_position": tools.analyse_position,
        "get_plan": tools.get_plan,
        "save_plan": tools.save_plan,
    }.get(name)
    if impl is None:
        raise RpcError(INVALID_PARAMS, f"Unknown tool: {name}")
    if not isinstance(args, dict):
        raise RpcError(INVALID_PARAMS, "arguments must be an object")
    try:
        return _tool_result(impl(ctx, **args))
    except ToolError as exc:
        return _tool_result(str(exc), is_error=True)
    except TypeError as exc:  # missing or unknown argument
        return _tool_result(f"Bad arguments: {exc}", is_error=True)
    except (ValueError, OverflowError, sqlite3.Error) as exc:
        log.exception("MCP tool %s failed", name)
        return _tool_result(f"Tool failed: {exc}", is_error=True)


class RpcError(Exception):
    def __init__(self, code: int, message: str):
        self.code, self.message = code, message


def _dispatch(ctx: Ctx, method: str, params: dict) -> dict:
    if method == "initialize":
        asked = params.get("protocolVersion")
        return {
            "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {"listChanged": False}, "prompts": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        return _call_tool(ctx, params)
    if method == "prompts/list":
        return {"prompts": PROMPTS}
    if method == "prompts/get":
        if params.get("name") != "weekly_review":
            raise RpcError(INVALID_PARAMS, f"Unknown prompt: {params.get('name')}")
        return {
            "description": PROMPTS[0]["description"],
            "messages": [{"role": "user", "content": {"type": "text", "text": WEEKLY_REVIEW}}],
        }
    raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")


def _handle_one(ctx: Ctx, message: Any) -> dict | None:
    """One JSON-RPC message -> its response, or None for a notification or a stray response."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, INVALID_REQUEST, "Not a JSON-RPC 2.0 message")
    method, msg_id = message.get("method"), message.get("id")
    if method is None:  # a response to a server request: this server sends none
        return None
    if not isinstance(method, str):
        return _error(msg_id, INVALID_REQUEST, "method must be a string")
    if "id" not in message:  # notification (for example notifications/initialized)
        return None
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return _error(msg_id, INVALID_PARAMS, "params must be an object")
    try:
        return {"jsonrpc": "2.0", "id": msg_id, "result": _dispatch(ctx, method, params)}
    except RpcError as exc:
        return _error(msg_id, exc.code, exc.message)
    except (TypeError, ValueError, OverflowError) as exc:
        log.exception("MCP method %s failed", method)
        return _error(msg_id, INVALID_PARAMS, f"Bad parameters: {exc}")


def _error(msg_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _bearer(request: Request) -> str | None:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    value = value.strip()
    return value if scheme.lower() == "bearer" and value else None


def _auth_failure(status: int, detail: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status, headers=headers)


def _authenticate(app: FastAPI, key: str) -> int | None:
    db = connect(app.state.settings.app_db_path)
    try:
        return service.resolve_mcp_key(db, key)
    finally:
        db.close()


def _process(app: FastAPI, user_id: int, payload: Any) -> Any:
    """Runs in a worker thread with its own database connection."""
    db = connect(app.state.settings.app_db_path)
    try:
        ctx = Ctx(app, db, user_id)
        if isinstance(payload, list):  # batches were removed in MCP 2025-06-18
            return _error(None, INVALID_REQUEST, "Batch requests are not supported")
        return _handle_one(ctx, payload)
    finally:
        db.close()


@router.post("/mcp")
async def mcp_post(request: Request) -> Response:
    app = request.app
    limiter = app.state.login_limiter
    keys = [f"mcp-ip:{limiter_ip(client_ip(request))}"]  # not the browser login key "ip:"
    try:
        limiter.guard(keys)
    except HTTPException as exc:
        return _auth_failure(exc.status_code, TOO_MANY_LOGINS, exc.headers)
    challenge = {"WWW-Authenticate": "Bearer"}
    key = _bearer(request)
    if key is None:
        return _auth_failure(401, BAD_KEY, challenge)
    user_id = await run_in_threadpool(_authenticate, app, key)
    if user_id is None:
        limiter.fail(keys)
        return _auth_failure(401, BAD_KEY, challenge)
    try:
        payload = json.loads(await request.body())
    except ValueError:
        return JSONResponse(_error(None, PARSE_ERROR, "Parse error"), status_code=400)
    body = await run_in_threadpool(_process, app, user_id, payload)
    return Response(status_code=202) if body is None else JSONResponse(body)


@router.api_route("/mcp", methods=["GET", "DELETE"])
def mcp_no_stream() -> Response:
    """This server has no server-to-client stream and no sessions."""
    return Response(status_code=405, headers={"Allow": "POST"})
