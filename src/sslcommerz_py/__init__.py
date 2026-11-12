"""Python SDK and CLI for the SSLCommerz payment gateway (Bangladesh)."""

from __future__ import annotations

from ._version import __version__
from .async_client import AsyncSSLCommerz
from .client import SSLCommerz
from .config import Config, Environment
from .constants import (
    LIVE_BASE_URL,
    SANDBOX_BASE_URL,
    APIConnect,
    IPNStatus,
    RefundInitStatus,
    RefundStatusValue,
    TransactionStatus,
    ValidationStatus,
)
from .core import VerifiedPayment
from .errors import (
    AmountMismatchError,
    APIConnectError,
    AuthenticationError,
    ConfigurationError,
    HashVerificationError,
    InactiveStoreError,
    InvalidRequestError,
    NetworkError,
    PaymentNotValidError,
    RefundError,
    ResponseError,
    SessionInitError,
    SSLCommerzError,
    TimeoutError,
    ValidationError,
)
from .hashing import compute_signature, verify_signature
from .ipn import IPNOutcome, IPNVerifier, UnknownOrderError
from .models import (
    CartItem,
    Customer,
    IPNPayload,
    PaymentRequest,
    Product,
    RefundResult,
    RefundStatusResult,
    SessionResponse,
    Shipping,
    Transaction,
    TransactionQueryResult,
    ValidationResult,
)
from .transport import RetryPolicy

__all__ = [
    "LIVE_BASE_URL",
    "SANDBOX_BASE_URL",
    "APIConnect",
    "APIConnectError",
    "AmountMismatchError",
    "AsyncSSLCommerz",
    "AuthenticationError",
    "CartItem",
    "Config",
    "ConfigurationError",
    "Customer",
    "Environment",
    "HashVerificationError",
    "IPNPayload",
    "IPNStatus",
    "IPNOutcome",
    "IPNVerifier",
    "InactiveStoreError",
    "InvalidRequestError",
    "NetworkError",
    "PaymentNotValidError",
    "PaymentRequest",
    "Product",
    "RefundError",
    "RefundInitStatus",
    "RefundResult",
    "RefundStatusResult",
    "RefundStatusValue",
    "ResponseError",
    "RetryPolicy",
    "SSLCommerz",
    "SSLCommerzError",
    "SessionInitError",
    "SessionResponse",
    "Shipping",
    "TimeoutError",
    "Transaction",
    "UnknownOrderError",
    "TransactionQueryResult",
    "TransactionStatus",
    "ValidationError",
    "ValidationResult",
    "ValidationStatus",
    "VerifiedPayment",
    "__version__",
    "compute_signature",
    "verify_signature",
]
