"""Request and response models.

Responses keep the full body in ``raw`` so nothing the gateway sends is lost,
including fields this package does not model yet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional

from ._util import (
    AmountLike,
    first,
    format_amount,
    optional_text,
    require_text,
    require_url,
    to_decimal,
    to_int,
    to_str,
)
from .constants import MAX_AMOUNT_BDT, MIN_AMOUNT_BDT, PAID_STATUSES, PRODUCT_PROFILES
from .errors import ValidationError

# ----------------------------------------------------------------- requests


@dataclass
class Customer:
    name: str
    email: str
    phone: str
    add1: str
    city: str
    postcode: str
    country: str = "Bangladesh"
    add2: Optional[str] = None
    state: Optional[str] = None
    fax: Optional[str] = None

    def to_params(self) -> Dict[str, str]:
        p = {
            "cus_name": require_text("cus_name", self.name, 50),
            "cus_email": require_text("cus_email", self.email, 50),
            "cus_add1": require_text("cus_add1", self.add1, 50),
            "cus_city": require_text("cus_city", self.city, 50),
            "cus_postcode": require_text("cus_postcode", self.postcode, 30),
            "cus_country": require_text("cus_country", self.country, 50),
            "cus_phone": require_text("cus_phone", self.phone, 20),
        }
        if "@" not in p["cus_email"]:
            raise ValidationError("cus_email", "must be an email address")
        for key, value, limit in (
            ("cus_add2", self.add2, 50),
            ("cus_state", self.state, 50),
            ("cus_fax", self.fax, 20),
        ):
            v = optional_text(key, value, limit)
            if v is not None:
                p[key] = v
        return p


@dataclass
class Shipping:
    """Shipping details. ``method='NO'`` (default) sends no address."""

    method: str = "NO"
    num_of_item: Optional[int] = None
    weight_of_items: Optional[str] = None
    name: Optional[str] = None
    add1: Optional[str] = None
    add2: Optional[str] = None
    area: Optional[str] = None
    city: Optional[str] = None
    sub_city: Optional[str] = None
    state: Optional[str] = None
    postcode: Optional[str] = None
    country: Optional[str] = None
    logistic_pickup_id: Optional[str] = None
    logistic_delivery_type: Optional[str] = None

    def to_params(self) -> Dict[str, str]:
        method = require_text("shipping_method", self.method, 50)
        p: Dict[str, str] = {"shipping_method": method}
        fields = {
            "num_of_item": self.num_of_item,
            "weight_of_items": self.weight_of_items,
            "ship_name": self.name,
            "ship_add1": self.add1,
            "ship_add2": self.add2,
            "ship_area": self.area,
            "ship_city": self.city,
            "ship_sub_city": self.sub_city,
            "ship_state": self.state,
            "ship_postcode": self.postcode,
            "ship_country": self.country,
            "logistic_pickup_id": self.logistic_pickup_id,
            "logistic_delivery_type": self.logistic_delivery_type,
        }
        for k, v in fields.items():
            if v is not None and v != "":
                p[k] = str(v)
        upper = method.upper()
        if upper in ("YES", "SSLCOMMERZ_LOGISTIC"):
            for k in ("ship_name", "ship_add1", "ship_city", "ship_postcode", "ship_country"):
                if k not in p:
                    raise ValidationError(k, f"is required when shipping_method is {method}")
        if upper == "SSLCOMMERZ_LOGISTIC":
            for k in ("num_of_item", "weight_of_items", "logistic_pickup_id", "logistic_delivery_type"):
                if k not in p:
                    raise ValidationError(k, "is required for SSLCOMMERZ_LOGISTIC")
        return p


@dataclass
class Product:
    name: str
    category: str
    profile: str = "general"
    #: Vertical-specific fields (``hours_till_departure``, ``hotel_name``,
    #: ``topup_number`` and so on), sent as given.
    extra: Dict[str, str] = field(default_factory=dict)

    def to_params(self) -> Dict[str, str]:
        if self.profile not in PRODUCT_PROFILES:
            raise ValidationError("product_profile", f"must be one of {', '.join(PRODUCT_PROFILES)}")
        p = {
            "product_name": require_text("product_name", self.name, 255),
            "product_category": require_text("product_category", self.category, 100),
            "product_profile": self.profile,
        }
        p.update({k: str(v) for k, v in self.extra.items()})
        return p


@dataclass
class CartItem:
    product: str
    quantity: int = 1
    amount: Optional[AmountLike] = None
    unit_price: Optional[AmountLike] = None
    sku: Optional[str] = None

    def to_dict(self) -> Dict[str, str]:
        d: Dict[str, str] = {"product": self.product, "quantity": str(self.quantity)}
        if self.amount is not None:
            d["amount"] = format_amount("cart.amount", self.amount)
        if self.unit_price is not None:
            d["unit_price"] = format_amount("cart.unit_price", self.unit_price)
        if self.sku:
            d["sku"] = self.sku
        return d


@dataclass
class PaymentRequest:
    """Parameters for creating a payment session."""

    total_amount: AmountLike
    tran_id: str
    success_url: str
    fail_url: str
    cancel_url: str
    customer: Customer
    product: Product
    ipn_url: Optional[str] = None
    currency: str = "BDT"
    shipping: Shipping = field(default_factory=Shipping)
    emi_option: int = 0
    emi_max_inst_option: Optional[int] = None
    emi_selected_inst: Optional[int] = None
    emi_allow_only: Optional[int] = None
    multi_card_name: Optional[str] = None
    allowed_bin: Optional[str] = None
    cart: List[CartItem] = field(default_factory=list)
    product_amount: Optional[AmountLike] = None
    vat: Optional[AmountLike] = None
    discount_amount: Optional[AmountLike] = None
    convenience_fee: Optional[AmountLike] = None
    value_a: Optional[str] = None
    value_b: Optional[str] = None
    value_c: Optional[str] = None
    value_d: Optional[str] = None
    #: Extra parameters sent verbatim (they cannot override required fields).
    extra: Dict[str, str] = field(default_factory=dict)

    def to_params(self, *, enforce_amount_range: bool = True) -> Dict[str, str]:
        """Flatten into the form fields of the session API (without credentials)."""
        amount = format_amount("total_amount", self.total_amount)
        currency = require_text("currency", self.currency, 3).upper()
        if len(currency) != 3:
            raise ValidationError("currency", "must be a 3-letter code")
        in_range = Decimal(MIN_AMOUNT_BDT) <= Decimal(amount) <= Decimal(MAX_AMOUNT_BDT)
        if enforce_amount_range and currency == "BDT" and not in_range:
            raise ValidationError("total_amount", f"must be between {MIN_AMOUNT_BDT} and {MAX_AMOUNT_BDT} BDT")
        if self.emi_option not in (0, 1):
            raise ValidationError("emi_option", "must be 0 or 1")

        p: Dict[str, str] = {str(k): str(v) for k, v in self.extra.items()}
        p.update(
            {
                "total_amount": amount,
                "currency": currency,
                "tran_id": require_text("tran_id", self.tran_id, 30),
                "success_url": require_url("success_url", self.success_url),
                "fail_url": require_url("fail_url", self.fail_url),
                "cancel_url": require_url("cancel_url", self.cancel_url),
                "emi_option": str(self.emi_option),
            }
        )
        if self.ipn_url:
            p["ipn_url"] = require_url("ipn_url", self.ipn_url)
        for key in ("emi_max_inst_option", "emi_selected_inst", "emi_allow_only"):
            v = getattr(self, key)
            if v is not None:
                p[key] = str(v)
        for key, limit in (("multi_card_name", 255), ("allowed_bin", 255)):
            v = optional_text(key, getattr(self, key), limit)
            if v is not None:
                p[key] = v
        for key in ("product_amount", "vat", "discount_amount", "convenience_fee"):
            v = getattr(self, key)
            if v is not None:
                d = to_decimal(v)
                if d is None or d < 0:
                    raise ValidationError(key, "must be a non-negative amount")
                p[key] = "0.00" if d == 0 else format_amount(key, v)
        for key in ("value_a", "value_b", "value_c", "value_d"):
            v = optional_text(key, getattr(self, key), 255)
            if v is not None:
                p[key] = v
        if self.cart:
            p["cart"] = json.dumps([item.to_dict() for item in self.cart], separators=(",", ":"))
        p.update(self.customer.to_params())
        p.update(self.shipping.to_params())
        p.update(self.product.to_params())
        return p


# ---------------------------------------------------------------- responses


@dataclass
class SessionResponse:
    status: str
    sessionkey: Optional[str]
    gateway_page_url: Optional[str]
    failed_reason: Optional[str] = None
    gateways: Dict[str, Any] = field(default_factory=dict)
    desc: List[Dict[str, Any]] = field(default_factory=list)
    redirect_gateway_url: Optional[str] = None
    store_logo: Optional[str] = None
    store_banner: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def ok(self) -> bool:
        return self.status.upper() == "SUCCESS" and bool(self.gateway_page_url)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> SessionResponse:
        gw = d.get("gw")
        desc = d.get("desc")
        return cls(
            status=str(d.get("status") or ""),
            sessionkey=to_str(d.get("sessionkey")),
            gateway_page_url=to_str(d.get("GatewayPageURL")),
            failed_reason=to_str(d.get("failedreason")),
            gateways=dict(gw) if isinstance(gw, Mapping) else {},
            desc=list(desc) if isinstance(desc, list) else [],
            redirect_gateway_url=to_str(d.get("redirectGatewayURL")),
            store_logo=to_str(d.get("storeLogo")),
            store_banner=to_str(d.get("storeBanner")),
            raw=dict(d),
        )


@dataclass
class Transaction:
    """A transaction as returned by the Validation and Transaction Query APIs."""

    status: str
    tran_id: Optional[str] = None
    val_id: Optional[str] = None
    amount: Optional[Decimal] = None
    store_amount: Optional[Decimal] = None
    currency: Optional[str] = None
    bank_tran_id: Optional[str] = None
    tran_date: Optional[str] = None
    card_type: Optional[str] = None
    card_no: Optional[str] = None
    card_issuer: Optional[str] = None
    card_brand: Optional[str] = None
    card_issuer_country: Optional[str] = None
    card_issuer_country_code: Optional[str] = None
    currency_type: Optional[str] = None
    currency_amount: Optional[Decimal] = None
    currency_rate: Optional[Decimal] = None
    emi_instalment: Optional[str] = None
    emi_amount: Optional[Decimal] = None
    discount_amount: Optional[Decimal] = None
    discount_percentage: Optional[str] = None
    discount_remarks: Optional[str] = None
    risk_level: Optional[int] = None
    risk_title: Optional[str] = None
    value_a: Optional[str] = None
    value_b: Optional[str] = None
    value_c: Optional[str] = None
    value_d: Optional[str] = None
    validated_on: Optional[str] = None
    api_connect: Optional[str] = None
    sessionkey: Optional[str] = None
    error: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_paid(self) -> bool:
        """``VALID`` or ``VALIDATED``: the gateway received the money."""
        return self.status.upper() in PAID_STATUSES

    @property
    def is_high_risk(self) -> bool:
        """``risk_level == 1``: hold delivery and verify the customer."""
        return self.risk_level == 1

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Transaction:
        g = d.get
        return cls(
            status=str(g("status") or ""),
            tran_id=to_str(g("tran_id")),
            val_id=to_str(g("val_id")),
            amount=to_decimal(g("amount")),
            store_amount=to_decimal(g("store_amount")),
            currency=to_str(g("currency")),
            bank_tran_id=to_str(g("bank_tran_id")),
            tran_date=to_str(g("tran_date")),
            card_type=to_str(g("card_type")),
            card_no=to_str(g("card_no")),
            card_issuer=to_str(g("card_issuer")),
            card_brand=to_str(g("card_brand")),
            card_issuer_country=to_str(g("card_issuer_country")),
            card_issuer_country_code=to_str(g("card_issuer_country_code")),
            currency_type=to_str(g("currency_type")),
            currency_amount=to_decimal(g("currency_amount")),
            currency_rate=to_decimal(g("currency_rate")),
            emi_instalment=to_str(g("emi_instalment")),
            emi_amount=to_decimal(g("emi_amount")),
            discount_amount=to_decimal(g("discount_amount")),
            discount_percentage=to_str(g("discount_percentage")),
            discount_remarks=to_str(g("discount_remarks")),
            risk_level=to_int(g("risk_level")),
            risk_title=to_str(g("risk_title")),
            value_a=to_str(g("value_a")),
            value_b=to_str(g("value_b")),
            value_c=to_str(g("value_c")),
            value_d=to_str(g("value_d")),
            validated_on=to_str(g("validated_on")),
            api_connect=to_str(g("APIConnect")),
            sessionkey=to_str(g("sessionkey")),
            error=to_str(g("error")),
            raw=dict(d),
        )


@dataclass
class ValidationResult(Transaction):
    """Response of the Validation API (``validationserverAPI.php``)."""

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ValidationResult:
        base = Transaction.from_dict(d)
        return cls(**{f: getattr(base, f) for f in base.__dataclass_fields__})


@dataclass
class TransactionQueryResult:
    api_connect: Optional[str]
    transactions: List[Transaction]
    no_of_trans_found: int = 0
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def paid(self) -> Optional[Transaction]:
        """First transaction in a paid state, if any."""
        return next((t for t in self.transactions if t.is_paid), None)

    @property
    def is_paid(self) -> bool:
        return self.paid is not None

    @classmethod
    def from_tran_id_response(cls, d: Mapping[str, Any]) -> TransactionQueryResult:
        elements = d.get("element")
        items = (
            [Transaction.from_dict(e) for e in elements if isinstance(e, Mapping)] if isinstance(elements, list) else []
        )
        found = to_int(d.get("no_of_trans_found"))
        return cls(
            api_connect=to_str(d.get("APIConnect")),
            transactions=items,
            no_of_trans_found=found if found is not None else len(items),
            raw=dict(d),
        )

    @classmethod
    def from_session_response(cls, d: Mapping[str, Any]) -> TransactionQueryResult:
        has_txn = bool(d.get("status")) or bool(d.get("tran_id"))
        items = [Transaction.from_dict(d)] if has_txn else []
        return cls(
            api_connect=to_str(d.get("APIConnect")), transactions=items, no_of_trans_found=len(items), raw=dict(d)
        )


@dataclass
class RefundResult:
    api_connect: Optional[str]
    status: str
    bank_tran_id: Optional[str] = None
    trans_id: Optional[str] = None
    refund_ref_id: Optional[str] = None
    error_reason: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def accepted(self) -> bool:
        """``success`` (initiated now) or ``processing`` (already initiated)."""
        return self.status.lower() in ("success", "processing")

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> RefundResult:
        return cls(
            api_connect=to_str(d.get("APIConnect")),
            status=str(d.get("status") or ""),
            bank_tran_id=to_str(d.get("bank_tran_id")),
            trans_id=to_str(d.get("trans_id")),
            refund_ref_id=to_str(d.get("refund_ref_id")),
            error_reason=to_str(d.get("errorReason")),
            raw=dict(d),
        )


@dataclass
class RefundStatusResult:
    api_connect: Optional[str]
    status: str
    refund_ref_id: Optional[str] = None
    bank_tran_id: Optional[str] = None
    tran_id: Optional[str] = None
    initiated_on: Optional[str] = None
    refunded_on: Optional[str] = None
    error_reason: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_refunded(self) -> bool:
        return self.status.lower() == "refunded"

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> RefundStatusResult:
        return cls(
            api_connect=to_str(d.get("APIConnect")),
            status=str(d.get("status") or ""),
            refund_ref_id=to_str(d.get("refund_ref_id")),
            bank_tran_id=to_str(d.get("bank_tran_id")),
            tran_id=to_str(d.get("tran_id")),
            initiated_on=to_str(d.get("initiated_on")),
            refunded_on=to_str(d.get("refunded_on")),
            error_reason=to_str(d.get("errorReason")),
            raw=dict(d),
        )


@dataclass
class IPNPayload:
    """Fields SSLCommerz posts to the IPN listener (and to success/fail URLs)."""

    status: str
    tran_id: Optional[str]
    val_id: Optional[str]
    amount: Optional[Decimal]
    currency: Optional[str]
    store_amount: Optional[Decimal] = None
    bank_tran_id: Optional[str] = None
    tran_date: Optional[str] = None
    card_type: Optional[str] = None
    card_no: Optional[str] = None
    card_issuer: Optional[str] = None
    card_brand: Optional[str] = None
    currency_type: Optional[str] = None
    currency_amount: Optional[Decimal] = None
    risk_level: Optional[int] = None
    risk_title: Optional[str] = None
    value_a: Optional[str] = None
    value_b: Optional[str] = None
    value_c: Optional[str] = None
    value_d: Optional[str] = None
    verify_sign: Optional[str] = None
    verify_key: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_form(cls, form: Mapping[str, Any]) -> IPNPayload:
        """Build from a POSTed form (Flask ``request.form``, a dict, or ``parse_qs`` output)."""
        flat = {str(k): first(form, k) for k in form}
        g = flat.get
        return cls(
            status=str(g("status") or ""),
            tran_id=to_str(g("tran_id")),
            val_id=to_str(g("val_id")),
            amount=to_decimal(g("amount")),
            currency=to_str(g("currency")),
            store_amount=to_decimal(g("store_amount")),
            bank_tran_id=to_str(g("bank_tran_id")),
            tran_date=to_str(g("tran_date")),
            card_type=to_str(g("card_type")),
            card_no=to_str(g("card_no")),
            card_issuer=to_str(g("card_issuer")),
            card_brand=to_str(g("card_brand")),
            currency_type=to_str(g("currency_type")),
            currency_amount=to_decimal(g("currency_amount")),
            risk_level=to_int(g("risk_level")),
            risk_title=to_str(g("risk_title")),
            value_a=to_str(g("value_a")),
            value_b=to_str(g("value_b")),
            value_c=to_str(g("value_c")),
            value_d=to_str(g("value_d")),
            verify_sign=to_str(g("verify_sign")),
            verify_key=to_str(g("verify_key")),
            raw=flat,
        )
