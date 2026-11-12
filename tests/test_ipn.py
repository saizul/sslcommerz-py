from decimal import Decimal

import pytest

from sslcommerz_py import (
    AmountMismatchError,
    Config,
    HashVerificationError,
    InactiveStoreError,
    InvalidRequestError,
    IPNPayload,
    IPNVerifier,
    PaymentNotValidError,
    SSLCommerz,
    UnknownOrderError,
)

from .conftest import STORE_ID, STORE_PASSWD, VALIDATION, Router, ipn_form, validation_body


def test_validate_sends_documented_params(client, router: Router):
    router.on(VALIDATION, validation_body())
    res = client.validate("1709162025351ElIuHtUtFReBwE")
    assert res.is_paid
    assert res.amount == Decimal("103.00")
    assert res.risk_level == 0
    assert res.value_a == "order-42"
    params = Router.params(router.last(VALIDATION))
    assert params == {
        "val_id": "1709162025351ElIuHtUtFReBwE",
        "store_id": STORE_ID,
        "store_passwd": STORE_PASSWD,
        "format": "json",
        "v": "1",
    }
    assert router.last(VALIDATION).method == "GET"


def test_validate_invalid_transaction_is_returned(client, router):
    router.on(VALIDATION, {"status": "INVALID_TRANSACTION"})
    res = client.validate("x")
    assert not res.is_paid


@pytest.mark.parametrize(("value", "exc"), [("INVALID_REQUEST", InvalidRequestError), ("INACTIVE", InactiveStoreError)])
def test_api_connect_errors(client, router, value, exc):
    router.on(VALIDATION, {"APIConnect": value, "status": ""})
    with pytest.raises(exc):
        client.validate("x")


def test_verify_ipn_happy_path(client, router):
    router.on(VALIDATION, validation_body())
    paid = client.verify_ipn(
        ipn_form(), expected_tran_id="SSLCZ_TEST_59bd349436a7b", expected_amount="103", expected_currency="BDT"
    )
    assert paid.tran_id == "SSLCZ_TEST_59bd349436a7b"
    assert paid.amount == Decimal("103.00")
    assert not paid.already_validated
    assert not paid.is_high_risk


def test_verify_ipn_already_validated(client, router):
    router.on(VALIDATION, validation_body("VALIDATED"))
    assert client.verify_ipn(ipn_form(), expected_amount=103).already_validated


def test_bad_hash_stops_before_api_call(client, router):
    form = ipn_form()
    form["amount"] = "1.00"
    with pytest.raises(HashVerificationError):
        client.verify_ipn(form)
    assert router.requests == []


def test_hash_check_can_be_disabled(router):
    import httpx

    c = SSLCommerz(
        config=Config(STORE_ID, STORE_PASSWD, verify_hash=False), transport=httpx.MockTransport(router.handler)
    )
    router.on(VALIDATION, validation_body())
    form = ipn_form()
    form.pop("verify_sign")
    assert c.verify_ipn(form).tran_id


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED", "UNATTEMPTED", "EXPIRED"])
def test_non_valid_ipn_status(client, router, status):
    with pytest.raises(PaymentNotValidError) as info:
        client.verify_ipn(ipn_form(status))
    assert info.value.status == status
    assert router.requests == []


def test_validation_api_disagrees(client, router):
    router.on(VALIDATION, {"status": "INVALID_TRANSACTION", "APIConnect": "DONE"})
    with pytest.raises(PaymentNotValidError, match="INVALID_TRANSACTION"):
        client.verify_ipn(ipn_form())


def test_amount_mismatch(client, router):
    router.on(VALIDATION, validation_body(amount="50.00"))
    with pytest.raises(AmountMismatchError) as info:
        client.verify_ipn(ipn_form(), expected_amount="103.00")
    assert info.value.field == "amount"


def test_amount_tolerance(router):
    import httpx

    c = SSLCommerz(
        config=Config(STORE_ID, STORE_PASSWD, amount_tolerance="0.50"), transport=httpx.MockTransport(router.handler)
    )
    router.on(VALIDATION, validation_body(amount="102.60"))
    assert c.verify_ipn(ipn_form(), expected_amount="103.00")


def test_currency_mismatch(client, router):
    router.on(VALIDATION, validation_body(currency="USD"))
    with pytest.raises(AmountMismatchError, match="currency"):
        client.verify_ipn(ipn_form(), expected_currency="BDT")


def test_foreign_currency_uses_currency_amount(client, router):
    router.on(
        VALIDATION, validation_body(amount="1100.00", currency="BDT", currency_type="USD", currency_amount="10.00")
    )
    paid = client.verify_ipn(ipn_form(), expected_amount="10", expected_currency="usd")
    assert paid.validation.currency_amount == Decimal("10.00")


def test_tran_id_mismatch(client, router):
    router.on(VALIDATION, validation_body(tran_id="SOMETHING_ELSE"))
    with pytest.raises(AmountMismatchError, match="tran_id"):
        client.verify_ipn(ipn_form())
    with pytest.raises(AmountMismatchError, match="tran_id"):
        client.verify_ipn(ipn_form(), expected_tran_id="OTHER")


def test_high_risk_flag(client, router):
    router.on(VALIDATION, validation_body(risk_level="1", risk_title="High"))
    assert client.verify_ipn(ipn_form()).is_high_risk


def test_ipn_payload_parsing():
    p = IPNPayload.from_form({k: [v] for k, v in ipn_form().items()})
    assert p.status == "VALID"
    assert p.amount == Decimal("103.00")
    assert p.risk_level == 0
    assert p.verify_key and "tran_id" in p.verify_key


def test_missing_val_id(client):
    form = ipn_form()
    form.pop("val_id")
    form["verify_key"] = ",".join(k for k in form if k not in ("verify_sign", "verify_key"))
    from sslcommerz_py import compute_signature

    form["verify_sign"] = compute_signature(form, STORE_PASSWD)
    with pytest.raises(PaymentNotValidError, match="val_id"):
        client.verify_ipn(form)


def test_ipn_verifier_uses_order_lookup(client, router):
    router.on(VALIDATION, validation_body())
    orders = {"SSLCZ_TEST_59bd349436a7b": ("103.00", "BDT")}
    v = IPNVerifier(client, orders.get)
    out = v.handle(ipn_form())
    assert out.ok and out.payment is not None
    assert out.http_status == 200

    orders["SSLCZ_TEST_59bd349436a7b"] = ("200.00", "BDT")
    out = v.handle(ipn_form())
    assert not out.ok and isinstance(out.error, AmountMismatchError)

    out = v.handle(ipn_form("CANCELLED"))
    assert out.status == "CANCELLED"

    with pytest.raises(UnknownOrderError):
        IPNVerifier(client, lambda _t: None).verify(ipn_form())
