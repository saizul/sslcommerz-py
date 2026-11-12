import io
import json

import httpx

from sslcommerz_py import SSLCommerz
from sslcommerz_py.cli import EXIT_API, EXIT_INVALID, EXIT_NETWORK, EXIT_OK, EXIT_USAGE, main

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

ENV = {"SSLCOMMERZ_STORE_ID": STORE_ID, "SSLCOMMERZ_STORE_PASSWD": STORE_PASSWD}


def run(router: Router, *argv, env=None, stdin=None):
    out, err = io.StringIO(), io.StringIO()

    def factory(config):
        return SSLCommerz(config=config, transport=httpx.MockTransport(router.handler), sleep=lambda _d: None)

    code = main(
        list(argv), env=ENV if env is None else env, client_factory=factory, stdout=out, stderr=err, stdin=stdin
    )
    return code, out.getvalue(), err.getvalue()


def test_init(router):
    router.on(SESSION, session_success())
    code, out, _ = run(
        router,
        "init",
        "--amount",
        "150",
        "--tran-id",
        "INV-1",
        "--success-url",
        "https://shop.example.com/s",
        "--fail-url",
        "https://shop.example.com/f",
        "--cancel-url",
        "https://shop.example.com/c",
        "--cus-name",
        "A",
        "--cus-email",
        "a@example.com",
        "--cus-phone",
        "017",
        "--cus-add1",
        "Dhaka",
        "--product-name",
        "Book",
    )
    assert code == EXIT_OK
    data = json.loads(out)
    assert data["gateway_page_url"].startswith("https://sandbox.sslcommerz.com")
    assert "raw" not in data
    assert Router.form(router.last(SESSION))["total_amount"] == "150.00"


def test_validate_paid_and_invalid(router):
    router.on(VALIDATION, validation_body(), {"status": "INVALID_TRANSACTION"})
    code, out, _ = run(router, "--pretty", "--raw", "validate", "VAL1")
    assert code == EXIT_OK
    data = json.loads(out)
    assert data["amount"] == "103.00"
    assert data["raw"]["APIConnect"] == "DONE"
    code, _, _ = run(router, "validate", "VAL1")
    assert code == EXIT_INVALID


def test_query_both_modes(router):
    router.on(MERCHANT, {"APIConnect": "DONE", "element": [validation_body()], "no_of_trans_found": 1})
    code, out, _ = run(router, "query", "--tran-id", "T")
    assert code == EXIT_OK and json.loads(out)["no_of_trans_found"] == 1
    code, _, _ = run(router, "query", "--session-key", "S")
    assert code == EXIT_OK
    assert Router.params(router.last(MERCHANT))["sessionkey"] == "S"


def test_refund_and_status(router):
    router.on(
        MERCHANT,
        {"APIConnect": "DONE", "status": "success", "refund_ref_id": "R1"},
        {"APIConnect": "DONE", "status": "refunded", "refund_ref_id": "R1"},
    )
    code, out, _ = run(
        router, "refund", "--bank-tran-id", "B", "--amount", "10", "--remarks", "x", "--refund-trans-id", "RT1"
    )
    assert code == EXIT_OK and json.loads(out)["refund_ref_id"] == "R1"
    code, out, _ = run(router, "refund-status", "R1")
    assert code == EXIT_OK and json.loads(out)["status"] == "refunded"


def test_api_error_exit_code(router):
    router.on(MERCHANT, {"APIConnect": "DONE", "status": "failed", "errorReason": "bad"})
    code, _, err = run(
        router, "refund", "--bank-tran-id", "B", "--amount", "10", "--remarks", "x", "--refund-trans-id", "RT1"
    )
    assert code == EXIT_API
    assert "bad" in err


def test_network_error_exit_code(router):
    router.on(VALIDATION, httpx.ConnectError("down"))
    code, _, err = run(router, "validate", "V")
    assert code == EXIT_NETWORK
    assert STORE_PASSWD not in err


def test_missing_credentials(router):
    code, _, err = run(router, "validate", "V", env={})
    assert code == EXIT_USAGE
    assert "store_id" in err


def test_flags_override_env(router):
    router.on(VALIDATION, validation_body())
    code, _, _ = run(router, "--store-id", "other", "--store-passwd", "pw", "--env", "live", "validate", "V")
    assert code == EXIT_OK
    req = router.last(VALIDATION)
    assert req.url.host == "securepay.sslcommerz.com"
    assert Router.params(req)["store_id"] == "other"


def test_verify_hash_json_and_form(router, tmp_path):
    form = ipn_form()
    f = tmp_path / "ipn.json"
    f.write_text(json.dumps(form))
    code, out, _ = run(router, "verify-hash", str(f))
    assert code == EXIT_OK and json.loads(out)["valid"] is True

    from urllib.parse import urlencode

    form["amount"] = "1.00"
    code, out, _ = run(router, "verify-hash", "-", stdin=io.StringIO(urlencode(form)))
    assert code == EXIT_INVALID and json.loads(out)["valid"] is False
    assert router.requests == []


def test_usage_errors(router, tmp_path):
    code, _, _ = run(router)
    assert code == EXIT_USAGE
    code, _, _ = run(router, "verify-hash", str(tmp_path / "missing.json"))
    assert code == EXIT_USAGE
    code, _, _ = run(router, "validate", "")
    assert code == EXIT_USAGE


def test_version(capsys):
    assert main(["--version"]) == 0
    assert "sslcommerz" in capsys.readouterr().out
