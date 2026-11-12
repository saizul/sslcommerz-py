"""Removes credentials from data that ends up in errors and logs."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

SENSITIVE_KEYS = frozenset({"store_passwd", "store_password", "password", "verify_sign"})
REDACTED = "[REDACTED]"


def redact(data: Any, secrets: Iterable[str] = ()) -> Any:
    """Deep copy of ``data`` with sensitive keys and secret values replaced."""
    secret_list = [s for s in secrets if s and len(s) >= 4]
    return _walk(data, secret_list)


def _walk(value: Any, secrets: list) -> Any:
    if isinstance(value, Mapping):
        return {k: REDACTED if str(k).lower() in SENSITIVE_KEYS else _walk(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, secrets) for v in value]
    if isinstance(value, str):
        for s in secrets:
            value = value.replace(s, REDACTED)
        return value
    return value


def mask_card(card_no: str) -> str:
    """Keep only the last four characters of a card or account number."""
    if not card_no:
        return card_no
    tail = card_no[-4:]
    return "*" * max(0, len(card_no) - 4) + tail
