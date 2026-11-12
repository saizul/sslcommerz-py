"""``verify_sign`` / ``verify_key`` checks for IPN and redirect payloads.

SSLCommerz signs the fields it posts back. ``verify_key`` is a comma
separated list of the signed field names and ``verify_sign`` is::

    md5("k1=v1&k2=v2&...")

over those fields plus ``store_passwd=md5(<your store password>)``, with the
keys sorted in byte order. This follows the hash check in the official
SSLCommerz PHP library (``SSLCOMMERZ_hash_verify``).
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Mapping, Optional

from .errors import HashVerificationError


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()  # noqa: S324 - mandated by the gateway


def _value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return _value(v[0]) if v else ""
    return str(v)


def build_hash_string(payload: Mapping[str, Any], store_passwd: str, verify_key: Optional[str] = None) -> str:
    """The exact string that is md5-hashed into ``verify_sign``."""
    key_list = verify_key if verify_key is not None else _value(payload.get("verify_key"))
    keys = [k for k in (part.strip() for part in key_list.split(",")) if k]
    data = {k: _value(payload.get(k)) for k in keys}
    data["store_passwd"] = _md5(store_passwd)
    return "&".join(f"{k}={data[k]}" for k in sorted(data))


def compute_signature(payload: Mapping[str, Any], store_passwd: str, verify_key: Optional[str] = None) -> str:
    """``verify_sign`` value for ``payload``. Useful for tests and fixtures."""
    return _md5(build_hash_string(payload, store_passwd, verify_key))


def verify_signature(payload: Mapping[str, Any], store_passwd: str) -> bool:
    """True when ``payload['verify_sign']`` matches the signed fields."""
    sign = _value(payload.get("verify_sign")).strip().lower()
    key = _value(payload.get("verify_key")).strip()
    if not sign or not key:
        return False
    return hmac.compare_digest(compute_signature(payload, store_passwd), sign)


def require_valid_signature(payload: Mapping[str, Any], store_passwd: str) -> None:
    """Raise :class:`HashVerificationError` unless the signature matches."""
    if not _value(payload.get("verify_sign")) or not _value(payload.get("verify_key")):
        raise HashVerificationError("Payload has no verify_sign/verify_key")
    if not verify_signature(payload, store_passwd):
        raise HashVerificationError("verify_sign does not match the posted fields")
