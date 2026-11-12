"""Hosts, endpoint paths and documented status values.

Every URL and value here comes from the SSLCommerz developer documentation
(https://developer.sslcommerz.com/doc/v4/).
"""

from __future__ import annotations

from enum import Enum

SANDBOX_BASE_URL = "https://sandbox.sslcommerz.com"
LIVE_BASE_URL = "https://securepay.sslcommerz.com"

#: Create a payment session (POST, form encoded).
SESSION_PATH = "/gwprocess/v4/api.php"
#: Validate a payment by ``val_id`` (GET).
VALIDATION_PATH = "/validator/api/validationserverAPI.php"
#: Transaction query by ``sessionkey`` or ``tran_id``, refund initiate and
#: refund status all share this endpoint (GET) and differ by parameters.
MERCHANT_API_PATH = "/validator/api/merchantTransIDvalidationAPI.php"

DEFAULT_TIMEOUT = 30.0

#: Documented ``total_amount`` range for BDT.
MIN_AMOUNT_BDT = "10.00"
MAX_AMOUNT_BDT = "500000.00"

PRODUCT_PROFILES = (
    "general",
    "physical-goods",
    "non-physical-goods",
    "airline-tickets",
    "travel-vertical",
    "telecom-vertical",
)


class _StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)


class APIConnect(_StrEnum):
    """``APIConnect`` field returned by every merchant API."""

    DONE = "DONE"
    INVALID_REQUEST = "INVALID_REQUEST"
    FAILED = "FAILED"
    INACTIVE = "INACTIVE"


class IPNStatus(_StrEnum):
    """``status`` posted to the IPN listener and redirect URLs."""

    VALID = "VALID"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNATTEMPTED = "UNATTEMPTED"
    EXPIRED = "EXPIRED"


class ValidationStatus(_StrEnum):
    """``status`` returned by the Validation API."""

    VALID = "VALID"
    VALIDATED = "VALIDATED"
    INVALID_TRANSACTION = "INVALID_TRANSACTION"


class TransactionStatus(_StrEnum):
    """``status`` returned by the Transaction Query API."""

    VALID = "VALID"
    VALIDATED = "VALIDATED"
    PENDING = "PENDING"
    FAILED = "FAILED"


class RefundInitStatus(_StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    PROCESSING = "processing"


class RefundStatusValue(_StrEnum):
    REFUNDED = "refunded"
    PROCESSING = "processing"
    CANCELLED = "cancelled"


#: Validation/Query statuses that mean the money was received.
PAID_STATUSES = frozenset({"VALID", "VALIDATED"})
