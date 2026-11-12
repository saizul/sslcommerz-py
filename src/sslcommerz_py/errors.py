"""Exception hierarchy.

Every exception raised by this package derives from :class:`SSLCommerzError`.
"""

from __future__ import annotations

import builtins
from typing import Any, Mapping, Optional


class SSLCommerzError(Exception):
    """Base class for all SDK errors."""

    def __init__(self, message: str, *, raw: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        #: Response body (credentials removed), when there was one.
        self.raw = dict(raw) if raw is not None else None

    #: Whether repeating the same call may succeed.
    retryable = False


class ConfigurationError(SSLCommerzError):
    """Missing or invalid client configuration."""


class ValidationError(SSLCommerzError, ValueError):
    """Input rejected locally before any request was sent."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field


class NetworkError(SSLCommerzError):
    """No HTTP response was received (DNS, TCP, TLS)."""

    retryable = True


class TimeoutError(NetworkError, builtins.TimeoutError):
    """No response within the configured timeout. The outcome is unknown."""


class ResponseError(SSLCommerzError):
    """The response was not valid JSON or had an unexpected HTTP status."""

    def __init__(
        self, message: str, *, status_code: Optional[int] = None, raw: Optional[Mapping[str, Any]] = None
    ) -> None:
        super().__init__(message, raw=raw)
        self.status_code = status_code

    @property
    def retryable(self) -> bool:  # type: ignore[override]
        return self.status_code is not None and self.status_code >= 500


class APIConnectError(SSLCommerzError):
    """``APIConnect`` was not ``DONE``."""

    def __init__(self, api_connect: str, message: str, *, raw: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message, raw=raw)
        self.api_connect = api_connect


class InvalidRequestError(APIConnectError):
    """``APIConnect=INVALID_REQUEST``: missing or malformed parameters."""


class AuthenticationError(APIConnectError):
    """``APIConnect=FAILED``: store id/password rejected (or IP not whitelisted)."""


class InactiveStoreError(APIConnectError):
    """``APIConnect=INACTIVE``: the store or API user is inactive."""


class SessionInitError(SSLCommerzError):
    """Session init answered ``status=FAILED``; ``reason`` holds ``failedreason``."""

    def __init__(self, reason: str, *, raw: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(f"SSLCommerz session init failed: {reason}", raw=raw)
        self.reason = reason


class HashVerificationError(SSLCommerzError):
    """``verify_sign`` did not match the posted fields."""


class PaymentNotValidError(SSLCommerzError):
    """The payment is not in a paid state (``VALID``/``VALIDATED``)."""

    def __init__(self, status: str, message: str, *, raw: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message, raw=raw)
        self.status = status


class AmountMismatchError(SSLCommerzError):
    """The validated amount, currency or tran_id differs from your order."""

    def __init__(self, field: str, expected: str, actual: str, *, raw: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(f"{field} mismatch: expected {expected!r}, got {actual!r}", raw=raw)
        self.field = field
        self.expected = expected
        self.actual = actual


class RefundError(SSLCommerzError):
    """Refund initiate or status answered ``failed``; ``reason`` holds ``errorReason``."""

    def __init__(self, reason: str, *, status: str = "failed", raw: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(f"SSLCommerz refund failed: {reason or 'no reason given'}", raw=raw)
        self.reason = reason
        self.status = status


def api_connect_error(value: str, raw: Mapping[str, Any]) -> APIConnectError:
    """Most specific :class:`APIConnectError` for an ``APIConnect`` value."""
    reason = str(raw.get("errorReason") or raw.get("failedreason") or raw.get("error") or "")
    suffix = f": {reason}" if reason else ""
    if value == "INVALID_REQUEST":
        return InvalidRequestError(value, f"SSLCommerz rejected the request (INVALID_REQUEST){suffix}", raw=raw)
    if value == "FAILED":
        return AuthenticationError(value, f"SSLCommerz authentication failed{suffix}", raw=raw)
    if value == "INACTIVE":
        return InactiveStoreError(value, f"SSLCommerz store or API user is inactive{suffix}", raw=raw)
    return APIConnectError(value, f"Unexpected APIConnect value {value!r}{suffix}", raw=raw)
