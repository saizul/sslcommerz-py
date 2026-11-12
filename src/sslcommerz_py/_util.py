"""Small parsing and validation helpers."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Union
from urllib.parse import urlparse

from .errors import ValidationError

AmountLike = Union[Decimal, str, int, float]

_AMOUNT_RE = re.compile(r"^\d+(\.\d{1,2})?$")
_TWO_PLACES = Decimal("0.01")


def to_decimal(value: Any) -> Optional[Decimal]:
    """Parse a gateway amount ("103.00", 103, None) into a Decimal."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def to_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def to_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value)
    return s if s != "" else None


def format_amount(field: str, value: AmountLike) -> str:
    """Format an amount as the 2-decimal string the gateway expects.

    Floats are accepted but must already have at most two decimals, so that
    rounding never silently changes what the customer pays.
    """
    if isinstance(value, bool):
        raise ValidationError(field, "must be a number")
    if isinstance(value, float):
        d = Decimal(repr(value))
    elif isinstance(value, (int, Decimal)):
        d = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        if not _AMOUNT_RE.match(text):
            raise ValidationError(field, "must be a decimal with at most two places, e.g. '120.50'")
        d = Decimal(text)
    else:
        raise ValidationError(field, "must be a number or numeric string")
    if not d.is_finite():
        raise ValidationError(field, "must be finite")
    if d != d.quantize(_TWO_PLACES):
        raise ValidationError(field, "must have at most two decimal places")
    if d <= 0:
        raise ValidationError(field, "must be greater than zero")
    return str(d.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))


def require_text(field: str, value: Any, max_length: Optional[int] = None) -> str:
    if value is None or not str(value).strip():
        raise ValidationError(field, "is required")
    text = str(value)
    if max_length is not None and len(text) > max_length:
        raise ValidationError(field, f"must be at most {max_length} characters")
    return text


def optional_text(field: str, value: Any, max_length: Optional[int] = None) -> Optional[str]:
    if value is None or value == "":
        return None
    return require_text(field, value, max_length)


def require_url(field: str, value: Any) -> str:
    text = require_text(field, value, 255)
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValidationError(field, "must be an absolute http(s) URL")
    return text


def first(payload: Mapping[str, Any], key: str) -> Any:
    """Read a form value that may be a list (e.g. from ``parse_qs``)."""
    v = payload.get(key)
    if isinstance(v, (list, tuple)):
        return v[0] if v else None
    return v
