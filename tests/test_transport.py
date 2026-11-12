import logging

import httpx
import pytest

from sslcommerz_py import Config, NetworkError, ResponseError, RetryPolicy, SSLCommerz, TimeoutError
from sslcommerz_py.redact import REDACTED, mask_card, redact

from .conftest import STORE_ID, STORE_PASSWD, VALIDATION, Router, validation_body


def test_backoff_delays():
    p = RetryPolicy(base_delay=1, factor=2, max_delay=3, jitter=False)
    assert [p.delay(n) for n in (1, 2, 3, 4)] == [1, 2, 3, 3]
    assert RetryPolicy(base_delay=1, jitter=True).delay(1, lambda: 0.0) == 0.5


def test_sleeps_between_retries(router: Router):
    slept = []
    c = SSLCommerz(
        config=Config(STORE_ID, STORE_PASSWD),
        transport=httpx.MockTransport(router.handler),
        retry=RetryPolicy(retries=2, base_delay=0.1, jitter=False),
        sleep=slept.append,
    )
    router.on(VALIDATION, httpx.ConnectError("x"), httpx.ConnectError("x"), validation_body())
    c.validate("v")
    assert slept == [0.1, 0.2]


def test_retries_503_but_not_400(client, router):
    router.on(VALIDATION, httpx.Response(503, text="busy"), validation_body())
    assert client.validate("v").is_paid
    router.routes.clear()
    router.requests.clear()
    router.on(VALIDATION, httpx.Response(400, json={"error": "bad"}))
    with pytest.raises(ResponseError) as info:
        client.validate("v")
    assert info.value.status_code == 400
    assert router.count(VALIDATION) == 1


def test_non_json_response(client, router):
    router.on(VALIDATION, httpx.Response(200, text="<html>maintenance</html>"))
    with pytest.raises(ResponseError, match="non-JSON"):
        client.validate("v")


def test_json_array_rejected(client, router):
    router.on(VALIDATION, httpx.Response(200, json=[1, 2]))
    with pytest.raises(ResponseError, match="unexpected JSON"):
        client.validate("v")


def test_timeout_maps_to_timeout_error(client, router):
    router.on(VALIDATION, httpx.ReadTimeout("slow"))
    with pytest.raises(TimeoutError) as info:
        client.validate("v")
    assert isinstance(info.value, NetworkError)
    assert info.value.retryable


def test_empty_body_is_missing_status(client, router):
    router.on(VALIDATION, httpx.Response(200, text=""))
    with pytest.raises(ResponseError, match="no status"):
        client.validate("v")


def test_external_http_client_not_closed(router):
    http = httpx.Client(transport=httpx.MockTransport(router.handler))
    c = SSLCommerz(config=Config(STORE_ID, STORE_PASSWD), http_client=http)
    c.close()
    assert not http.is_closed
    http.close()


def test_context_manager(router):
    with SSLCommerz(STORE_ID, STORE_PASSWD, transport=httpx.MockTransport(router.handler)) as c:
        assert c.base_url == "https://sandbox.sslcommerz.com"


def test_logs_are_redacted(client, router, caplog):
    caplog.set_level(logging.DEBUG, logger="sslcommerz_py")
    router.on(VALIDATION, httpx.ConnectError(f"failed {STORE_PASSWD}"), validation_body())
    client.validate("v")
    joined = " ".join(str(getattr(r, "sslcommerz", "")) + r.getMessage() for r in caplog.records)
    assert "retry" in joined
    assert STORE_PASSWD not in joined


def test_redact_helpers():
    out = redact({"store_passwd": "x", "nested": [{"note": "has secret-value"}]}, ["secret-value"])
    assert out == {"store_passwd": REDACTED, "nested": [{"note": f"has {REDACTED}"}]}
    assert mask_card("432149XXXXXX0667") == "************0667"
    assert mask_card("") == ""
