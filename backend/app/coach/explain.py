"""One explanation chain: cache -> LLM -> validator -> template."""

import hashlib
import json
import logging
import sqlite3

from app.coach.prompt import CONTRACT_VERSION, build_messages
from app.coach.schema import CoachFacts
from app.coach.templates import explain
from app.coach.validator import render_response
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
    system, user = build_messages(facts)
    # All facts, trusted prose, catalog, and prompt changes invalidate old entries.
    key_src = json.dumps(
        [CONTRACT_VERSION, model, facts.model_dump(mode="json"), system, user],
        ensure_ascii=False,
        sort_keys=True,
    )
    key = hashlib.sha256(key_src.encode()).hexdigest()
    row = db.execute("SELECT text FROM llm_cache WHERE key = ?", (key,)).fetchone()
    if row:
        try:
            text = render_response(row["text"], facts)
            return {"text": text, "source": "llm", "model": model}
        except ValueError:
            log.info("cached LLM selection is invalid; dropped")
            with db:
                db.execute("DELETE FROM llm_cache WHERE key = ?", (key,))
    try:
        payload = llm.chat(system, user, model)
    except LLMError as exc:
        log.warning("LLM explanation skipped: %s", exc)
        return template
    try:
        text = render_response(payload, facts)
    except ValueError as exc:
        log.warning("LLM explanation rejected: %s", exc)
        return template
    with db:
        db.execute(
            "INSERT OR REPLACE INTO llm_cache (key, model, text, created_at)"
            " VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
            (key, model, payload),
        )
    return {"text": text, "source": "llm", "model": model}
