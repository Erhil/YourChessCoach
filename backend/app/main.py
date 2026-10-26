from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from app.activity.routes import achievements_router
from app.activity.routes import router as activity_router
from app.auth import service
from app.auth.deps import USER_COOKIE, current_user_id, require_admin
from app.auth.routes import admin_router, key_router
from app.auth.routes import router as auth_router
from app.bench.routes import router as bench_router
from app.coach.routes import router as coach_router
from app.config import Settings
from app.config import settings as default_settings
from app.db import backup, connect, migrate
from app.engines.locate import find_binary
from app.engines.opponent import Opponent
from app.engines.opponent_routes import router as opponent_router
from app.engines.pool import EnginePool
from app.engines.routes import router as engines_router
from app.games.routes import router as games_router
from app.lessons.routes import router as lessons_router
from app.llm.client import OllamaClient
from app.mcp.plan import router as plan_router
from app.mcp.server import router as mcp_router
from app.mistakes.routes import router as mistakes_router
from app.openings.routes import router as openings_router
from app.progress.routes import router as progress_router
from app.puzzles.routes import router as puzzles_router
from app.review.routes import router as review_router
from app.security import install as install_security

NOT_BUILT = "Фронтенд не собран: запустите python scripts/run.py"


def create_app(settings: Settings = default_settings) -> FastAPI:
    pool = EnginePool(
        settings.engines_dir,
        settings.engine_pool_size,
        settings.stockfish_threads,
        settings.stockfish_hash,
    )

    opponent = Opponent(settings.engines_dir)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        backup(settings.app_db_path)
        migrate(settings.app_db_path)
        yield
        try:
            pool.close()
        finally:
            opponent.close()

    app = FastAPI(
        title="chess-coach", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.pool = pool
    app.state.opponent = opponent
    app.state.settings = settings
    app.state.llm = OllamaClient(settings.llm_base_url, settings.llm_timeout_s)
    install_security(app, settings)
    app.include_router(auth_router)
    app.include_router(admin_router)
    # Every data router needs a user session; handlers that read or write data also take UserId.
    user_only = [Depends(current_user_id)]
    for router in (
        games_router,
        engines_router,
        opponent_router,
        puzzles_router,
        openings_router,
        lessons_router,
        coach_router,
        review_router,
        mistakes_router,
        progress_router,
        plan_router,
        key_router,
        activity_router,
        achievements_router,
    ):
        app.include_router(router, dependencies=user_only)
    # /mcp has its own authentication: a bearer key, never the cookie session.
    app.include_router(mcp_router)
    # Bench changes the global default model: admin only (its URL is under /api/admin for the cookie path).
    app.include_router(bench_router, dependencies=[Depends(require_admin)])

    @app.get("/api/health")
    def health(request: Request) -> dict:
        """Without a user session: status and version only. Details need a login."""
        short = {"status": "ok", "version": settings.app_version}
        db = connect(settings.app_db_path)
        try:
            known = service.resolve_session(db, request.cookies.get(USER_COOKIE), admin=False)
        finally:
            db.close()
        if known is None:
            return short
        path = find_binary(settings.engines_dir, "stockfish")
        return {
            **short,
            "engines": {"stockfish": {"available": path is not None}},
            "llm": {
                "enabled": settings.llm_enabled,
                "available": settings.llm_enabled and app.state.llm.available(),
            },
        }

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        # API paths and .well-known (MCP clients probe it for OAuth) never get the app page.
        if path in ("api", "mcp") or path.startswith(("api/", ".well-known/")):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        dist = settings.frontend_dist.resolve()
        index = dist / "index.html"
        if not index.is_file():
            return PlainTextResponse(NOT_BUILT, status_code=404)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist):
            return FileResponse(candidate)
        return FileResponse(index)

    return app


app = create_app()
