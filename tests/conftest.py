"""Shared fixtures: a scripted httpx transport and gateway samples.

Sample bodies mirror the examples in the SSLCommerz v4 documentation, with
placeholder ids.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Union
from urllib.parse import parse_qsl

import httpx
import pytest

from sslcommerz_py import AsyncSSLCommerz, Config, Customer, PaymentRequest, Product, SSLCommerz, compute_signature

STORE_ID = "testbox"
STORE_PASSWD = "qwerty-placeholder"

Reply = Union[Dict[str, Any], httpx.Response, Exception, Callable[[httpx.Request], Any]]


class Router:
    """Records requests and answers from a queue per path (last reply repeats)."""

    def __init__(self) -> None:
        self.routes: Dict[str, List[Reply]] = {}
        self.requests: List[httpx.Request] = []

    def on(self, path: str, *replies: Reply) -> Router:
        self.routes.setdefault(path, []).extend(replies)
        return self

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        queue = self.routes.get(request.url.path)
        if not queue:
            return httpx.Response(404, json={"error": "no route"})
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if callable(reply) and not isinstance(reply, httpx.Response):
            reply = reply(request)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, httpx.Response):
            return reply
        return httpx.Response(200, json=reply)

    def count(self, path: str) -> int:
        return sum(1 for r in self.requests if r.url.path == path)

    def last(self, path: str) -> httpx.Request:
        return [r for r in self.requests if r.url.path == path][-1]

    @staticmethod
    def params(request: httpx.Request) -> Dict[str, str]:
        return dict(request.url.params)

    @staticmethod
    def form(request: httpx.Request) -> Dict[str, str]:
        return dict(parse_qsl(request.content.decode(), keep_blank_values=True))


SESSION = "/gwprocess/v4/api.php"
VALIDATION = "/validator/api/validationserverAPI.php"
MERCHANT = "/validator/api/merchantTransIDvalidationAPI.php"


@pytest.fixture
def router() -> Router:
    return Router()


@pytest.fixture
def config() -> Config:
    return Config(store_id=STORE_ID, store_passwd=STORE_PASSWD)


@pytest.fixture
def client(router: Router, config: Config) -> SSLCommerz:
    c = SSLCommerz(config=config, transport=httpx.MockTransport(router.handler), sleep=lambda _d: None, rnd=lambda: 1.0)
    yield c
    c.close()


@pytest.fixture
def async_client(router: Router, config: Config) -> AsyncSSLCommerz:
    return AsyncSSLCommerz(config=config, transport=httpx.MockTransport(router.handler), sleep=lambda _d: None)


@pytest.fixture
def payment_request() -> PaymentRequest:
    return PaymentRequest(
        total_amount="103.00",
        tran_id="SSLCZ_TEST_59bd349436a7b",
        success_url="https://shop.example.com/sslc/success",
        fail_url="https://shop.example.com/sslc/fail",
        cancel_url="https://shop.example.com/sslc/cancel",
        ipn_url="https://shop.example.com/sslc/ipn",
        customer=Customer(
            name="Test Customer",
            email="customer@example.com",
            phone="01711111111",
            add1="House 1, Road 2",
            city="Dhaka",
            postcode="1207",
        ),
        product=Product(name="T-shirt", category="clothing", profile="physical-goods"),
    )


def session_success(sessionkey: str = "F298BC45B0688E02768900C4F6B28C8B") -> Dict[str, Any]:
    return {
        "status": "SUCCESS",
        "failedreason": "",
        "sessionkey": sessionkey,
        "gw": {"visa": "city_visa,ebl_visa", "mobilebanking": "bkash,dbbl_mobile"},
        "GatewayPageURL": f"https://sandbox.sslcommerz.com/gwprocess/v4/gw.php?Q=PAY&SESSIONKEY={sessionkey}",
        "storeBanner": "https://sandbox.sslcommerz.com/stores/logos/demoLogo.png",
        "storeLogo": "https://sandbox.sslcommerz.com/stores/logos/demoLogo.png",
        "desc": [{"name": "BKash", "type": "mobilebanking", "gw": "bkash"}],
        "is_direct_pay_enable": "1",
    }


def validation_body(status: str = "VALID", **overrides: Any) -> Dict[str, Any]:
    body = {
        "status": status,
        "tran_date": "2017-09-16 20:25:33",
        "tran_id": "SSLCZ_TEST_59bd349436a7b",
        "val_id": "1709162025351ElIuHtUtFReBwE",
        "amount": "103.00",
        "store_amount": "98.88",
        "currency": "BDT",
        "bank_tran_id": "1709162025351S1ezyhmrA3T3Op",
        "card_type": "VISA-Brac bank",
        "card_no": "432149XXXXXX0667",
        "card_issuer": "BRAC BANK, LTD.",
        "card_brand": "VISA",
        "card_issuer_country": "Bangladesh",
        "card_issuer_country_code": "BD",
        "currency_type": "BDT",
        "currency_amount": "103.00",
        "currency_rate": "1.0000",
        "base_fair": "0.00",
        "value_a": "order-42",
        "value_b": "",
        "value_c": "",
        "value_d": "",
        "emi_instalment": "0",
        "emi_amount": "0.00",
        "risk_level": "0",
        "risk_title": "Safe",
        "APIConnect": "DONE",
        "validated_on": "2017-09-16 20:25:37",
        "gw_version": "",
    }
    body.update(overrides)
    return body


def ipn_form(status: str = "VALID", passwd: str = STORE_PASSWD, **overrides: Any) -> Dict[str, str]:
    form = {
        "tran_id": "SSLCZ_TEST_59bd349436a7b",
        "val_id": "1709162025351ElIuHtUtFReBwE",
        "amount": "103.00",
        "card_type": "VISA-Brac bank",
        "store_amount": "98.88",
        "card_no": "432149XXXXXX0667",
        "bank_tran_id": "1709162025351S1ezyhmrA3T3Op",
        "status": status,
        "tran_date": "2017-09-16 20:25:33",
        "currency": "BDT",
        "card_issuer": "BRAC BANK, LTD.",
        "card_brand": "VISA",
        "card_issuer_country": "Bangladesh",
        "card_issuer_country_code": "BD",
        "store_id": STORE_ID,
        "currency_type": "BDT",
        "currency_amount": "103.00",
        "currency_rate": "1.0000",
        "base_fair": "0.00",
        "value_a": "order-42",
        "value_b": "",
        "value_c": "",
        "value_d": "",
        "risk_level": "0",
        "risk_title": "Safe",
    }
    form.update({k: str(v) for k, v in overrides.items()})
    keys = [k for k in form if k not in ("verify_sign", "verify_key")]
    form["verify_key"] = ",".join(keys)
    form["verify_sign"] = compute_signature(form, passwd)
    return form


def as_json(response_body: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status, content=json.dumps(response_body).encode(), headers={"content-type": "application/json"}
    )
