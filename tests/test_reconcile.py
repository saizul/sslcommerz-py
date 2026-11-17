import asyncio
import csv
import io
import json
from decimal import Decimal

import httpx
import pytest

from sslcommerz_py import (
    AuthenticationError,
    Config,
    ExpectedOrder,
    ReconcileStatus,
    SSLCommerz,
    TransactionQueryResult,
    ValidationError,
    areconcile,
    load_orders,
    reconcile,
)
from sslcommerz_py.cli import EXIT_API, EXIT_INVALID, EXIT_OK, EXIT_USAGE, main
from sslcommerz_py.reconcile import classify

from .conftest import MERCHANT, STORE_ID, STORE_PASSWD, validation_body

ENV = {"SSLCOMMERZ_STORE_ID": STORE_ID, "SSLCOMMERZ_STORE_PASSWD": STORE_PASSWD}


def txn(status="VALID", tran_id="INV-1", **overrides):
    return {**validation_body(status, tran_id=tran_id), **overrides}


def query_body(*elements):
    return {"APIConnect": "DONE", "no_of_trans_found": len(elements), "element": list(elements)}


def result(*elements):
    return TransactionQueryResult.from_tran_id_response(query_body(*elements))


def by_tran_id(bodies):
    """Answer the merchant API per ``tran_id`` query parameter."""

    def reply(request: httpx.Request):
        tid = request.url.params.get("tran_id")
        body = bodies[tid]
        if isinstance(body, Exception):
            raise body
        if isinstance(body, httpx.Response):
            return body
        return httpx.Response(200, json=body)

    return reply


# ----------------------------------------------------------------- classify


def test_classify_paid():
    res = classify(ExpectedOrder.create("INV-1", "103.00"), result(txn()))
    assert res.status is ReconcileStatus.PAID
    assert res.ok and not res.is_problem
    assert res.paid_amount == Decimal("103.00")
    assert res.paid_currency == "BDT"
    assert res.bank_tran_id == "1709162025351S1ezyhmrA3T3Op"
    assert res.detail == ""


def test_classify_paid_without_expected_amount():
    res = classify(ExpectedOrder.create("INV-1"), result(txn(amount="999.00")))
    assert res.status is ReconcileStatus.PAID


def test_classify_paid_after_failed_attempt():
    res = classify(ExpectedOrder.create("INV-1", 103), result(txn("FAILED"), txn("VALIDATED")))
    assert res.status is ReconcileStatus.PAID
    assert res.attempts == 2
    assert res.gateway_statuses == ["FAILED", "VALIDATED"]


def test_classify_amount_mismatch_and_tolerance():
    order = ExpectedOrder.create("INV-1", "103.00")
    short = result(txn(amount="102.50"))
    res = classify(order, short)
    assert res.status is ReconcileStatus.AMOUNT_MISMATCH
    assert res.is_problem
    assert "expected 103.00, got 102.50" in res.detail
    assert classify(order, short, tolerance=Decimal("0.50")).status is ReconcileStatus.PAID


def test_classify_currency_mismatch():
    res = classify(ExpectedOrder.create("INV-1", "10.00", "usd"), result(txn()))
    assert res.status is ReconcileStatus.CURRENCY_MISMATCH
    assert res.detail == "expected USD, got BDT"


def test_classify_foreign_currency_uses_original_amount():
    body = txn(amount="1180.00", currency="BDT", currency_type="USD", currency_amount="10.00")
    res = classify(ExpectedOrder.create("INV-1", "10.00", "USD"), result(body))
    assert res.status is ReconcileStatus.PAID
    assert res.paid_amount == Decimal("10.00")
    assert res.paid_currency == "USD"


def test_classify_multiple_payments():
    first = txn("VALID", val_id="V1", bank_tran_id="B1")
    second = txn("VALIDATED", val_id="V2", bank_tran_id="B2", risk_level="1")
    res = classify(ExpectedOrder.create("INV-1", "103.00"), result(first, second))
    assert res.status is ReconcileStatus.MULTIPLE_PAYMENTS
    assert res.paid_count == 2
    assert res.high_risk
    assert "B1, B2" in res.detail
    assert len(res.paid_transactions) == 2


def test_classify_same_payment_listed_twice_is_not_double():
    res = classify(ExpectedOrder.create("INV-1", "103.00"), result(txn("VALID"), txn("VALIDATED")))
    assert res.status is ReconcileStatus.PAID
    assert res.paid_count == 1


@pytest.mark.parametrize(
    ("elements", "status"),
    [
        ((), ReconcileStatus.NOT_FOUND),
        ((txn("FAILED"), txn("PENDING")), ReconcileStatus.PENDING),
        ((txn("FAILED"), txn("CANCELLED")), ReconcileStatus.NOT_PAID),
    ],
)
def test_classify_unpaid(elements, status):
    res = classify(ExpectedOrder.create("INV-1", "103.00"), result(*elements))
    assert res.status is status
    assert not res.is_problem
    assert res.paid_amount is None


def test_classify_ignores_other_tran_ids():
    res = classify(ExpectedOrder.create("INV-1"), result(txn("VALID", tran_id="INV-2")))
    assert res.status is ReconcileStatus.NOT_FOUND


# -------------------------------------------------------------- ExpectedOrder


@pytest.mark.parametrize(
    ("args", "field"),
    [
        (("",), "tran_id"),
        (("X" * 31,), "tran_id"),
        (("INV-1", "abc"), "amount"),
        (("INV-1", "1.234"), "amount"),
        (("INV-1", "10", "TAKA"), "currency"),
    ],
)
def test_expected_order_rejects_bad_values(args, field):
    with pytest.raises(ValidationError) as exc:
        ExpectedOrder.create(*args)
    assert exc.value.field == field


def test_expected_order_normalises():
    order = ExpectedOrder.create(" INV-1 ", " 50 ", " usd ")
    assert order == ExpectedOrder("INV-1", Decimal("50.00"), "USD")


# ------------------------------------------------------------------ loading


def test_load_orders_aliases_delimiters_and_blank_rows():
    text = "﻿Order ID;Total Amount;Currency\nINV-1;103.00;bdt\n\n;;\nINV-2;;\n"
    orders = load_orders(io.StringIO(text))
    assert orders == [
        ExpectedOrder("INV-1", Decimal("103.00"), "BDT"),
        ExpectedOrder("INV-2", None, "BDT"),
    ]


def test_load_orders_from_path(tmp_path):
    path = tmp_path / "orders.csv"
    path.write_text("tran_id,amount\nINV-1,10\n", encoding="utf-8")
    assert load_orders(str(path)) == [ExpectedOrder("INV-1", Decimal("10.00"), "BDT")]


def test_load_orders_needs_tran_id_column():
    with pytest.raises(ValidationError, match="tran_id column"):
        load_orders(io.StringIO("id,amount\n1,10\n"))


def test_load_orders_reports_line_number():
    with pytest.raises(ValidationError, match="line 3"):
        load_orders(io.StringIO("tran_id,amount\nINV-1,10\nINV-2,ten\n"))


def test_load_orders_empty():
    assert load_orders(io.StringIO("")) == []


# ------------------------------------------------------------------- runner


def test_reconcile_runs_every_order_and_keeps_going(client, router):
    router.on(
        MERCHANT,
        by_tran_id(
            {
                "INV-1": query_body(txn(tran_id="INV-1")),
                "INV-2": query_body(),
                "INV-3": httpx.Response(500, text="oops"),
                "INV-4": query_body(txn(tran_id="INV-4", amount="1.00")),
            }
        ),
    )
    orders = [ExpectedOrder.create(t, "103.00") for t in ("INV-1", "INV-2", "INV-3", "INV-4")]
    seen = []
    report = reconcile(client, orders, on_result=seen.append)
    assert [r.status for r in report.results] == [
        ReconcileStatus.PAID,
        ReconcileStatus.NOT_FOUND,
        ReconcileStatus.ERROR,
        ReconcileStatus.AMOUNT_MISMATCH,
    ]
    assert seen == report.results
    assert report.results[2].error is not None
    assert report.has_problems
    assert [r.tran_id for r in report.problems] == ["INV-3", "INV-4"]
    assert [r.tran_id for r in report.unpaid] == ["INV-2"]
    counts = report.counts()
    assert counts["paid"] == 1 and counts["error"] == 1 and counts["pending"] == 0
    # Every query is read-only and goes to the merchant API only.
    assert {r.url.path for r in router.requests} == {MERCHANT}
    assert all(r.method == "GET" for r in router.requests)


def test_reconcile_uses_config_tolerance(router):
    router.on(MERCHANT, query_body(txn(amount="102.99")))
    config = Config(store_id=STORE_ID, store_passwd=STORE_PASSWD, amount_tolerance=Decimal("0.01"))
    loose = SSLCommerz(config=config, transport=httpx.MockTransport(router.handler))
    report = reconcile(loose, [ExpectedOrder.create("INV-1", "103.00")])
    assert report.results[0].status is ReconcileStatus.PAID
    report = reconcile(loose, [ExpectedOrder.create("INV-1", "103.00")], tolerance="0")
    assert report.results[0].status is ReconcileStatus.AMOUNT_MISMATCH
    loose.close()


def test_reconcile_stops_on_authentication_error(client, router):
    router.on(MERCHANT, {"APIConnect": "FAILED"})
    with pytest.raises(AuthenticationError):
        reconcile(client, [ExpectedOrder.create("INV-1"), ExpectedOrder.create("INV-2")])
    assert router.count(MERCHANT) == 1


def test_reconcile_rejects_duplicate_orders(client, router):
    with pytest.raises(ValidationError, match="duplicate"):
        reconcile(client, [ExpectedOrder.create("INV-1"), ExpectedOrder.create("INV-1")])
    assert router.requests == []


def test_reconcile_delay_between_queries(client, router):
    router.on(MERCHANT, query_body())
    pauses = []
    orders = [ExpectedOrder.create(t) for t in ("A", "B", "C")]
    reconcile(client, orders, delay=0.25, sleep=pauses.append)
    assert pauses == [0.25, 0.25]


def test_areconcile_keeps_input_order(async_client, router):
    router.on(
        MERCHANT,
        by_tran_id({"A": query_body(txn(tran_id="A")), "B": query_body(txn("FAILED", tran_id="B"))}),
    )

    async def go():
        async with async_client as c:
            return await areconcile(c, [ExpectedOrder.create("A", 103), ExpectedOrder.create("B")], concurrency=2)

    report = asyncio.run(go())
    assert [(r.tran_id, r.status) for r in report.results] == [
        ("A", ReconcileStatus.PAID),
        ("B", ReconcileStatus.NOT_PAID),
    ]


def test_areconcile_rejects_bad_concurrency(async_client):
    with pytest.raises(ValidationError):
        asyncio.run(areconcile(async_client, [], concurrency=0))


# ---------------------------------------------------------------- reporting


def test_report_json_and_csv(client, router):
    router.on(MERCHANT, query_body(txn(tran_id="INV-1", bank_tran_id="=HYPERLINK(1)")))
    report = reconcile(client, [ExpectedOrder.create("INV-1", "103.00")])
    data = report.to_dict()
    assert data["summary"]["total"] == 1
    assert data["summary"]["paid"] == 1
    row = data["results"][0]
    assert row["paid_amount"] == "103.00"
    assert row["expected_amount"] == "103.00"
    json.dumps(data)  # serialisable

    rows = list(csv.DictReader(io.StringIO(report.to_csv())))
    assert rows[0]["status"] == "paid"
    assert rows[0]["high_risk"] == "no"
    # Values from the gateway cannot become spreadsheet formulas.
    assert rows[0]["bank_tran_id"] == "'=HYPERLINK(1)"


# ---------------------------------------------------------------------- CLI


def run_cli(router, *argv, stdin=None):
    out, err = io.StringIO(), io.StringIO()

    def factory(config):
        return SSLCommerz(config=config, transport=httpx.MockTransport(router.handler), sleep=lambda _d: None)

    code = main(list(argv), env=ENV, client_factory=factory, stdout=out, stderr=err, stdin=stdin)
    return code, out.getvalue(), err.getvalue()


def test_cli_reconcile_csv_from_stdin(router):
    router.on(MERCHANT, by_tran_id({"INV-1": query_body(txn(tran_id="INV-1")), "INV-2": query_body()}))
    stdin = io.StringIO("tran_id,amount,currency\nINV-1,103.00,BDT\nINV-2,50.00,BDT\n")
    code, out, _ = run_cli(router, "reconcile", "-", stdin=stdin)
    assert code == EXIT_OK
    data = json.loads(out)
    assert data["summary"]["paid"] == 1
    assert data["summary"]["not_found"] == 1
    assert STORE_PASSWD not in out


def test_cli_reconcile_fail_on_unpaid(router):
    router.on(MERCHANT, query_body())
    code, _, _ = run_cli(router, "reconcile", "--tran-id", "INV-1", "--fail-on", "unpaid")
    assert code == EXIT_INVALID
    code, _, _ = run_cli(router, "reconcile", "--tran-id", "INV-1")
    assert code == EXIT_OK


def test_cli_reconcile_problems_exit_and_csv_output(router, tmp_path):
    router.on(MERCHANT, query_body(txn(tran_id="INV-1", amount="1.00")))
    orders = tmp_path / "orders.csv"
    orders.write_text("tran_id,amount\nINV-1,103.00\n", encoding="utf-8")
    report = tmp_path / "report.csv"
    code, out, _ = run_cli(router, "reconcile", str(orders), "--format", "csv", "-o", str(report))
    assert code == EXIT_INVALID
    assert out == ""
    rows = list(csv.DictReader(report.open(encoding="utf-8")))
    assert rows[0]["status"] == "amount_mismatch"

    code, _, _ = run_cli(router, "reconcile", str(orders), "--fail-on", "never")
    assert code == EXIT_OK
    code, _, _ = run_cli(router, "reconcile", str(orders), "--tolerance", "102")
    assert code == EXIT_OK


def test_cli_reconcile_usage_errors(router, tmp_path):
    code, _, err = run_cli(router, "reconcile")
    assert code == EXIT_USAGE
    assert "--tran-id" in err
    bad = tmp_path / "bad.csv"
    bad.write_text("order,amount\nINV-1,10\n", encoding="utf-8")
    code, _, err = run_cli(router, "reconcile", str(bad))
    assert code == EXIT_USAGE
    assert "tran_id column" in err
    code, _, _ = run_cli(router, "reconcile", "--tran-id", "A", "--tolerance", "lots")
    assert code == EXIT_USAGE
    code, _, err = run_cli(router, "reconcile", str(tmp_path / "missing.csv"))
    assert code == EXIT_USAGE
    assert router.requests == []


def test_cli_reconcile_authentication_failure(router):
    router.on(MERCHANT, {"APIConnect": "FAILED"})
    code, _, err = run_cli(router, "reconcile", "--tran-id", "A", "--tran-id", "B")
    assert code == EXIT_API
    assert "authentication" in err
    assert router.count(MERCHANT) == 1


def test_example_orders_csv_loads():
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "examples" / "orders.csv"
    orders = load_orders(str(path))
    assert [o.currency for o in orders] == ["BDT", "BDT", "USD"]


def test_cli_reconcile_non_utf8_file_is_usage_error(router, tmp_path):
    path = tmp_path / "latin1.csv"
    path.write_bytes(b"tran_id,amount\nINV-\xe9,10\n")
    code, _, err = run_cli(router, "reconcile", str(path))
    assert code == EXIT_USAGE
    assert err.startswith("error:")
