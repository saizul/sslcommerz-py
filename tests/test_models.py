import json
from decimal import Decimal

import pytest

from sslcommerz_py import CartItem, Customer, Product, Shipping, ValidationError
from sslcommerz_py._util import format_amount


@pytest.mark.parametrize(
    ("value", "expected"),
    [(10, "10.00"), ("10", "10.00"), ("10.5", "10.50"), (10.25, "10.25"), (Decimal("99.99"), "99.99")],
)
def test_format_amount(value, expected):
    assert format_amount("a", value) == expected


@pytest.mark.parametrize("value", ["10.555", 10.555, "-1", 0, "abc", True, None, float("inf"), Decimal("NaN")])
def test_format_amount_rejects(value):
    with pytest.raises(ValidationError):
        format_amount("a", value)


def test_to_params_required_fields(payment_request):
    p = payment_request.to_params()
    assert p["total_amount"] == "103.00"
    assert p["currency"] == "BDT"
    assert p["tran_id"] == "SSLCZ_TEST_59bd349436a7b"
    assert p["ipn_url"] == "https://shop.example.com/sslc/ipn"
    assert p["cus_name"] == "Test Customer"
    assert p["cus_country"] == "Bangladesh"
    assert p["shipping_method"] == "NO"
    assert p["product_profile"] == "physical-goods"
    assert p["emi_option"] == "0"
    assert "store_passwd" not in p
    assert all(isinstance(v, str) for v in p.values())


def test_amount_range(payment_request):
    payment_request.total_amount = "9.99"
    with pytest.raises(ValidationError, match="between"):
        payment_request.to_params()
    assert payment_request.to_params(enforce_amount_range=False)["total_amount"] == "9.99"
    payment_request.total_amount = "500000.01"
    with pytest.raises(ValidationError):
        payment_request.to_params()


def test_range_only_for_bdt(payment_request):
    payment_request.total_amount = "5"
    payment_request.currency = "usd"
    assert payment_request.to_params()["currency"] == "USD"


def test_tran_id_length(payment_request):
    payment_request.tran_id = "x" * 31
    with pytest.raises(ValidationError, match="30"):
        payment_request.to_params()


def test_urls_must_be_absolute(payment_request):
    payment_request.success_url = "/success"
    with pytest.raises(ValidationError, match="absolute"):
        payment_request.to_params()


def test_customer_email_and_optional_fields():
    c = Customer(name="A", email="a@example.com", phone="1", add1="x", city="Dhaka", postcode="1000", state="Dhaka")
    assert c.to_params()["cus_state"] == "Dhaka"
    with pytest.raises(ValidationError, match="email"):
        Customer(name="A", email="nope", phone="1", add1="x", city="D", postcode="1").to_params()


def test_shipping_yes_requires_address():
    with pytest.raises(ValidationError, match="ship_name"):
        Shipping(method="YES").to_params()
    p = Shipping(
        method="YES", name="A", add1="B", city="Dhaka", postcode="1000", country="Bangladesh", num_of_item=2
    ).to_params()
    assert p["ship_city"] == "Dhaka"
    assert p["num_of_item"] == "2"


def test_logistic_requires_extra_fields():
    s = Shipping(method="SSLCOMMERZ_LOGISTIC", name="A", add1="B", city="C", postcode="1", country="BD")
    with pytest.raises(ValidationError, match="SSLCOMMERZ_LOGISTIC"):
        s.to_params()


def test_product_profile_validated():
    with pytest.raises(ValidationError, match="product_profile"):
        Product(name="x", category="y", profile="weird").to_params()
    p = Product(name="Ticket", category="travel", profile="airline-tickets", extra={"pnr": "ABC123"}).to_params()
    assert p["pnr"] == "ABC123"


def test_cart_and_amount_breakdown(payment_request):
    payment_request.cart = [CartItem(product="T-shirt", quantity=2, amount="100", unit_price=50, sku="TS-1")]
    payment_request.vat = 0
    payment_request.discount_amount = "3"
    payment_request.value_a = "order-42"
    p = payment_request.to_params()
    assert json.loads(p["cart"]) == [
        {"product": "T-shirt", "quantity": "2", "amount": "100.00", "unit_price": "50.00", "sku": "TS-1"}
    ]
    assert p["vat"] == "0.00"
    assert p["discount_amount"] == "3.00"
    assert p["value_a"] == "order-42"


def test_negative_fee_rejected(payment_request):
    payment_request.vat = "-1"
    with pytest.raises(ValidationError, match="non-negative"):
        payment_request.to_params()


def test_extra_cannot_override_required(payment_request):
    payment_request.extra = {"total_amount": "1", "multi_card_name": "x", "custom": "y"}
    p = payment_request.to_params()
    assert p["total_amount"] == "103.00"
    assert p["custom"] == "y"


def test_emi_option(payment_request):
    payment_request.emi_option = 2
    with pytest.raises(ValidationError):
        payment_request.to_params()
    payment_request.emi_option = 1
    payment_request.emi_max_inst_option = 12
    assert payment_request.to_params()["emi_max_inst_option"] == "12"
