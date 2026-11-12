"""HTTP layer: timeouts, retry with backoff and error mapping.

The client accepts any ``httpx`` transport, so tests can pass
``httpx.MockTransport`` and applications can add proxies or custom TLS.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

import httpx

from ._version import __version__
from .errors import NetworkError, ResponseError, SSLCommerzError, TimeoutError
from .redact import redact

logger = logging.getLogger("sslcommerz_py")

USER_AGENT = f"sslcommerz-py/{__version__}"


@dataclass(frozen=True)
class RetryPolicy:
    """Backoff for idempotent calls (validation, queries, refund status).

    Session init and refund initiate are not retried by default: a request
    that timed out may already have been processed.
    """

    retries: int = 2
    base_delay: float = 0.5
    max_delay: float = 8.0
    factor: float = 2.0
    jitter: bool = True
    retry_statuses: Sequence[int] = (502, 503, 504)

    def delay(self, attempt: int, rnd: Callable[[], float] = random.random) -> float:
        """Delay before retry number ``attempt`` (1-based)."""
        d = min(self.max_delay, self.base_delay * (self.factor ** (attempt - 1)))
        return d * (0.5 + rnd() * 0.5) if self.jitter else d


NO_RETRY = RetryPolicy(retries=0)


def _decode(response: httpx.Response, operation: str, secrets: Sequence[str]) -> Dict[str, Any]:
    text = response.text
    try:
        body = json.loads(text) if text.strip() else {}
    except ValueError:
        raise ResponseError(
            f"SSLCommerz {operation} returned a non-JSON response (HTTP {response.status_code})",
            status_code=response.status_code,
            raw={"body": redact(text[:500], secrets)},
        ) from None
    if not isinstance(body, dict):
        raise ResponseError(
            f"SSLCommerz {operation} returned unexpected JSON (HTTP {response.status_code})",
            status_code=response.status_code,
            raw={"body": redact(body, secrets)},
        )
    if response.status_code >= 400:
        raise ResponseError(
            f"SSLCommerz {operation} failed with HTTP {response.status_code}",
            status_code=response.status_code,
            raw=redact(body, secrets),
        )
    return body


def _transient(exc: SSLCommerzError, policy: RetryPolicy) -> bool:
    if isinstance(exc, NetworkError):
        return True
    return isinstance(exc, ResponseError) and exc.status_code in tuple(policy.retry_statuses)


def _network_error(exc: Exception, operation: str, timeout: float, secrets: Sequence[str]) -> NetworkError:
    if isinstance(exc, httpx.TimeoutException):
        return TimeoutError(f"SSLCommerz {operation} timed out after {timeout:g}s")
    return NetworkError(f"SSLCommerz {operation} network error: {redact(str(exc), secrets)}")


class _Base:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float,
        retry: RetryPolicy,
        secrets: Sequence[str],
        sleep: Optional[Callable[[float], Any]] = None,
        rnd: Callable[[], float] = random.random,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retry = retry
        self.secrets = tuple(secrets)
        self._sleep = sleep
        self._rnd = rnd

    def _log(self, level: int, msg: str, **fields: Any) -> None:
        logger.log(level, msg, extra={"sslcommerz": redact(fields, self.secrets)})


class SyncTransport(_Base):
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float,
        retry: RetryPolicy,
        secrets: Sequence[str],
        transport: Optional[httpx.BaseTransport] = None,
        client: Optional[httpx.Client] = None,
        sleep: Optional[Callable[[float], Any]] = None,
        rnd: Callable[[], float] = random.random,
    ) -> None:
        super().__init__(base_url, timeout=timeout, retry=retry, secrets=secrets, sleep=sleep or time.sleep, rnd=rnd)
        self._owns_client = client is None
        self.client = client or httpx.Client(transport=transport, timeout=timeout, headers={"User-Agent": USER_AGENT})

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        params: Optional[Mapping[str, str]] = None,
        data: Optional[Mapping[str, str]] = None,
        retry: Optional[RetryPolicy] = None,
    ) -> Dict[str, Any]:
        policy = retry or self.retry
        attempts = policy.retries + 1
        url = f"{self.base_url}{path}"
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                try:
                    response = self.client.request(method, url, params=params, data=data, timeout=self.timeout)
                except httpx.HTTPError as exc:
                    raise _network_error(exc, operation, self.timeout, self.secrets) from exc
                self._log(
                    logging.DEBUG,
                    "sslcommerz response",
                    operation=operation,
                    status=response.status_code,
                    attempt=attempt,
                    ms=round((time.monotonic() - started) * 1000),
                )
                return _decode(response, operation, self.secrets)
            except SSLCommerzError as exc:
                if attempt >= attempts or not _transient(exc, policy):
                    raise
                delay = policy.delay(attempt, self._rnd)
                self._log(
                    logging.WARNING,
                    "sslcommerz retry",
                    operation=operation,
                    attempt=attempt,
                    delay=delay,
                    error=str(exc),
                )
                assert self._sleep is not None
                self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover


class AsyncTransport(_Base):
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float,
        retry: RetryPolicy,
        secrets: Sequence[str],
        transport: Optional[httpx.AsyncBaseTransport] = None,
        client: Optional[httpx.AsyncClient] = None,
        sleep: Optional[Callable[[float], Any]] = None,
        rnd: Callable[[], float] = random.random,
    ) -> None:
        super().__init__(base_url, timeout=timeout, retry=retry, secrets=secrets, sleep=sleep or asyncio.sleep, rnd=rnd)
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            transport=transport, timeout=timeout, headers={"User-Agent": USER_AGENT}
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        params: Optional[Mapping[str, str]] = None,
        data: Optional[Mapping[str, str]] = None,
        retry: Optional[RetryPolicy] = None,
    ) -> Dict[str, Any]:
        policy = retry or self.retry
        attempts = policy.retries + 1
        url = f"{self.base_url}{path}"
        for attempt in range(1, attempts + 1):
            try:
                try:
                    response = await self.client.request(method, url, params=params, data=data, timeout=self.timeout)
                except httpx.HTTPError as exc:
                    raise _network_error(exc, operation, self.timeout, self.secrets) from exc
                return _decode(response, operation, self.secrets)
            except SSLCommerzError as exc:
                if attempt >= attempts or not _transient(exc, policy):
                    raise
                delay = policy.delay(attempt, self._rnd)
                self._log(
                    logging.WARNING,
                    "sslcommerz retry",
                    operation=operation,
                    attempt=attempt,
                    delay=delay,
                    error=str(exc),
                )
                assert self._sleep is not None
                result = self._sleep(delay)
                if asyncio.iscoroutine(result):
                    await result
        raise AssertionError("unreachable")  # pragma: no cover
