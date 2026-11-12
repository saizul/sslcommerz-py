from decimal import Decimal

import pytest

from sslcommerz_py import LIVE_BASE_URL, SANDBOX_BASE_URL, Config, ConfigurationError, Environment, SSLCommerz


def test_defaults():
    c = Config("store", "pass")
    assert c.sandbox
    assert c.resolved_base_url == SANDBOX_BASE_URL
    assert "pass" not in repr(c)


def test_live_and_override():
    assert Config("s", "p", environment=Environment.LIVE).resolved_base_url == LIVE_BASE_URL
    assert Config("s", "p", environment="production").environment is Environment.LIVE
    assert Config("s", "p", base_url="https://proxy.example.com/").resolved_base_url == "https://proxy.example.com"


@pytest.mark.parametrize("kwargs", [{"store_id": ""}, {"store_passwd": " "}, {"timeout": 0}, {"environment": "moon"}])
def test_invalid(kwargs):
    base = {"store_id": "s", "store_passwd": "p"}
    base.update(kwargs)
    with pytest.raises(ConfigurationError):
        Config(**base)


def test_from_env():
    c = Config.from_env(
        {
            "SSLCOMMERZ_STORE_ID": "s",
            "SSLCOMMERZ_STORE_PASSWD": "p",
            "SSLCOMMERZ_ENV": "live",
            "SSLCOMMERZ_TIMEOUT": "12",
        }
    )
    assert c.environment is Environment.LIVE
    assert c.timeout == 12.0
    c2 = Config.from_env({"SSLCOMMERZ_STORE_ID": "s", "SSLCOMMERZ_STORE_PASSWD": "p", "SSLCOMMERZ_SANDBOX": "false"})
    assert not c2.sandbox
    c3 = Config.from_env(
        {"SSLCOMMERZ_STORE_ID": "s", "SSLCOMMERZ_STORE_PASSWD": "p", "SSLCOMMERZ_BASE_URL": "https://x.example"}
    )
    assert c3.resolved_base_url == "https://x.example"
    with pytest.raises(ConfigurationError):
        Config.from_env({"SSLCOMMERZ_STORE_ID": "s", "SSLCOMMERZ_STORE_PASSWD": "p", "SSLCOMMERZ_TIMEOUT": "x"})


def test_tolerance_coerced():
    assert Config("s", "p", amount_tolerance=1).amount_tolerance == Decimal("1")


def test_client_from_env_and_positional():
    c = SSLCommerz.from_env({"SSLCOMMERZ_STORE_ID": "s", "SSLCOMMERZ_STORE_PASSWD": "p"})
    assert c.config.store_id == "s"
    c.close()
    with pytest.raises(ConfigurationError):
        SSLCommerz()
    live = SSLCommerz("s", "p", sandbox=False)
    assert live.base_url == LIVE_BASE_URL
    live.close()
