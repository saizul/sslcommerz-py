from decimal import Decimal

import httpx
import pytest

from sslcommerz_py import NetworkError, RefundError, ValidationError

from .conftest import MERCHANT, STORE_ID, STORE_PASSWD, Router, validation_body


def test_query_by_session(client, router: Router):
    router.on(MERCHANT, {**validation_body(), "sessionkey": "SESSION123"})
    res = client.query_by_session("SESSION123")
    assert res.is_paid
    assert res.transactions[0].sessionkey == "SESSION123"
    assert Router.params(router.last(MERCHANT)) == {
        "sessionkey": "SESSION123",
        "store_id": STORE_ID,
        "store_passwd": STORE_PASSWD,
        "format": "json",
        "v": "1",
    }


def test_query_by_session_without_transaction(client, router):
    router.on(MERCHANT, {"APIConnect": "DONE"})
    res = client.query_by_session("S")
    assert res.transactions == []
    assert not res.is_paid


def test_query_by_tran_id(client, router):
    router.on(
        MERCHANT,
        {
            "APIConnect": "DONE",
            "no_of_trans_found": 2,
            "element": [
                {**validation_body("FAILED"), "error": "Declined"},
                {**validation_body("VALIDATED"), "error": ""},
            ],
        },
    )
    res = client.query_by_tran_id("SSLCZ_TEST_59bd349436a7b")
    assert res.no_of_trans_found == 2
    assert res.transactions[0].error == "Declined"
    assert res.paid is not None and res.paid.status == "VALIDATED"
    assert Router.params(router.last(MERCHANT))["tran_id"] == "SSLCZ_TEST_59bd349436a7b"


def test_query_pending(client, router):
    router.on(MERCHANT, {"APIConnect": "DONE", "no_of_trans_found": "1", "element": [validation_body("PENDING")]})
    res = client.query_by_tran_id("T")
    assert not res.is_paid
    assert res.no_of_trans_found == 1


def test_query_retries_network_errors(client, router):
    router.on(MERCHANT, httpx.ConnectError("reset"), httpx.ReadTimeout("slow"), {"APIConnect": "DONE", "element": []})
    client.query_by_tran_id("T")
    assert router.count(MERCHANT) == 3


def test_query_gives_up(client, router):
    router.on(MERCHANT, httpx.ConnectError("reset"))
    with pytest.raises(NetworkError):
        client.query_by_tran_id("T")
    assert router.count(MERCHANT) == 3


REFUND_OK = {
    "APIConnect": "DONE",
    "bank_tran_id": "1709162345070ANJdZV8LyI4cMw",
    "trans_id": "SSLCZ_TEST_59bd635981a94",
    "refund_ref_id": "59bd63fea5455",
    "status": "success",
    "errorReason": "",
}


def test_refund_sends_documented_params(client, router):
    router.on(MERCHANT, REFUND_OK)
    res = client.refund(
        bank_tran_id="1709162345070ANJdZV8LyI4cMw",
        refund_amount=50,
        refund_remarks="Out of stock",
        refund_trans_id="REF-1001",
        refe_id="ORDER-42",
    )
    assert res.accepted
    assert res.refund_ref_id == "59bd63fea5455"
    assert Router.params(router.last(MERCHANT)) == {
        "bank_tran_id": "1709162345070ANJdZV8LyI4cMw",
        "refund_trans_id": "REF-1001",
        "refund_amount": "50.00",
        "refund_remarks": "Out of stock",
        "store_id": STORE_ID,
        "store_passwd": STORE_PASSWD,
        "format": "json",
        "v": "1",
        "refe_id": "ORDER-42",
    }


def test_refund_processing_is_accepted(client, router):
    router.on(MERCHANT, {**REFUND_OK, "status": "processing"})
    assert client.refund(bank_tran_id="B", refund_amount="1", refund_remarks="r", refund_trans_id="R").accepted


def test_refund_failed(client, router):
    router.on(MERCHANT, {"APIConnect": "DONE", "status": "failed", "errorReason": "Invalid bank_tran_id"})
    with pytest.raises(RefundError) as info:
        client.refund(bank_tran_id="B", refund_amount="1", refund_remarks="r", refund_trans_id="R")
    assert info.value.reason == "Invalid bank_tran_id"


def test_refund_never_retried(client, router):
    router.on(MERCHANT, httpx.ReadTimeout("slow"))
    with pytest.raises(NetworkError):
        client.refund(bank_tran_id="B", refund_amount="1", refund_remarks="r", refund_trans_id="R")
    assert router.count(MERCHANT) == 1


def test_refund_validation(client, router):
    with pytest.raises(ValidationError, match="refund_trans_id"):
        client.refund(bank_tran_id="B", refund_amount="1", refund_remarks="r", refund_trans_id="x" * 31)
    with pytest.raises(ValidationError, match="refund_amount"):
        client.refund(bank_tran_id="B", refund_amount="0", refund_remarks="r", refund_trans_id="R")
    with pytest.raises(ValidationError, match="refund_remarks"):
        client.refund(bank_tran_id="B", refund_amount="1", refund_remarks="", refund_trans_id="R")
    assert router.requests == []


def test_refund_status(client, router):
    router.on(
        MERCHANT,
        {
            "APIConnect": "DONE",
            "bank_tran_id": "1709162345070ANJdZV8LyI4cMw",
            "tran_id": "SSLCZ_TEST_59bd635981a94",
            "initiated_on": "2017-09-16 23:48:46",
            "refunded_on": "2017-09-17 08:53:51",
            "status": "refunded",
            "refund_ref_id": "59bd63fea5455",
            "errorReason": "",
        },
    )
    res = client.refund_status("59bd63fea5455")
    assert res.is_refunded
    assert res.refunded_on == "2017-09-17 08:53:51"
    assert Router.params(router.last(MERCHANT)) == {
        "refund_ref_id": "59bd63fea5455",
        "store_id": STORE_ID,
        "store_passwd": STORE_PASSWD,
        "format": "json",
    }


def test_refund_status_without_status(client, router):
    router.on(MERCHANT, {"APIConnect": "DONE", "errorReason": "Invalid refund_ref_id"})
    with pytest.raises(RefundError, match="Invalid refund_ref_id"):
        client.refund_status("X")


def test_decimal_fields(client, router):
    router.on(MERCHANT, {**validation_body(), "sessionkey": "S"})
    t = client.query_by_session("S").transactions[0]
    assert t.store_amount == Decimal("98.88")
    assert t.currency_rate == Decimal("1.0000")
