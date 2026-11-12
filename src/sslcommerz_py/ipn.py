"""Framework-agnostic IPN handling.

:class:`IPNVerifier` ties :meth:`SSLCommerz.verify_ipn` to your order store:
it looks up the order by ``tran_id`` so the expected amount and currency
always come from your database, never from the request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Tuple

from ._util import AmountLike, first
from .client import SSLCommerz
from .core import VerifiedPayment
from .errors import PaymentNotValidError, SSLCommerzError

#: Returns ``(amount, currency)`` for a tran_id, or ``None`` if unknown.
OrderLookup = Callable[[str], Optional[Tuple[AmountLike, str]]]


@dataclass(frozen=True)
class IPNOutcome:
    """Result of :meth:`IPNVerifier.handle`."""

    ok: bool
    tran_id: Optional[str]
    payment: Optional[VerifiedPayment] = None
    error: Optional[SSLCommerzError] = None
    #: Gateway status of a payment that was not successful (FAILED, CANCELLED...).
    status: Optional[str] = None

    @property
    def http_status(self) -> int:
        """Status code to answer the IPN with. SSLCommerz only needs a 2xx."""
        return 200


class UnknownOrderError(SSLCommerzError):
    """The IPN refers to a tran_id that your system did not create."""


class IPNVerifier:
    def __init__(self, client: SSLCommerz, lookup: OrderLookup) -> None:
        self.client = client
        self.lookup = lookup

    def verify(self, form: Mapping[str, Any]) -> VerifiedPayment:
        """Verify or raise. See :meth:`SSLCommerz.verify_ipn` for the checks."""
        tran_id = first(form, "tran_id")
        order = self.lookup(str(tran_id)) if tran_id else None
        if order is None:
            raise UnknownOrderError(f"Unknown tran_id {tran_id!r}")
        amount, currency = order
        return self.client.verify_ipn(
            form, expected_tran_id=str(tran_id), expected_amount=amount, expected_currency=currency
        )

    def handle(self, form: Mapping[str, Any]) -> IPNOutcome:
        """Like :meth:`verify` but returns an :class:`IPNOutcome` instead of raising."""
        tran_id = first(form, "tran_id")
        tid = str(tran_id) if tran_id else None
        try:
            return IPNOutcome(ok=True, tran_id=tid, payment=self.verify(form))
        except PaymentNotValidError as exc:
            return IPNOutcome(ok=False, tran_id=tid, error=exc, status=exc.status)
        except SSLCommerzError as exc:
            return IPNOutcome(ok=False, tran_id=tid, error=exc)
