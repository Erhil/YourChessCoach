"""One explanation chain: cache -> LLM -> validator -> template."""

import hashlib
import logging
import sqlite3

from app.coach.prompt import build_messages
from app.coach.schema import CoachFacts
from app.coach.templates import explain
from app.coach.validator import to_display, validate
from app.config import Settings
from app.llm.client import LLMClient, LLMError

log = logging.getLogger("app.coach.explain")


TEMPLATE_MODEL = "template"  # pseudo-model: always the template text, no LLM call


def current_model(db: sqlite3.Connection, settings: Settings) -> str:
    row = db.execute("SELECT value FROM app_settings WHERE key = 'llm_model'").fetchone()
    return row["value"] if row and row["value"] else settings.llm_model


def explain_facts(
    facts: CoachFacts, db: sqlite3.Connection, llm: LLMClient, settings: Settings
) -> dict:
    template = {"text": explain(facts), "source": "template", "model": None}
    if not settings.llm_enabled:
        return template
    model = current_model(db, settings)
    if model == TEMPLATE_MODEL:
        return template
    # The best move and the reply are in the key: Stockfish can pick another best move next time,
    # and a cached text must name the same moves as the arrows drawn from the new facts.
    best = facts.best_move.uci if facts.best_move else ""
    reply = facts.refutation[0] if facts.refutation else ""
    key_src = f"{facts.fen_before}\n{facts.player_move.uci}\n{model}\n{best}\n{reply}"
    key = hashlib.sha256(key_src.encode()).hexdigest()
    row = db.execute("SELECT text FROM llm_cache WHERE key = ?", (key,)).fetchone()
    if row:
        if not validate(row["text"], facts):
            return {"text": row["text"], "source": "llm", "model": model}
        log.info("cached LLM explanation does not fit the new facts; dropped")
        with db:
            db.execute("DELETE FROM llm_cache WHERE key = ?", (key,))
    try:
        system, user = build_messages(facts)
        text = llm.chat(system, user, model)
    except LLMError as exc:
        log.warning("LLM explanation skipped: %s", exc)
        return template
    reasons = validate(text, facts)
    if reasons:
        log.warning("LLM explanation rejected: %s", "; ".join(reasons))
        return template
    text = to_display(text)
    with db:
        db.execute(
            "INSERT OR REPLACE INTO llm_cache (key, model, text, created_at)"
            " VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
            (key, model, text),
        )
    return {"text": text, "source": "llm", "model": model}
