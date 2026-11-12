import httpx
import pytest

from sslcommerz_py import AuthenticationError, ResponseError, SessionInitError, TimeoutError

from .conftest import SESSION, STORE_ID, STORE_PASSWD, Router, session_success


def test_create_session_posts_form(client, router: Router, payment_request):
    router.on(SESSION, session_success())
    res = client.create_session(payment_request)
    assert res.ok
    assert res.sessionkey == "F298BC45B0688E02768900C4F6B28C8B"
    assert res.gateway_page_url.startswith("https://sandbox.sslcommerz.com/gwprocess/v4/gw.php")
    assert res.gateways["mobilebanking"] == "bkash,dbbl_mobile"
    req = router.last(SESSION)
    assert req.method == "POST"
    assert str(req.url).startswith("https://sandbox.sslcommerz.com/gwprocess/v4/api.php")
    assert req.headers["content-type"] == "application/x-www-form-urlencoded"
    form = Router.form(req)
    assert form["store_id"] == STORE_ID
    assert form["store_passwd"] == STORE_PASSWD
    assert form["total_amount"] == "103.00"
    assert req.headers["user-agent"].startswith("sslcommerz-py/")


def test_failed_status_raises(client, router, payment_request):
    router.on(SESSION, {"status": "FAILED", "failedreason": "Store Credential Error Or Store is De-active"})
    with pytest.raises(SessionInitError) as info:
        client.create_session(payment_request)
    assert "Store Credential" in info.value.reason


def test_success_without_url_raises(client, router, payment_request):
    router.on(SESSION, {"status": "SUCCESS"})
    with pytest.raises(ResponseError, match="GatewayPageURL"):
        client.create_session(payment_request)


def test_session_not_retried_by_default(client, router, payment_request):
    router.on(SESSION, httpx.ReadTimeout("slow"))
    with pytest.raises(TimeoutError):
        client.create_session(payment_request)
    assert router.count(SESSION) == 1


def test_session_retry_opt_in(client, router, payment_request):
    from sslcommerz_py import RetryPolicy

    router.on(SESSION, httpx.ConnectError("refused"), session_success())
    res = client.create_session(payment_request, retry=RetryPolicy(retries=1))
    assert res.ok
    assert router.count(SESSION) == 2


def test_live_host(router, payment_request):
    from sslcommerz_py import SSLCommerz

    c = SSLCommerz(STORE_ID, STORE_PASSWD, sandbox=False, transport=httpx.MockTransport(router.handler))
    router.on(SESSION, session_success())
    c.create_session(payment_request)
    assert router.last(SESSION).url.host == "securepay.sslcommerz.com"


def test_validation_error_sends_nothing(client, router, payment_request):
    payment_request.tran_id = ""
    with pytest.raises(Exception, match="tran_id"):
        client.create_session(payment_request)
    assert router.requests == []


def test_http_error_json_body(client, router, payment_request):
    router.on(SESSION, httpx.Response(500, json={"status": "FAILED"}))
    with pytest.raises(ResponseError) as info:
        client.create_session(payment_request)
    assert info.value.status_code == 500
    assert info.value.retryable


def test_password_never_in_error(client, router, payment_request):
    router.on(SESSION, httpx.ConnectError(f"boom {STORE_PASSWD}"))
    with pytest.raises(Exception) as info:
        client.create_session(payment_request)
    assert STORE_PASSWD not in str(info.value)


def test_api_connect_failure_maps(client, router):
    from .conftest import VALIDATION

    router.on(VALIDATION, {"APIConnect": "FAILED"})
    with pytest.raises(AuthenticationError):
        client.validate("abc")
