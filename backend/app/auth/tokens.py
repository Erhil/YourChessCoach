import hashlib
import re
import secrets

# No 0/o, 1/l/i: a token is read aloud and typed on a phone.
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
TOKEN_LENGTH = 16
GROUP = 4


def new_token() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(TOKEN_LENGTH))
    return "-".join(raw[i : i + GROUP] for i in range(0, TOKEN_LENGTH, GROUP))


def normalize_token(token: str) -> str:
    return re.sub(r"[\s-]", "", token).lower()


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_token(token: str) -> str:
    return hash_secret(normalize_token(token))


def new_session_id() -> str:
    return secrets.token_urlsafe(32)
