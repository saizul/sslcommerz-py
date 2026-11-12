"""Request builders and response handlers shared by the sync and async clients.

Nothing in here performs I/O, which keeps both clients identical in
behaviour and makes the protocol easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Mapping, Optional

from ._util import AmountLike, format_amount, optional_text, require_text, to_decimal
from .config import Config
from .constants import PAID_STATUSES
from .errors import (
    AmountMismatchError,
    PaymentNotValidError,
    RefundError,
    ResponseError,
    SessionInitError,
    api_connect_error,
)
from .hashing import require_valid_signature
from .models import (
    IPNPayload,
    PaymentRequest,
    RefundResult,
    RefundStatusResult,
    SessionResponse,
    TransactionQueryResult,
    ValidationResult,
)


def _auth(config: Config) -> Dict[str, str]:
    return {"store_id": config.store_id, "store_passwd": config.store_passwd}


def check_api_connect(body: Mapping[str, Any]) -> None:
    """Raise for ``APIConnect`` values other than ``DONE``. A missing field passes."""
    value = body.get("APIConnect")
    if value is None or value == "" or str(value).upper() == "DONE":
        return
    raise api_connect_error(str(value).upper(), body)


# ------------------------------------------------------------------ session


def session_params(config: Config, request: PaymentRequest) -> Dict[str, str]:
    params = request.to_params(enforce_amount_range=config.enforce_amount_range)
    params.update(_auth(config))
    return params


def parse_session(body: Mapping[str, Any]) -> SessionResponse:
    res = SessionResponse.from_dict(body)
    if res.status.upper() != "SUCCESS":
        raise SessionInitError(res.failed_reason or "unknown reason", raw=body)
    if not res.gateway_page_url:
        raise ResponseError("Session init succeeded but GatewayPageURL is missing", raw=body)
    return res


# --------------------------------------------------------------- validation


def validation_params(config: Config, val_id: str) -> Dict[str, str]:
    return {
        "val_id": require_text("val_id", val_id, 50),
        **_auth(config),
        "format": "json",
        "v": "1",
    }


def parse_validation(body: Mapping[str, Any]) -> ValidationResult:
    check_api_connect(body)
    if not body.get("status"):
        raise ResponseError("Validation response has no status", raw=body)
    return ValidationResult.from_dict(body)


# ------------------------------------------------------------------- query


def query_by_session_params(config: Config, sessionkey: str) -> Dict[str, str]:
    return {
        "sessionkey": require_text("sessionkey", sessionkey, 50),
        **_auth(config),
        "format": "json",
        "v": "1",
    }


def query_by_tran_id_params(config: Config, tran_id: str) -> Dict[str, str]:
    return {"tran_id": require_text("tran_id", tran_id, 30), **_auth(config), "format": "json"}


def parse_query_by_session(body: Mapping[str, Any]) -> TransactionQueryResult:
    check_api_connect(body)
    return TransactionQueryResult.from_session_response(body)


def parse_query_by_tran_id(body: Mapping[str, Any]) -> TransactionQueryResult:
    check_api_connect(body)
    return TransactionQueryResult.from_tran_id_response(body)


# ------------------------------------------------------------------ refunds


def refund_params(
    config: Config,
    *,
    bank_tran_id: str,
    refund_amount: AmountLike,
    refund_remarks: str,
    refund_trans_id: str,
    refe_id: Optional[str] = None,
) -> Dict[str, str]:
    params = {
        "bank_tran_id": require_text("bank_tran_id", bank_tran_id, 80),
        "refund_trans_id": require_text("refund_trans_id", refund_trans_id, 30),
        "refund_amount": format_amount("refund_amount", refund_amount),
        "refund_remarks": require_text("refund_remarks", refund_remarks, 255),
        **_auth(config),
        "format": "json",
        "v": "1",
    }
    ref = optional_text("refe_id", refe_id, 50)
    if ref is not None:
        params["refe_id"] = ref
    return params


def parse_refund(body: Mapping[str, Any]) -> RefundResult:
    check_api_connect(body)
    res = RefundResult.from_dict(body)
    if res.status.lower() == "failed" or not res.status:
        raise RefundError(res.error_reason or "", status=res.status or "failed", raw=body)
    return res


def refund_status_params(config: Config, refund_ref_id: str) -> Dict[str, str]:
    return {"refund_ref_id": require_text("refund_ref_id", refund_ref_id, 50), **_auth(config), "format": "json"}


def parse_refund_status(body: Mapping[str, Any]) -> RefundStatusResult:
    check_api_connect(body)
    res = RefundStatusResult.from_dict(body)
    if not res.status:
        raise RefundError(res.error_reason or "no status in response", status="", raw=body)
    return res


# --------------------------------------------------------------------- IPN


@dataclass(frozen=True)
class VerifiedPayment:
    """A payment that passed every check in :meth:`SSLCommerz.verify_ipn`."""

    payload: IPNPayload
    validation: ValidationResult

    @property
    def tran_id(self) -> Optional[str]:
        return self.validation.tran_id

    @property
    def amount(self) -> Optional[Decimal]:
        return self.validation.amount

    @property
    def already_validated(self) -> bool:
        """``VALIDATED``: this val_id was validated before (duplicate IPN or redirect)."""
        return self.validation.status.upper() == "VALIDATED"

    @property
    def is_high_risk(self) -> bool:
        return self.validation.is_high_risk


def precheck_ipn(config: Config, form: Mapping[str, Any]) -> IPNPayload:
    """Steps before the Validation API call: parse, hash check, status check."""
    payload = IPNPayload.from_form(form)
    if config.verify_hash:
        require_valid_signature(payload.raw, config.store_passwd)
    if payload.status.upper() != "VALID":
        raise PaymentNotValidError(
            payload.status, f"IPN status is {payload.status or 'missing'}, not VALID", raw=payload.raw
        )
    if not payload.val_id:
        raise PaymentNotValidError(payload.status, "IPN has no val_id", raw=payload.raw)
    return payload


def check_validation(
    config: Config,
    validation: ValidationResult,
    *,
    expected_tran_id: Optional[str] = None,
    expected_amount: Optional[AmountLike] = None,
    expected_currency: Optional[str] = None,
    payload: Optional[IPNPayload] = None,
) -> None:
    """Raise unless the validated transaction is paid and matches your order.

    For non-BDT orders the comparison uses ``currency_type`` and
    ``currency_amount`` (the original currency), as the official PHP library
    does; ``amount``/``currency`` then hold the BDT conversion.
    """
    status = validation.status.upper()
    if status not in PAID_STATUSES:
        raise PaymentNotValidError(validation.status, f"Validation status is {validation.status}", raw=validation.raw)
    if payload is not None and payload.tran_id and validation.tran_id and payload.tran_id != validation.tran_id:
        raise AmountMismatchError("tran_id", payload.tran_id, validation.tran_id, raw=validation.raw)
    if expected_tran_id is not None and (validation.tran_id or "").strip() != expected_tran_id.strip():
        raise AmountMismatchError("tran_id", expected_tran_id, validation.tran_id or "", raw=validation.raw)

    currency = (expected_currency or "").strip().upper()
    foreign = bool(currency) and currency != "BDT"
    if currency:
        actual_currency = (validation.currency_type if foreign else validation.currency) or ""
        if actual_currency.strip().upper() != currency:
            raise AmountMismatchError("currency", currency, actual_currency, raw=validation.raw)
    if expected_amount is not None:
        expected = Decimal(format_amount("expected_amount", expected_amount))
        actual = validation.currency_amount if foreign else validation.amount
        if actual is None:
            actual = to_decimal(validation.raw.get("amount"))
        if actual is None or abs(actual - expected) > config.amount_tolerance:
            raise AmountMismatchError(
                "amount", str(expected), "" if actual is None else str(actual), raw=validation.raw
            )
