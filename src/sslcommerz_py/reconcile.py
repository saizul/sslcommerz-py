"""Batch reconciliation of your orders against the Transaction Query API.

IPNs get lost: a listener is down during a deploy, a proxy times out, or the
customer closes the tab before the success redirect. :func:`reconcile` takes
the orders *you* expect to be paid (``tran_id`` plus the amount and currency
from your database) and asks the gateway what really happened to each one,
using only :meth:`SSLCommerz.query_by_tran_id`.

Every order ends up in exactly one :class:`ReconcileStatus`. The ones that
need a human are the "problems": the amount or currency differs, the same
``tran_id`` was paid more than once, or the query itself failed.

Nothing here changes state at the gateway; it is safe to run on a schedule.
"""

from __future__ import annotations

import asyncio
import csv
import io
from dataclasses import dataclass, field
from decimal import Decimal
from typing import (
    IO,
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Union,
)

from ._util import AmountLike, format_amount, require_text
from .constants import _StrEnum
from .errors import (
    AuthenticationError,
    ConfigurationError,
    InactiveStoreError,
    SSLCommerzError,
    ValidationError,
)
from .models import Transaction, TransactionQueryResult

#: Errors that would fail for every order, so reconciliation stops at once.
FATAL_ERRORS = (AuthenticationError, InactiveStoreError, ConfigurationError)

CSV_COLUMNS = (
    "tran_id",
    "status",
    "expected_amount",
    "expected_currency",
    "paid_amount",
    "paid_currency",
    "paid_count",
    "attempts",
    "gateway_statuses",
    "bank_tran_id",
    "val_id",
    "high_risk",
    "detail",
)


class ReconcileStatus(_StrEnum):
    """Outcome of reconciling one order."""

    #: Exactly one paid attempt, and amount/currency match the order.
    PAID = "paid"
    #: Paid, but in a different currency than the order.
    CURRENCY_MISMATCH = "currency_mismatch"
    #: Paid, but the amount differs by more than the tolerance.
    AMOUNT_MISMATCH = "amount_mismatch"
    #: More than one paid attempt for the same ``tran_id``: refund the extra.
    MULTIPLE_PAYMENTS = "multiple_payments"
    #: No paid attempt, but one is still ``PENDING``: check again later.
    PENDING = "pending"
    #: Attempts exist and none of them is paid (failed, cancelled...).
    NOT_PAID = "not_paid"
    #: The gateway has no transaction for this ``tran_id``.
    NOT_FOUND = "not_found"
    #: The query failed (network, HTTP or response error).
    ERROR = "error"


#: Statuses that need attention: money arrived but does not match, or the
#: state is unknown.
PROBLEM_STATUSES = frozenset(
    {
        ReconcileStatus.CURRENCY_MISMATCH,
        ReconcileStatus.AMOUNT_MISMATCH,
        ReconcileStatus.MULTIPLE_PAYMENTS,
        ReconcileStatus.ERROR,
    }
)
#: Statuses where the order was not paid (normal for abandoned checkouts).
UNPAID_STATUSES = frozenset({ReconcileStatus.PENDING, ReconcileStatus.NOT_PAID, ReconcileStatus.NOT_FOUND})


@dataclass(frozen=True)
class ExpectedOrder:
    """An order you expect to be paid. Amount and currency come from *your* database."""

    tran_id: str
    amount: Optional[Decimal] = None
    currency: str = "BDT"

    @classmethod
    def create(cls, tran_id: str, amount: Optional[AmountLike] = None, currency: Optional[str] = None) -> ExpectedOrder:
        """Validate and normalise the fields (``tran_id`` up to 30 characters, 2-decimal amount)."""
        tid = require_text("tran_id", tran_id, 30).strip()
        amt = None
        if amount is not None and str(amount).strip() != "":
            amt = Decimal(format_amount("amount", amount.strip() if isinstance(amount, str) else amount))
        cur = (currency or "BDT").strip().upper() or "BDT"
        if len(cur) != 3 or not cur.isalpha():
            raise ValidationError("currency", f"must be a 3-letter code, got {currency!r}")
        return cls(tran_id=tid, amount=amt, currency=cur)


@dataclass
class ReconcileResult:
    """Outcome for one :class:`ExpectedOrder`."""

    order: ExpectedOrder
    status: ReconcileStatus
    #: Amount the gateway received, in the order's currency (see :func:`classify`).
    paid_amount: Optional[Decimal] = None
    paid_currency: Optional[str] = None
    #: Number of attempts in a paid state (``VALID`` / ``VALIDATED``).
    paid_count: int = 0
    #: Total attempts the gateway reported.
    attempts: int = 0
    #: Gateway ``status`` of every attempt, in the order returned.
    gateway_statuses: List[str] = field(default_factory=list)
    bank_tran_id: Optional[str] = None
    val_id: Optional[str] = None
    high_risk: bool = False
    #: Human readable explanation for anything other than ``PAID``.
    detail: str = ""
    #: The paid transactions (all of them for ``MULTIPLE_PAYMENTS``).
    paid_transactions: List[Transaction] = field(default_factory=list, repr=False)
    error: Optional[SSLCommerzError] = field(default=None, repr=False)

    @property
    def tran_id(self) -> str:
        return self.order.tran_id

    @property
    def ok(self) -> bool:
        return self.status is ReconcileStatus.PAID

    @property
    def is_problem(self) -> bool:
        return self.status in PROBLEM_STATUSES

    def to_dict(self) -> Dict[str, Any]:
        """JSON-friendly summary (amounts as strings, no raw responses)."""
        return {
            "tran_id": self.tran_id,
            "status": self.status.value,
            "expected_amount": _fmt(self.order.amount),
            "expected_currency": self.order.currency,
            "paid_amount": _fmt(self.paid_amount),
            "paid_currency": self.paid_currency,
            "paid_count": self.paid_count,
            "attempts": self.attempts,
            "gateway_statuses": list(self.gateway_statuses),
            "bank_tran_id": self.bank_tran_id,
            "val_id": self.val_id,
            "high_risk": self.high_risk,
            "detail": self.detail,
        }


@dataclass
class ReconcileReport:
    """All results of a :func:`reconcile` run, in input order."""

    results: List[ReconcileResult]

    def counts(self) -> Dict[str, int]:
        """Number of orders per status; every status is present, zero or not."""
        out = {s.value: 0 for s in ReconcileStatus}
        for r in self.results:
            out[r.status.value] += 1
        return out

    @property
    def problems(self) -> List[ReconcileResult]:
        return [r for r in self.results if r.is_problem]

    @property
    def unpaid(self) -> List[ReconcileResult]:
        return [r for r in self.results if r.status in UNPAID_STATUSES]

    @property
    def has_problems(self) -> bool:
        return any(r.is_problem for r in self.results)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": {"total": len(self.results), **self.counts()},
            "results": [r.to_dict() for r in self.results],
        }

    def to_csv(self) -> str:
        """One row per order with the columns in :data:`CSV_COLUMNS`."""
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
        writer.writeheader()
        for r in self.results:
            row = r.to_dict()
            row["gateway_statuses"] = " ".join(row["gateway_statuses"])
            row["high_risk"] = "yes" if row["high_risk"] else "no"
            writer.writerow({k: _csv_safe("" if row[k] is None else str(row[k])) for k in CSV_COLUMNS})
        return buf.getvalue()


# ------------------------------------------------------------ classification


def _fmt(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else str(value)


def _csv_safe(text: str) -> str:
    """Neutralise spreadsheet formulas in values that came from the gateway."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _paid_in(txn: Transaction, currency: str) -> tuple:
    """``(amount, currency)`` of ``txn`` comparable with an order in ``currency``.

    Non-BDT orders are compared on ``currency_type``/``currency_amount`` (the
    original currency), exactly like :meth:`SSLCommerz.verify_ipn`.
    """
    if currency != "BDT":
        return txn.currency_amount, (txn.currency_type or "").strip().upper() or None
    return txn.amount, (txn.currency or "").strip().upper() or None


def _distinct_paid(transactions: Sequence[Transaction]) -> List[Transaction]:
    seen = set()
    out: List[Transaction] = []
    for t in transactions:
        if not t.is_paid:
            continue
        key = t.val_id or t.bank_tran_id or id(t)
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def classify(
    order: ExpectedOrder, result: TransactionQueryResult, *, tolerance: Decimal = Decimal("0")
) -> ReconcileResult:
    """Decide the :class:`ReconcileStatus` for one order. Pure, no I/O.

    Precedence: ``MULTIPLE_PAYMENTS`` > ``CURRENCY_MISMATCH`` >
    ``AMOUNT_MISMATCH`` > ``PAID`` when money arrived, otherwise ``PENDING``
    > ``NOT_PAID`` > ``NOT_FOUND``. Attempts whose ``tran_id`` differs from
    the order are ignored.
    """
    txns = [t for t in result.transactions if not t.tran_id or t.tran_id.strip() == order.tran_id]
    statuses = [t.status for t in txns]
    base = {"order": order, "attempts": len(txns), "gateway_statuses": statuses}
    paid = _distinct_paid(txns)

    if not paid:
        if not txns:
            return ReconcileResult(status=ReconcileStatus.NOT_FOUND, detail="no transaction at the gateway", **base)
        if any(s.upper() == "PENDING" for s in statuses):
            return ReconcileResult(status=ReconcileStatus.PENDING, detail="attempt still pending", **base)
        return ReconcileResult(
            status=ReconcileStatus.NOT_PAID, detail="no paid attempt: " + ", ".join(statuses), **base
        )

    first = paid[0]
    amount, currency = _paid_in(first, order.currency)
    common = {
        **base,
        "paid_amount": amount,
        "paid_currency": currency,
        "paid_count": len(paid),
        "bank_tran_id": first.bank_tran_id,
        "val_id": first.val_id,
        "high_risk": any(t.is_high_risk for t in paid),
        "paid_transactions": paid,
    }
    if len(paid) > 1:
        ids = ", ".join(t.bank_tran_id or t.val_id or "?" for t in paid)
        return ReconcileResult(
            status=ReconcileStatus.MULTIPLE_PAYMENTS, detail=f"{len(paid)} paid attempts ({ids})", **common
        )
    if currency != order.currency:
        return ReconcileResult(
            status=ReconcileStatus.CURRENCY_MISMATCH,
            detail=f"expected {order.currency}, got {currency or 'none'}",
            **common,
        )
    if order.amount is not None and (amount is None or abs(amount - order.amount) > tolerance):
        return ReconcileResult(
            status=ReconcileStatus.AMOUNT_MISMATCH,
            detail=f"expected {order.amount}, got {amount if amount is not None else 'none'}",
            **common,
        )
    return ReconcileResult(status=ReconcileStatus.PAID, **common)


def _error_result(order: ExpectedOrder, exc: SSLCommerzError) -> ReconcileResult:
    return ReconcileResult(order=order, status=ReconcileStatus.ERROR, detail=str(exc), error=exc)


def _check_unique(orders: Sequence[ExpectedOrder]) -> None:
    seen = set()
    for o in orders:
        if o.tran_id in seen:
            raise ValidationError("tran_id", f"duplicate order {o.tran_id!r}")
        seen.add(o.tran_id)


# ------------------------------------------------------------------ runners


def _tolerance(client: Any, tolerance: Optional[AmountLike]) -> Decimal:
    if tolerance is not None:
        return Decimal(str(tolerance))
    config = getattr(client, "config", None)
    return getattr(config, "amount_tolerance", Decimal("0"))


def reconcile(
    client: Any,
    orders: Iterable[ExpectedOrder],
    *,
    tolerance: Optional[AmountLike] = None,
    on_result: Optional[Callable[[ReconcileResult], None]] = None,
    delay: float = 0.0,
    sleep: Optional[Callable[[float], None]] = None,
) -> ReconcileReport:
    """Query every order with ``client.query_by_tran_id`` and classify it.

    ``tolerance`` defaults to the client's ``Config.amount_tolerance``.
    Per-order failures become ``ERROR`` results; authentication and
    inactive-store errors stop the run because every query would fail.
    ``delay`` pauses between queries to stay gentle on the gateway.
    """
    order_list = list(orders)
    _check_unique(order_list)
    tol = _tolerance(client, tolerance)
    pause = sleep or _default_sleep
    results: List[ReconcileResult] = []
    for i, order in enumerate(order_list):
        if i and delay > 0:
            pause(delay)
        try:
            res = classify(order, client.query_by_tran_id(order.tran_id), tolerance=tol)
        except FATAL_ERRORS:
            raise
        except SSLCommerzError as exc:
            res = _error_result(order, exc)
        results.append(res)
        if on_result is not None:
            on_result(res)
    return ReconcileReport(results)


async def areconcile(
    client: Any,
    orders: Iterable[ExpectedOrder],
    *,
    tolerance: Optional[AmountLike] = None,
    concurrency: int = 4,
) -> ReconcileReport:
    """Async :func:`reconcile` for :class:`AsyncSSLCommerz`, with bounded concurrency.

    Results keep the input order regardless of which query finishes first.
    """
    if concurrency < 1:
        raise ValidationError("concurrency", "must be at least 1")
    order_list = list(orders)
    _check_unique(order_list)
    tol = _tolerance(client, tolerance)
    gate = asyncio.Semaphore(concurrency)

    async def one(order: ExpectedOrder) -> ReconcileResult:
        async with gate:
            try:
                return classify(order, await client.query_by_tran_id(order.tran_id), tolerance=tol)
            except FATAL_ERRORS:
                raise
            except SSLCommerzError as exc:
                return _error_result(order, exc)

    return ReconcileReport(list(await asyncio.gather(*(one(o) for o in order_list))))


def _default_sleep(seconds: float) -> None:  # pragma: no cover - trivial
    import time

    time.sleep(seconds)


# ---------------------------------------------------------------- CSV input

_ALIASES = {
    "tran_id": ("tran_id", "tranid", "transaction_id", "order_id"),
    "amount": ("amount", "total_amount", "expected_amount", "total"),
    "currency": ("currency", "expected_currency"),
}


def _column(header: Sequence[str], name: str) -> Optional[str]:
    normalised = {h.strip().lower().replace(" ", "_").replace("-", "_"): h for h in header if h}
    for alias in _ALIASES[name]:
        if alias in normalised:
            return normalised[alias]
    return None


def load_orders(source: Union[str, IO[str]]) -> List[ExpectedOrder]:
    """Read orders from a CSV file path or text stream.

    The header must contain a ``tran_id`` column (aliases: ``transaction_id``,
    ``order_id``); ``amount`` (or ``total_amount``) and ``currency`` are
    optional. Comma, semicolon and tab delimiters are detected. Blank rows
    are skipped; a bad value raises :class:`ValidationError` naming the line.
    """
    if isinstance(source, str):
        with open(source, encoding="utf-8-sig", newline="") as fh:
            return load_orders(fh)
    text = source.read()
    if text.startswith("﻿"):
        text = text[1:]
    if not text.strip():
        return []
    try:
        dialect: Any = csv.Sniffer().sniff(text.split("\n", 1)[0], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    header = reader.fieldnames or []
    tran_col = _column(header, "tran_id")
    if tran_col is None:
        raise ValidationError("tran_id", f"CSV header needs a tran_id column, found {list(header)}")
    amount_col = _column(header, "amount")
    currency_col = _column(header, "currency")
    orders: List[ExpectedOrder] = []
    for row in reader:
        values: Mapping[str, Any] = {k: (v or "") for k, v in row.items() if k is not None}
        tran_id = str(values.get(tran_col, "")).strip()
        if not tran_id and not any(str(v).strip() for v in values.values()):
            continue
        try:
            orders.append(
                ExpectedOrder.create(
                    tran_id,
                    values.get(amount_col) if amount_col else None,
                    values.get(currency_col) if currency_col else None,
                )
            )
        except ValidationError as exc:
            raise ValidationError(exc.field, f"line {reader.line_num}: {exc.message.split(': ', 1)[-1]}") from None
    return orders


__all__ = [
    "CSV_COLUMNS",
    "PROBLEM_STATUSES",
    "UNPAID_STATUSES",
    "ExpectedOrder",
    "ReconcileReport",
    "ReconcileResult",
    "ReconcileStatus",
    "areconcile",
    "classify",
    "load_orders",
    "reconcile",
]
