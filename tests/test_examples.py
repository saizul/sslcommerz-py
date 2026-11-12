"""Runs the web framework examples against the mocked gateway."""

import asyncio
import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

from sslcommerz_py import AsyncSSLCommerz, Config, SSLCommerz

from .conftest import SESSION, STORE_ID, STORE_PASSWD, VALIDATION, Router, ipn_form, session_success, validation_body

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"example_{name}", EXAMPLES / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_flask_example(router: Router):
    pytest.importorskip("flask")
    client = SSLCommerz(config=Config(STORE_ID, STORE_PASSWD), transport=httpx.MockTransport(router.handler))
    orders = {}
    app = load("flask_app").create_app(client, orders).test_client()

    router.on(SESSION, session_success())
    res = app.post("/checkout")
    assert res.status_code == 303
    assert res.headers["Location"].startswith("https://sandbox.sslcommerz.com/gwprocess/v4/gw.php")
    tran_id = next(iter(orders))
    assert orders[tran_id]["status"] == "pending"

    router.on(VALIDATION, validation_body(tran_id=tran_id, amount="1250.00"))
    form = ipn_form(tran_id=tran_id, amount="1250.00")
    assert app.post("/sslc/ipn", data=form).status_code == 200
    assert orders[tran_id]["status"] == "paid"
    assert app.post("/sslc/success", data=form).get_json()["status"] == "paid"

    tampered = dict(form, amount="1.00")
    assert app.post("/sslc/ipn", data=tampered).status_code == 200
    assert orders[tran_id]["status"] == "paid"
    assert app.post("/sslc/success", data={"tran_id": "nope"}).status_code == 404


def test_flask_example_failed_payment(router: Router):
    pytest.importorskip("flask")
    client = SSLCommerz(config=Config(STORE_ID, STORE_PASSWD), transport=httpx.MockTransport(router.handler))
    orders = {"T1": {"amount": "103.00", "currency": "BDT", "status": "pending"}}
    app = load("flask_app").create_app(client, orders).test_client()
    app.post("/sslc/ipn", data=ipn_form("FAILED", tran_id="T1"))
    assert orders["T1"]["status"] == "failed"
    assert router.requests == []


def test_fastapi_example(router: Router):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    client = AsyncSSLCommerz(config=Config(STORE_ID, STORE_PASSWD), transport=httpx.MockTransport(router.handler))
    orders = {"SSLCZ_TEST_59bd349436a7b": {"amount": "103.00", "currency": "BDT", "status": "pending"}}
    app = load("fastapi_app").create_app(client, orders)
    router.on(VALIDATION, validation_body())

    async def call():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            r = await http.post("/sslc/ipn", data=ipn_form())
            assert r.status_code == 200
            r = await http.post("/sslc/ipn", data=ipn_form(tran_id="UNKNOWN"))
            assert r.status_code == 200
            return (await http.get("/orders/SSLCZ_TEST_59bd349436a7b")).json()

    assert asyncio.run(call())["status"] == "paid"
