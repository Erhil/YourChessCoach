import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _flag(value: str) -> bool:
    return value.lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    app_host: str
    app_port: int
    app_version: str
    app_data_dir: Path
    app_db_path: Path
    puzzles_db_path: Path
    engines_dir: Path
    frontend_dist: Path
    lessons_dir: Path
    stockfish_threads: int
    stockfish_hash: int
    engine_pool_size: int
    analysis_movetime_ms: int
    coach_depth: int
    review_depth: int
    coach_inaccuracy: float
    coach_mistake: float
    coach_blunder: float
    llm_enabled: bool
    llm_base_url: str
    llm_model: str
    llm_timeout_s: float
    admin_token: str
    cookie_secure: bool
    ssl_certfile: str
    ssl_keyfile: str
    trust_proxy: bool
    backup_interval_s: float
    backup_dir: Path | None
    engine_requests_per_user: int


def load_settings() -> Settings:
    env = {**_read_dotenv(REPO_ROOT / ".env"), **os.environ}
    data_dir = Path(env.get("APP_DATA_DIR", REPO_ROOT / "data"))
    certfile, keyfile = env.get("APP_SSL_CERTFILE", ""), env.get("APP_SSL_KEYFILE", "")
    ssl_on = bool(certfile and keyfile)
    return Settings(
        app_host=env.get("APP_HOST", "0.0.0.0"),
        app_port=int(env.get("APP_PORT", 6355)),
        app_version=env.get("APP_VERSION", "dev"),
        app_data_dir=data_dir,
        app_db_path=Path(env.get("APP_DB_PATH", data_dir / "app.db")),
        puzzles_db_path=Path(env.get("PUZZLES_DB_PATH", data_dir / "puzzles.db")),
        engines_dir=Path(env.get("ENGINES_DIR", REPO_ROOT / "engines")),
        frontend_dist=Path(env.get("FRONTEND_DIST", REPO_ROOT / "frontend" / "dist")),
        lessons_dir=Path(env.get("LESSONS_DIR", REPO_ROOT / "content" / "lessons")),
        stockfish_threads=int(env.get("STOCKFISH_THREADS", 4)),
        stockfish_hash=int(env.get("STOCKFISH_HASH", 256)),
        engine_pool_size=int(env.get("ENGINE_POOL_SIZE", 2)),
        analysis_movetime_ms=int(env.get("ANALYSIS_MOVETIME_MS", 500)),
        coach_depth=int(env.get("COACH_DEPTH", 14)),
        review_depth=int(env.get("REVIEW_DEPTH", 12)),
        coach_inaccuracy=float(env.get("COACH_INACCURACY", 0.10)),
        coach_mistake=float(env.get("COACH_MISTAKE", 0.20)),
        coach_blunder=float(env.get("COACH_BLUNDER", 0.30)),
        llm_enabled=env.get("LLM_ENABLED", "true").lower() not in ("0", "false", "no", "off"),
        llm_base_url=env.get("LLM_BASE_URL", "http://localhost:11434"),
        llm_model=env.get("LLM_MODEL", "qwen3.5:4b"),
        llm_timeout_s=float(env.get("LLM_TIMEOUT_S", 20)),
        admin_token=env.get("ADMIN_TOKEN", ""),
        # Secure cookies and HSTS are on by default when uvicorn serves TLS itself.
        cookie_secure=_flag(env.get("COOKIE_SECURE", "true" if ssl_on else "false")),
        ssl_certfile=certfile,
        ssl_keyfile=keyfile,
        trust_proxy=_flag(env.get("TRUST_PROXY", "false")),
        backup_interval_s=max(0.01, float(env.get("BACKUP_INTERVAL_S", 21600))),
        backup_dir=Path(env["BACKUP_DIR"]) if env.get("BACKUP_DIR") else None,
        engine_requests_per_user=int(env.get("ENGINE_REQUESTS_PER_USER", 3)),
    )


settings = load_settings()
