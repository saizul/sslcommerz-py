import asyncio

import httpx
import pytest

from sslcommerz_py import AmountMismatchError, AsyncSSLCommerz, Config, RefundError

from .conftest import (
    MERCHANT,
    SESSION,
    STORE_ID,
    STORE_PASSWD,
    VALIDATION,
    Router,
    ipn_form,
    session_success,
    validation_body,
)


def run(coro):
    return asyncio.run(coro)


def test_async_session_and_ipn(async_client: AsyncSSLCommerz, router: Router, payment_request):
    router.on(SESSION, session_success()).on(VALIDATION, validation_body())

    async def flow():
        async with async_client as c:
            session = await c.create_session(payment_request)
            paid = await c.verify_ipn(ipn_form(), expected_amount="103.00", expected_currency="BDT")
            return session, paid

    session, paid = run(flow())
    assert session.ok
    assert paid.tran_id == "SSLCZ_TEST_59bd349436a7b"


def test_async_amount_mismatch(async_client, router):
    router.on(VALIDATION, validation_body(amount="1.00"))
    with pytest.raises(AmountMismatchError):
        run(async_client.verify_ipn(ipn_form(), expected_amount="103.00"))


def test_async_queries_and_refunds(async_client, router):
    router.on(
        MERCHANT,
        {"APIConnect": "DONE", "element": [validation_body()], "no_of_trans_found": 1},
        {"APIConnect": "DONE", "status": "failed", "errorReason": "nope"},
    )

    async def flow():
        q = await async_client.query_by_tran_id("T")
        with pytest.raises(RefundError):
            await async_client.refund(bank_tran_id="B", refund_amount=1, refund_remarks="r", refund_trans_id="R")
        await async_client.aclose()
        return q

    assert run(flow()).is_paid


def test_async_retry_with_coroutine_sleep(router):
    slept = []

    async def fake_sleep(d):
        slept.append(d)

    c = AsyncSSLCommerz(
        config=Config(STORE_ID, STORE_PASSWD), transport=httpx.MockTransport(router.handler), sleep=fake_sleep
    )
    router.on(VALIDATION, httpx.ConnectError("x"), validation_body())
    assert run(c.validate("v")).is_paid
    assert len(slept) == 1


def test_async_from_env():
    c = AsyncSSLCommerz.from_env({"SSLCOMMERZ_STORE_ID": "s", "SSLCOMMERZ_STORE_PASSWD": "p"})
    assert c.base_url.startswith("https://sandbox")
    run(c.aclose())
