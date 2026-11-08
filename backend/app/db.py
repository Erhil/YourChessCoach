import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

# Ordered migration scripts. Index + 1 is the schema version (PRAGMA user_version).
# Later stages add tables by appending scripts. Never edit a script that has shipped.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE games (
        id INTEGER PRIMARY KEY,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
        player_color TEXT NOT NULL CHECK (player_color IN ('white', 'black')),
        level INTEGER,
        result TEXT NOT NULL CHECK (result IN ('1-0', '0-1', '1/2-1/2', '*')),
        termination TEXT,
        pgn TEXT NOT NULL,
        moves_count INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE puzzle_attempts (
        id INTEGER PRIMARY KEY,
        puzzle_id TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
        solved INTEGER NOT NULL,
        used_hint INTEGER NOT NULL,
        puzzle_rating INTEGER NOT NULL,
        rating_before REAL NOT NULL,
        rating_after REAL NOT NULL
    );
    CREATE TABLE user_ratings (
        scope TEXT PRIMARY KEY,
        rating REAL NOT NULL,
        attempts INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE lesson_progress (
        slug TEXT NOT NULL,
        position INTEGER NOT NULL,
        solved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
        PRIMARY KEY (slug, position)
    );
    """,
    """
    CREATE TABLE mistakes (
        id INTEGER PRIMARY KEY,
        source TEXT NOT NULL CHECK (source IN ('puzzle', 'game', 'play')),
        ref TEXT NOT NULL,
        fen TEXT NOT NULL,
        best_uci TEXT NOT NULL,
        best_san TEXT NOT NULL,
        classification TEXT,
        motif TEXT,
        created_at TEXT NOT NULL,
        box INTEGER NOT NULL,
        due_at TEXT NOT NULL,
        reviews INTEGER NOT NULL,
        lapses INTEGER NOT NULL,
        UNIQUE (source, ref)
    );
    CREATE INDEX mistakes_due ON mistakes (due_at);
    """,
    """
    CREATE TABLE llm_cache (
        key TEXT PRIMARY KEY,
        model TEXT NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE app_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """,
    """
    CREATE TABLE bench_votes (
        id INTEGER PRIMARY KEY,
        created_at TEXT NOT NULL,
        item_id TEXT NOT NULL,
        model_a TEXT NOT NULL,
        model_b TEXT NOT NULL,
        winner TEXT NOT NULL CHECK (winner IN ('a', 'b', 'tie'))
    );
    """,
    # The Leitner box is replaced by a count of right answers in a row; old cards restart at 0.
    """
    ALTER TABLE mistakes DROP COLUMN box;
    ALTER TABLE mistakes ADD COLUMN streak INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE mistakes ADD COLUMN learned_at TEXT;
    """,
    # Users and sessions. Rows with user_id NULL have no owner; the first user created takes them.
    # SQLite cannot change a key in place, so user_ratings, lesson_progress and mistakes are rebuilt.
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        login TEXT NOT NULL UNIQUE,
        token_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_seen_at TEXT
    );
    CREATE TABLE sessions (
        id_hash TEXT PRIMARY KEY,
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        admin INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
    CREATE INDEX sessions_user ON sessions (user_id);

    ALTER TABLE games ADD COLUMN user_id INTEGER REFERENCES users(id);
    CREATE INDEX games_user ON games (user_id, id);
    ALTER TABLE puzzle_attempts ADD COLUMN user_id INTEGER REFERENCES users(id);
    CREATE INDEX puzzle_attempts_user ON puzzle_attempts (user_id, id);

    CREATE TABLE user_ratings_new (
        user_id INTEGER REFERENCES users(id),
        scope TEXT NOT NULL,
        rating REAL NOT NULL,
        attempts INTEGER NOT NULL,
        UNIQUE (user_id, scope)
    );
    INSERT INTO user_ratings_new (scope, rating, attempts)
        SELECT scope, rating, attempts FROM user_ratings;
    DROP TABLE user_ratings;
    ALTER TABLE user_ratings_new RENAME TO user_ratings;

    CREATE TABLE lesson_progress_new (
        user_id INTEGER REFERENCES users(id),
        slug TEXT NOT NULL,
        position INTEGER NOT NULL,
        solved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
        UNIQUE (user_id, slug, position)
    );
    INSERT INTO lesson_progress_new (slug, position, solved_at)
        SELECT slug, position, solved_at FROM lesson_progress;
    DROP TABLE lesson_progress;
    ALTER TABLE lesson_progress_new RENAME TO lesson_progress;

    CREATE TABLE mistakes_new (
        id INTEGER PRIMARY KEY,
        user_id INTEGER REFERENCES users(id),
        source TEXT NOT NULL CHECK (source IN ('puzzle', 'game', 'play')),
        ref TEXT NOT NULL,
        fen TEXT NOT NULL,
        best_uci TEXT NOT NULL,
        best_san TEXT NOT NULL,
        classification TEXT,
        motif TEXT,
        created_at TEXT NOT NULL,
        due_at TEXT NOT NULL,
        reviews INTEGER NOT NULL,
        lapses INTEGER NOT NULL,
        streak INTEGER NOT NULL DEFAULT 0,
        learned_at TEXT,
        UNIQUE (user_id, source, ref)
    );
    INSERT INTO mistakes_new (id, source, ref, fen, best_uci, best_san, classification, motif,
                              created_at, due_at, reviews, lapses, streak, learned_at)
        SELECT id, source, ref, fen, best_uci, best_san, classification, motif,
               created_at, due_at, reviews, lapses, streak, learned_at FROM mistakes;
    DROP TABLE mistakes;
    ALTER TABLE mistakes_new RENAME TO mistakes;
    CREATE INDEX mistakes_due ON mistakes (user_id, due_at);
    """,
    # A separate MCP key per user (SHA-256 only) and the plans the senior coach saves.
    """
    ALTER TABLE users ADD COLUMN mcp_key_hash TEXT;
    ALTER TABLE users ADD COLUMN mcp_key_created_at TEXT;
    CREATE UNIQUE INDEX users_mcp_key ON users (mcp_key_hash) WHERE mcp_key_hash IS NOT NULL;
    CREATE TABLE plans (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        summary TEXT NOT NULL,
        focus_themes TEXT NOT NULL,
        lessons TEXT NOT NULL,
        openings TEXT NOT NULL
    );
    CREATE INDEX plans_user ON plans (user_id, id);
    """,
    # A log of deck answers (active days), achievements (filled later), the weekly goal and
    # the count of the player's blunders in a game (NULL: unknown, old games and old clients).
    """
    CREATE TABLE card_reviews (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        mistake_id INTEGER NOT NULL,
        correct INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
    );
    CREATE INDEX card_reviews_user ON card_reviews (user_id, created_at);
    CREATE TABLE achievements (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        key TEXT NOT NULL,
        earned_at TEXT NOT NULL,
        seen INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, key)
    );
    ALTER TABLE users ADD COLUMN week_goal INTEGER NOT NULL DEFAULT 3 CHECK (week_goal IN (3, 4, 5));
    ALTER TABLE games ADD COLUMN blunders INTEGER;
    """,
    # Takebacks and coach hints in a game; a game with any of them is a training game.
    """
    ALTER TABLE games ADD COLUMN takebacks INTEGER NOT NULL DEFAULT 0 CHECK (takebacks >= 0);
    ALTER TABLE games ADD COLUMN hints INTEGER NOT NULL DEFAULT 0 CHECK (hints >= 0);
    """,
    # The move the player made in the game; NULL for puzzle cards and old cards.
    """
    ALTER TABLE mistakes ADD COLUMN played_uci TEXT;
    """,
    # A client retries the same save after an uncertain network response.
    """
    ALTER TABLE games ADD COLUMN client_id TEXT;
    CREATE UNIQUE INDEX games_client_id ON games(user_id, client_id);
    """,
    # Store the exact response for an idempotent puzzle result retry.
    """
    CREATE TABLE puzzle_receipts (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        client_id TEXT NOT NULL,
        puzzle_id TEXT NOT NULL,
        solved INTEGER NOT NULL,
        used_hint INTEGER NOT NULL,
        response TEXT NOT NULL,
        PRIMARY KEY (user_id, client_id)
    );
    """,
    # Resume old learned cards gradually, preserving their milestone and streak.
    """
    UPDATE mistakes SET due_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now',
        '+' || (7 + id % 54) || ' days')
    WHERE learned_at IS NOT NULL;
    """,
    """
    ALTER TABLE mistakes ADD COLUMN review_version INTEGER NOT NULL DEFAULT 0;
    UPDATE mistakes SET review_version = reviews;
    ALTER TABLE games ADD COLUMN mistakes_reviewed INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE puzzle_attempts ADD COLUMN details TEXT;
    ALTER TABLE puzzle_receipts ADD COLUMN attempt_id INTEGER REFERENCES puzzle_attempts(id);
    CREATE TABLE mistake_events (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        game_id INTEGER REFERENCES games(id),
        attempt_id INTEGER REFERENCES puzzle_attempts(id),
        ply INTEGER NOT NULL CHECK (ply > 0),
        card_id INTEGER NOT NULL REFERENCES mistakes(id),
        origin TEXT NOT NULL CHECK (origin IN ('play', 'review', 'puzzle')),
        start_fen TEXT NOT NULL,
        fen TEXT NOT NULL,
        prefix_uci TEXT NOT NULL,
        played_uci TEXT,
        best_uci TEXT NOT NULL,
        continuation_uci TEXT NOT NULL,
        classification TEXT,
        motif TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
        CHECK ((game_id IS NULL) != (attempt_id IS NULL)),
        UNIQUE (user_id, game_id, ply),
        UNIQUE (user_id, attempt_id, ply)
    );
    CREATE INDEX mistake_events_card ON mistake_events(card_id);
    """,
    """
    CREATE TABLE training_sessions (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        kind TEXT NOT NULL CHECK (kind IN ('practice', 'delayed')),
        version INTEGER NOT NULL DEFAULT 1,
        anchor TEXT,
        finished_at REAL,
        snapshot TEXT NOT NULL,
        UNIQUE (user_id, anchor)
    );
    CREATE INDEX training_sessions_user ON training_sessions(user_id, id);
    CREATE UNIQUE INDEX training_sessions_active ON training_sessions(user_id)
        WHERE finished_at IS NULL;
    CREATE TABLE training_receipts (
        user_id INTEGER NOT NULL REFERENCES users(id),
        client_id TEXT NOT NULL,
        session_id INTEGER NOT NULL REFERENCES training_sessions(id),
        request TEXT NOT NULL,
        PRIMARY KEY (user_id, client_id)
    );
    """,
]

# A training game (takebacks or hints): it does not count in wins, losses and game achievements.
TRAINING_GAME = "(takebacks > 0 OR hints > 0)"


_migrated: set[Path] = set()
_migrate_lock = threading.Lock()


def connect(path: Path) -> sqlite3.Connection:
    """Open the app database. The first open of a path in this process runs the migrations."""
    path = Path(path)
    if path not in _migrated or not path.exists():
        with _migrate_lock:
            if path not in _migrated or not path.exists():
                migrate(path)
                _migrated.add(path)
    return _open(path)


def _open(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI may open a sync dependency in one thread and close it in another;
    # each connection still serves only one request at a time.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(path: Path) -> None:
    conn = _open(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for number, script in enumerate(MIGRATIONS, start=1):
            if number <= version:
                continue
            # executescript commits first, so wrap the script and the version in one explicit transaction.
            conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;")
    finally:
        conn.close()


def verified_copy(source: Path, target: Path) -> Path:
    """Create a new consistent database; refuse replacement and invalid input."""
    source, target = Path(source).resolve(), Path(target).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also protects against concurrent CLI invocations.
    with target.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            if src.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Source database integrity check failed")
            with closing(sqlite3.connect(target)) as dst:
                deadline = time.monotonic() + 30

                def progress(status, remaining, total):
                    if time.monotonic() > deadline:
                        raise TimeoutError("SQLite backup exceeded 30 seconds")

                src.backup(dst, pages=256, progress=progress)
        with closing(sqlite3.connect(target)) as restored:
            if restored.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Restored database integrity check failed")
            # Read every restored table, including application rows.
            for (table,) in restored.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                for _ in restored.execute('SELECT * FROM "' + table.replace('"', '""') + '"'):
                    pass
        return target
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def backup(path: Path, keep: int = 7, folder: Path | None = None) -> Path | None:
    """Save a verified SQLite snapshot and retain the latest copies for this database."""
    path = Path(path)
    if not path.is_file():
        return None
    if keep < 1:
        raise ValueError("keep must be positive")
    folder = folder or path.parent / "backups"
    target = folder / f"{path.stem}-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    verified_copy(path, target)
    for old in sorted(folder.glob(f"{path.stem}-*.db"))[:-keep]:
        old.unlink()
    return target


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.settings.app_db_path)
    try:
        yield conn
    finally:
        conn.close()


Db = Annotated[sqlite3.Connection, Depends(get_db)]
