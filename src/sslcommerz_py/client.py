"""Synchronous client."""

from __future__ import annotations

import random
from typing import Any, Callable, Mapping, Optional

import httpx

from . import core
from ._util import AmountLike
from .config import Config, Environment
from .constants import MERCHANT_API_PATH, SESSION_PATH, VALIDATION_PATH
from .core import VerifiedPayment
from .models import (
    PaymentRequest,
    RefundResult,
    RefundStatusResult,
    SessionResponse,
    TransactionQueryResult,
    ValidationResult,
)
from .transport import NO_RETRY, RetryPolicy, SyncTransport


class SSLCommerz:
    """Client for the SSLCommerz v4 APIs.

    ``transport`` accepts any ``httpx.BaseTransport`` (``httpx.MockTransport``
    in tests); ``http_client`` accepts a configured ``httpx.Client``.

    >>> sslc = SSLCommerz("teststore", "teststore@ssl")  # doctest: +SKIP
    """

    def __init__(
        self,
        store_id: Optional[str] = None,
        store_passwd: Optional[str] = None,
        *,
        sandbox: Optional[bool] = None,
        config: Optional[Config] = None,
        retry: Optional[RetryPolicy] = None,
        transport: Optional[httpx.BaseTransport] = None,
        http_client: Optional[httpx.Client] = None,
        sleep: Optional[Callable[[float], Any]] = None,
        rnd: Callable[[], float] = random.random,
    ) -> None:
        if config is None:
            env = Environment.SANDBOX if sandbox is None or sandbox else Environment.LIVE
            config = Config(store_id=store_id or "", store_passwd=store_passwd or "", environment=env)
        self.config = config
        self._http = SyncTransport(
            config.resolved_base_url,
            timeout=config.timeout,
            retry=retry or RetryPolicy(),
            secrets=(config.store_passwd,),
            transport=transport,
            client=http_client,
            sleep=sleep,
            rnd=rnd,
        )

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None, **kwargs: Any) -> SSLCommerz:
        """Build from ``SSLCOMMERZ_*`` environment variables (see :meth:`Config.from_env`)."""
        return cls(config=Config.from_env(env), **kwargs)

    # -------------------------------------------------------------- context

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> SSLCommerz:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def base_url(self) -> str:
        return self._http.base_url

    # ------------------------------------------------------------- payments

    def create_session(self, request: PaymentRequest, *, retry: Optional[RetryPolicy] = None) -> SessionResponse:
        """Create a payment session and return ``GatewayPageURL`` to redirect to.

        Not retried by default; pass ``retry`` to opt in (each attempt reuses
        your ``tran_id``).
        """
        body = self._http.request(
            "POST",
            SESSION_PATH,
            operation="session",
            data=core.session_params(self.config, request),
            retry=retry or NO_RETRY,
        )
        return core.parse_session(body)

    def validate(self, val_id: str) -> ValidationResult:
        """Call the Validation API for ``val_id``. Does not raise on ``INVALID_TRANSACTION``."""
        body = self._http.request(
            "GET", VALIDATION_PATH, operation="validation", params=core.validation_params(self.config, val_id)
        )
        return core.parse_validation(body)

    def verify_ipn(
        self,
        form: Mapping[str, Any],
        *,
        expected_tran_id: Optional[str] = None,
        expected_amount: Optional[AmountLike] = None,
        expected_currency: Optional[str] = None,
    ) -> VerifiedPayment:
        """Full IPN check: hash, status, Validation API, tran_id/amount/currency.

        Raises :class:`HashVerificationError`, :class:`PaymentNotValidError` or
        :class:`AmountMismatchError` when the payment must not be accepted.
        """
        payload = core.precheck_ipn(self.config, form)
        assert payload.val_id is not None
        validation = self.validate(payload.val_id)
        core.check_validation(
            self.config,
            validation,
            expected_tran_id=expected_tran_id,
            expected_amount=expected_amount,
            expected_currency=expected_currency,
            payload=payload,
        )
        return VerifiedPayment(payload=payload, validation=validation)

    def query_by_session(self, sessionkey: str) -> TransactionQueryResult:
        body = self._http.request(
            "GET",
            MERCHANT_API_PATH,
            operation="query_session",
            params=core.query_by_session_params(self.config, sessionkey),
        )
        return core.parse_query_by_session(body)

    def query_by_tran_id(self, tran_id: str) -> TransactionQueryResult:
        body = self._http.request(
            "GET",
            MERCHANT_API_PATH,
            operation="query_tran_id",
            params=core.query_by_tran_id_params(self.config, tran_id),
        )
        return core.parse_query_by_tran_id(body)

    # -------------------------------------------------------------- refunds

    def refund(
        self,
        *,
        bank_tran_id: str,
        refund_amount: AmountLike,
        refund_remarks: str,
        refund_trans_id: str,
        refe_id: Optional[str] = None,
    ) -> RefundResult:
        """Initiate a refund. ``refund_trans_id`` is your unique id for this refund.

        Never retried automatically. A ``processing`` status means a refund was
        already initiated for this transaction.
        """
        params = core.refund_params(
            self.config,
            bank_tran_id=bank_tran_id,
            refund_amount=refund_amount,
            refund_remarks=refund_remarks,
            refund_trans_id=refund_trans_id,
            refe_id=refe_id,
        )
        body = self._http.request("GET", MERCHANT_API_PATH, operation="refund", params=params, retry=NO_RETRY)
        return core.parse_refund(body)

    def refund_status(self, refund_ref_id: str) -> RefundStatusResult:
        body = self._http.request(
            "GET",
            MERCHANT_API_PATH,
            operation="refund_status",
            params=core.refund_status_params(self.config, refund_ref_id),
        )
        return core.parse_refund_status(body)
