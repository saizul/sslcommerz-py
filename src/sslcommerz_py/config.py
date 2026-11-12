"""Client configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Mapping, Optional

from .constants import DEFAULT_TIMEOUT, LIVE_BASE_URL, SANDBOX_BASE_URL
from .errors import ConfigurationError


class Environment(str, Enum):
    SANDBOX = "sandbox"
    LIVE = "live"

    @classmethod
    def parse(cls, value: str) -> Environment:
        v = value.strip().lower()
        if v in ("sandbox", "test", "testbox"):
            return cls.SANDBOX
        if v in ("live", "production", "prod"):
            return cls.LIVE
        raise ConfigurationError(f"Unknown environment {value!r}; use 'sandbox' or 'live'")


_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    """Store credentials and behaviour switches.

    ``store_passwd`` is the API password SSLCommerz issues with the store id;
    it is not your merchant panel login password.
    """

    store_id: str
    store_passwd: str = field(repr=False)
    environment: Environment = Environment.SANDBOX
    #: Overrides the host chosen by ``environment``.
    base_url: Optional[str] = None
    timeout: float = DEFAULT_TIMEOUT
    #: Verify ``verify_sign`` on IPN payloads before calling the Validation API.
    verify_hash: bool = True
    #: Allowed difference between the expected and the validated amount.
    amount_tolerance: Decimal = Decimal("0")
    #: Enforce the documented 10.00 - 500000.00 BDT range on session init.
    enforce_amount_range: bool = True

    def __post_init__(self) -> None:
        if not self.store_id or not self.store_id.strip():
            raise ConfigurationError("store_id is required")
        if not self.store_passwd or not self.store_passwd.strip():
            raise ConfigurationError("store_passwd is required")
        if isinstance(self.environment, str) and not isinstance(self.environment, Environment):
            object.__setattr__(self, "environment", Environment.parse(self.environment))
        if self.timeout <= 0:
            raise ConfigurationError("timeout must be positive")
        if not isinstance(self.amount_tolerance, Decimal):
            object.__setattr__(self, "amount_tolerance", Decimal(str(self.amount_tolerance)))

    @property
    def sandbox(self) -> bool:
        return self.environment is Environment.SANDBOX

    @property
    def resolved_base_url(self) -> str:
        url = self.base_url or (SANDBOX_BASE_URL if self.sandbox else LIVE_BASE_URL)
        return url.rstrip("/")

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None, **overrides: object) -> Config:
        """Read ``SSLCOMMERZ_STORE_ID``, ``SSLCOMMERZ_STORE_PASSWD``,
        ``SSLCOMMERZ_ENV`` (``sandbox``/``live``), ``SSLCOMMERZ_SANDBOX``
        (``true``/``false``), ``SSLCOMMERZ_BASE_URL`` and ``SSLCOMMERZ_TIMEOUT``.
        """
        e = os.environ if env is None else env
        if e.get("SSLCOMMERZ_ENV"):
            environment = Environment.parse(e["SSLCOMMERZ_ENV"])
        elif e.get("SSLCOMMERZ_SANDBOX"):
            sandbox = e["SSLCOMMERZ_SANDBOX"].strip().lower() in _TRUE
            environment = Environment.SANDBOX if sandbox else Environment.LIVE
        else:
            environment = Environment.SANDBOX
        kwargs: dict = {
            "store_id": e.get("SSLCOMMERZ_STORE_ID", ""),
            "store_passwd": e.get("SSLCOMMERZ_STORE_PASSWD", ""),
            "environment": environment,
        }
        if e.get("SSLCOMMERZ_BASE_URL"):
            kwargs["base_url"] = e["SSLCOMMERZ_BASE_URL"]
        if e.get("SSLCOMMERZ_TIMEOUT"):
            try:
                kwargs["timeout"] = float(e["SSLCOMMERZ_TIMEOUT"])
            except ValueError as exc:
                raise ConfigurationError("SSLCOMMERZ_TIMEOUT must be a number") from exc
        kwargs.update(overrides)
        return cls(**kwargs)
