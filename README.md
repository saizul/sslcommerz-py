# sslcommerz-py

Typed Python SDK and CLI for the **SSLCommerz** payment gateway (Bangladesh).

[![CI](https://github.com/saizul/sslcommerz-py/actions/workflows/ci.yml/badge.svg)](https://github.com/saizul/sslcommerz-py/actions/workflows/ci.yml)
[![Docker image](https://github.com/saizul/sslcommerz-py/actions/workflows/publish-image.yml/badge.svg)](https://github.com/saizul/sslcommerz-py/actions/workflows/publish-image.yml)
![python](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)
![typed](https://img.shields.io/badge/typing-typed-informational)
![license](https://img.shields.io/badge/license-MIT-lightgrey)

SSLCommerz is the most widely used card, mobile banking and internet banking gateway in Bangladesh. Accepting a
payment safely takes more than redirecting to `GatewayPageURL`: the IPN must be checked against its `verify_sign`,
confirmed with the Validation API, and matched to your own order's `tran_id`, amount and currency. This package does
all of that in one call, with a sync client, an async client and a command line tool.

> Read [Limitations](#limitations) before going live. The package is tested against mocked responses built from the
> public documentation, not against the live gateway.

## Contents

- [Features](#features)
- [Install](#install)
- [Quick start](#quick-start)
- [Payment flow](#payment-flow)
- [API reference](#api-reference)
- [Errors](#errors)
- [Configuration](#configuration)
- [Command line](#command-line)
- [Docker image](#docker-image)
- [Examples](#examples)
- [Testing](#testing)
- [Security notes](#security-notes)
- [Limitations](#limitations)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Session init** - typed `PaymentRequest` with `Customer`, `Product`, `Shipping` and `CartItem`, validated before
  sending (amount format and the documented 10.00 - 500000.00 BDT range, field lengths, absolute URLs, shipping and
  logistic rules, product profiles).
- **IPN validation** - `verify_ipn()` runs the full check: `verify_sign`, IPN `status`, the Validation API by
  `val_id`, then `tran_id`, amount and currency against your order. Foreign-currency orders are compared on
  `currency_type`/`currency_amount`.
- **Hash verification** - `verify_signature()` / `compute_signature()` implement the `verify_key` / `verify_sign`
  md5 scheme used by the official SSLCommerz libraries, with constant-time comparison.
- **Transaction query** by `tran_id` (all attempts) and by `sessionkey`.
- **Batch reconciliation** - `reconcile()` / `sslcommerz reconcile orders.csv` checks a list of your orders against
  the read-only Transaction Query API and flags amount or currency mismatches, double payments, pending and unpaid
  orders, with JSON or CSV output for cron jobs.
- **Refunds** - initiate (with the required `refund_trans_id`) and refund status by `refund_ref_id`.
- **Sandbox and live** hosts, or any custom base URL.
- **Typed errors** - `APIConnect` values map to `InvalidRequestError`, `AuthenticationError` and
  `InactiveStoreError`; plus `SessionInitError`, `RefundError`, `HashVerificationError`, `PaymentNotValidError`,
  `AmountMismatchError`, `NetworkError`, `TimeoutError`, `ResponseError`.
- **Retry with backoff** on network errors and 502/503/504 for read-only calls. Session init and refund initiate are
  not retried blindly.
- **Injectable transport** - pass `httpx.MockTransport` in tests or your own `httpx.Client` for proxies and TLS.
- **Sync and async** clients with the same API (`SSLCommerz`, `AsyncSSLCommerz`).
- **Dataclass models** that keep the full response in `raw`, amounts as `Decimal`.
- **CLI** - `sslcommerz init | validate | query | reconcile | refund | refund-status | verify-hash`.
- **Flask and FastAPI** IPN examples, tested in CI.
- Redacted logging: the store password never appears in logs or error messages.

## Install

From GitHub:

```bash
pip install "git+https://github.com/saizul/sslcommerz-py.git"
```

From PyPI, once a release is published there:

```bash
pip install sslcommerz-py
```

Extras: `sslcommerz-py[flask]`, `sslcommerz-py[fastapi]`. Python 3.9 or newer. The only runtime dependency is
`httpx`.

## Quick start

```python
from sslcommerz_py import Customer, PaymentRequest, Product, SSLCommerz

sslc = SSLCommerz("your_store_id", "your_store_password", sandbox=True)
# or: sslc = SSLCommerz.from_env()

session = sslc.create_session(
    PaymentRequest(
        total_amount="1250.00",
        tran_id="INV-1001",
        success_url="https://shop.example.com/sslc/success",
        fail_url="https://shop.example.com/sslc/fail",
        cancel_url="https://shop.example.com/sslc/cancel",
        ipn_url="https://shop.example.com/sslc/ipn",
        customer=Customer(
            name="Test Customer",
            email="customer@example.com",
            phone="01700000000",
            add1="House 1, Road 2",
            city="Dhaka",
            postcode="1207",
        ),
        product=Product(name="T-shirt", category="clothing", profile="physical-goods"),
    )
)
redirect(session.gateway_page_url)
```

In the IPN listener:

```python
from sslcommerz_py import SSLCommerzError

try:
    paid = sslc.verify_ipn(
        request.form,
        expected_tran_id=order.tran_id,
        expected_amount=order.amount,      # from your database
        expected_currency=order.currency,
    )
except SSLCommerzError as exc:
    log.warning("IPN rejected: %s", exc)
else:
    order.mark_paid(bank_tran_id=paid.validation.bank_tran_id, review=paid.is_high_risk)
return "", 200
```

Async:

```python
from sslcommerz_py import AsyncSSLCommerz

async with AsyncSSLCommerz.from_env() as sslc:
    paid = await sslc.verify_ipn(form, expected_amount="1250.00", expected_currency="BDT")
```

## Payment flow

```
Your server                          SSLCommerz                        Customer
-----------                          ----------                        --------
create_session()  ---- POST ---->    /gwprocess/v4/api.php
                  <--------------    sessionkey, GatewayPageURL
redirect(GatewayPageURL) ------------------------------------------>   pays
POST ipn_url      <--------------    status, tran_id, val_id, verify_sign ...
verify_ipn():
  verify_sign check (local)
  validate(val_id) ---- GET ---->    /validator/api/validationserverAPI.php
  compare tran_id / amount / currency
POST success_url  <---------------------------------------------------  redirect
```

The IPN is server to server and is the reliable signal. The success redirect carries the same signed fields, so you
can verify it the same way if the customer arrives before the IPN. If neither arrives, reconcile with
`query_by_tran_id()`.

## API reference

### `SSLCommerz(store_id=None, store_passwd=None, *, sandbox=None, config=None, retry=None, transport=None, http_client=None)`

| Method | SSLCommerz API | Returns |
| --- | --- | --- |
| `create_session(request, *, retry=None)` | `POST /gwprocess/v4/api.php` | `SessionResponse` |
| `validate(val_id)` | `GET /validator/api/validationserverAPI.php` | `ValidationResult` |
| `verify_ipn(form, *, expected_tran_id, expected_amount, expected_currency)` | hash + Validation API | `VerifiedPayment` |
| `query_by_tran_id(tran_id)` | `GET /validator/api/merchantTransIDvalidationAPI.php?tran_id=` | `TransactionQueryResult` |
| `query_by_session(sessionkey)` | `GET /validator/api/merchantTransIDvalidationAPI.php?sessionkey=` | `TransactionQueryResult` |
| `refund(*, bank_tran_id, refund_amount, refund_remarks, refund_trans_id, refe_id=None)` | `GET .../merchantTransIDvalidationAPI.php` | `RefundResult` |
| `refund_status(refund_ref_id)` | `GET .../merchantTransIDvalidationAPI.php?refund_ref_id=` | `RefundStatusResult` |
| `from_env(env=None, **kwargs)` | | `SSLCommerz` |
| `close()` / context manager | | |

`AsyncSSLCommerz` has the same methods as coroutines, plus `aclose()` and `async with`.

### `verify_ipn()` checks, in order

1. `verify_sign` matches the fields named in `verify_key` (skip with `Config(verify_hash=False)`).
2. The IPN `status` is `VALID` (otherwise `PaymentNotValidError` with `.status` = `FAILED`, `CANCELLED`,
   `UNATTEMPTED` or `EXPIRED`), and `val_id` is present.
3. The Validation API returns `VALID` or `VALIDATED`.
4. The validated `tran_id` equals the IPN `tran_id` and `expected_tran_id`.
5. `expected_currency` and `expected_amount` match (`amount_tolerance` allowed, default exact).

The returned `VerifiedPayment` has `payload`, `validation`, `tran_id`, `amount`, `already_validated` (`VALIDATED`:
a duplicate IPN or redirect, so make fulfilment idempotent) and `is_high_risk` (`risk_level == 1`: hold delivery).

### `IPNVerifier(client, lookup)`

Binds `verify_ipn()` to your order store. `lookup(tran_id)` returns `(amount, currency)` or `None`. `verify(form)`
raises; `handle(form)` returns an `IPNOutcome(ok, tran_id, payment, error, status)`.

### Reconciliation

`reconcile(client, orders)` calls `query_by_tran_id()` for each `ExpectedOrder(tran_id, amount, currency)` and
returns a `ReconcileReport`. Nothing is changed at the gateway, so it is safe to run on a schedule.

```python
from sslcommerz_py import ExpectedOrder, SSLCommerz, load_orders, reconcile

orders = load_orders("orders.csv")  # or [ExpectedOrder.create("INV-1001", "1250.00", "BDT"), ...]
with SSLCommerz.from_env() as sslc:
    report = reconcile(sslc, orders, delay=0.2)

for r in report.problems:          # mismatches, double payments, failed queries
    alert(r.tran_id, r.status.value, r.detail)
for r in report.results:
    if r.ok:
        mark_paid(r.tran_id, bank_tran_id=r.bank_tran_id, review=r.high_risk)
```

| `ReconcileStatus` | Meaning | Problem? |
| --- | --- | --- |
| `paid` | One paid attempt (`VALID`/`VALIDATED`), currency and amount match | no |
| `currency_mismatch` | Paid in another currency than the order | yes |
| `amount_mismatch` | Paid amount differs by more than the tolerance | yes |
| `multiple_payments` | Two or more distinct paid attempts for one `tran_id`: refund the extra | yes |
| `pending` | Nothing paid yet, an attempt is `PENDING` | no |
| `not_paid` | Attempts exist, none paid (failed, cancelled...) | no |
| `not_found` | The gateway has no transaction for this `tran_id` | no |
| `error` | The query failed (network, HTTP or response error); `.error` holds the exception | yes |

Non-BDT orders are compared on `currency_type`/`currency_amount`, like `verify_ipn()`. The tolerance defaults to
`Config.amount_tolerance`; pass `tolerance=` to override. Orders without an amount only check that a payment exists
in the right currency. A failed query does not stop the run, but `AuthenticationError` and `InactiveStoreError` do,
because every other query would fail the same way. Duplicate `tran_id`s in the input raise `ValidationError`.

`areconcile(async_client, orders, concurrency=4)` is the async version; results keep the input order.
`report.to_dict()` and `report.to_csv()` give the same data the CLI prints. CSV values that would start a spreadsheet
formula are prefixed with `'`.

`load_orders(path_or_stream)` reads a CSV with a `tran_id` column (also `transaction_id` or `order_id`) and optional
`amount` (or `total_amount`) and `currency` (default `BDT`) columns. Comma, semicolon and tab delimiters and a UTF-8
BOM are accepted; a bad value raises `ValidationError` with the line number.

### Hashing

```python
from sslcommerz_py import compute_signature, verify_signature

verify_signature(form, store_passwd)   # True / False
compute_signature(form, store_passwd)  # md5 hex, for fixtures
```

### Models

| Model | Notes |
| --- | --- |
| `PaymentRequest` | `total_amount`, `tran_id`, `success_url`, `fail_url`, `cancel_url`, `customer`, `product`, optional `ipn_url`, `currency` (`BDT`), `shipping`, `emi_*`, `multi_card_name`, `allowed_bin`, `cart`, `product_amount`, `vat`, `discount_amount`, `convenience_fee`, `value_a`..`value_d`, `extra`. `to_params()` returns the form fields. |
| `Customer` | `cus_*` fields; `country` defaults to `Bangladesh`. |
| `Shipping` | `method` defaults to `NO`; `YES` and `SSLCOMMERZ_LOGISTIC` require the address (and logistic) fields. |
| `Product` | `name`, `category`, `profile` (one of the six documented profiles), vertical fields in `extra`. |
| `SessionResponse` | `status`, `sessionkey`, `gateway_page_url`, `gateways`, `desc`, `failed_reason`, `ok`, `raw`. |
| `ValidationResult` / `Transaction` | `status`, `tran_id`, `val_id`, `amount`, `store_amount`, `currency`, `bank_tran_id`, card fields, `currency_type`, `currency_amount`, `risk_level`, `risk_title`, `value_a`..`d`, `is_paid`, `is_high_risk`, `raw`. |
| `TransactionQueryResult` | `api_connect`, `no_of_trans_found`, `transactions`, `paid`, `is_paid`. |
| `RefundResult` | `status` (`success`, `processing`, `failed`), `refund_ref_id`, `trans_id`, `accepted`. |
| `RefundStatusResult` | `status` (`refunded`, `processing`, `cancelled`), `initiated_on`, `refunded_on`, `is_refunded`. |
| `IPNPayload` | Parsed IPN form; `from_form()` accepts dicts, Flask/Starlette forms and `parse_qs` output. |

Status enums: `IPNStatus`, `ValidationStatus`, `TransactionStatus`, `APIConnect`, `RefundInitStatus`,
`RefundStatusValue`.

## Errors

All exceptions derive from `SSLCommerzError` and carry `raw` (the response, when any).

| Exception | When |
| --- | --- |
| `ConfigurationError` | Missing store id/password, bad environment or timeout. |
| `ValidationError` | Input rejected locally; `.field` names it. Also a `ValueError`. |
| `SessionInitError` | Session init `status=FAILED`; `.reason` is `failedreason`. |
| `InvalidRequestError` | `APIConnect=INVALID_REQUEST`. |
| `AuthenticationError` | `APIConnect=FAILED` (wrong credentials; for refunds also an unregistered IP). |
| `InactiveStoreError` | `APIConnect=INACTIVE`. |
| `HashVerificationError` | `verify_sign` missing or wrong. |
| `PaymentNotValidError` | IPN or validation status is not a paid state; `.status`. |
| `AmountMismatchError` | `tran_id`, amount or currency differs; `.field`, `.expected`, `.actual`. |
| `RefundError` | Refund `status=failed`; `.reason` is `errorReason`. |
| `NetworkError` / `TimeoutError` | No response. Outcome unknown for session init and refunds. |
| `ResponseError` | Non-JSON body or HTTP 4xx/5xx; `.status_code`. |

## Configuration

```python
from decimal import Decimal
from sslcommerz_py import Config, Environment, RetryPolicy, SSLCommerz

config = Config(
    store_id="your_store_id",
    store_passwd="your_store_password",
    environment=Environment.LIVE,       # or "sandbox" / "live"
    base_url=None,                      # override the host
    timeout=30.0,                       # seconds
    verify_hash=True,                   # check verify_sign in verify_ipn()
    amount_tolerance=Decimal("0"),      # allowed amount difference
    enforce_amount_range=True,          # 10.00 - 500000.00 BDT on session init
)
sslc = SSLCommerz(config=config, retry=RetryPolicy(retries=3, base_delay=0.5, max_delay=8))
```

| Variable | Meaning |
| --- | --- |
| `SSLCOMMERZ_STORE_ID` | Store id |
| `SSLCOMMERZ_STORE_PASSWD` | Store API password |
| `SSLCOMMERZ_ENV` | `sandbox` (default) or `live` |
| `SSLCOMMERZ_SANDBOX` | Alternative: `true` / `false` |
| `SSLCOMMERZ_BASE_URL` | Host override |
| `SSLCOMMERZ_TIMEOUT` | Timeout in seconds |

| Environment | Host |
| --- | --- |
| sandbox | `https://sandbox.sslcommerz.com` |
| live | `https://securepay.sslcommerz.com` |

Retries: validation, both queries and refund status are retried on network errors and 502/503/504 with exponential
backoff and jitter. `create_session()` is not retried unless you pass `retry=`. `refund()` is never retried; reuse the
same `refund_trans_id` if you try again after a timeout.

Custom HTTP: `SSLCommerz(config=config, http_client=httpx.Client(proxy="http://proxy:3128"))`. A client you pass in is
not closed by `close()`.

## Command line

```bash
export SSLCOMMERZ_STORE_ID=your_sandbox_store_id
export SSLCOMMERZ_STORE_PASSWD=your_sandbox_store_password

sslcommerz init --amount 150 --tran-id INV-1 \
  --success-url https://shop.example.com/s --fail-url https://shop.example.com/f \
  --cancel-url https://shop.example.com/c --cus-name "Test Customer" \
  --cus-email customer@example.com --cus-phone 01700000000 --cus-add1 Dhaka \
  --product-name Book
sslcommerz --pretty validate 1709162025351ElIuHtUtFReBwE
sslcommerz query --tran-id INV-1
sslcommerz query --session-key F298BC45B0688E02768900C4F6B28C8B
sslcommerz --pretty reconcile orders.csv                 # tran_id,amount,currency per line
sslcommerz reconcile orders.csv --format csv -o report.csv --delay 0.2
sslcommerz reconcile --tran-id INV-1 --tran-id INV-2 --fail-on unpaid
sslcommerz refund --bank-tran-id 1709162345070ANJdZV8LyI4cMw --amount 50 \
  --remarks "Out of stock" --refund-trans-id RF-1001
sslcommerz refund-status 59bd63fea5455
sslcommerz verify-hash saved-ipn.json      # offline, JSON or form-encoded, "-" for stdin
```

Global flags: `--store-id`, `--store-passwd` (prefer the environment), `--env sandbox|live`, `--base-url`,
`--timeout`, `--pretty`, `--raw` (include the raw gateway response). Output is JSON.

Exit codes: `0` ok, `1` gateway/API error, `2` usage or configuration error, `3` network error, `4` not valid (bad
hash, `validate` returned a non-paid status, or `reconcile` found problems).

`reconcile` options: `--format json|csv`, `-o/--output FILE`, `--tolerance AMOUNT`, `--delay SECONDS` between
queries, `--currency` for `--tran-id` orders, and `--fail-on problems|unpaid|never`. The default `problems` exits `4`
on mismatches, double payments and failed queries; `unpaid` also on pending, unpaid and unknown orders. The JSON
report has a `summary` with a count per status and one entry per order in `results`.

## Docker image

Each push to `main` and each release publishes a multi-arch image (`linux/amd64`, `linux/arm64`) to the GitHub
Container Registry with the CLI as entrypoint.

```bash
docker pull ghcr.io/saizul/sslcommerz-py:latest

docker run --rm \
  -e SSLCOMMERZ_STORE_ID -e SSLCOMMERZ_STORE_PASSWD -e SSLCOMMERZ_ENV=sandbox \
  ghcr.io/saizul/sslcommerz-py:latest query --tran-id INV-1001

# Offline hash check of a saved payload in the current directory
docker run --rm -v "$PWD:/work" -e SSLCOMMERZ_STORE_ID -e SSLCOMMERZ_STORE_PASSWD \
  ghcr.io/saizul/sslcommerz-py:latest verify-hash saved-ipn.json
```

Tags: `latest` (default branch), the short commit SHA, and `X.Y.Z` for releases. The container runs as a non-root
user with `/work` as the working directory. Build locally with `docker build -t sslcommerz-py .`.

The refund APIs only accept requests from IP addresses registered with SSLCommerz, so run refund commands from a
host whose outbound IP is whitelisted.

## Examples

| File | What it shows |
| --- | --- |
| [examples/flask_app.py](examples/flask_app.py) | Flask checkout, IPN listener and success/fail/cancel routes |
| [examples/fastapi_app.py](examples/fastapi_app.py) | FastAPI IPN listener with the async client |
| [examples/create_session.py](examples/create_session.py) | Create a sandbox session from the command line |
| [examples/refund.py](examples/refund.py) | Initiate a refund and poll its status |
| [examples/reconcile.py](examples/reconcile.py) | Resolve orders whose IPN never arrived with `reconcile()` |
| [examples/orders.csv](examples/orders.csv) | Sample order list for `sslcommerz reconcile` |
| [examples/sample-ipn.json](examples/sample-ipn.json) | Signed sample IPN (store password `your_store_password`) for `verify-hash` |

The Flask and FastAPI examples are exercised by `tests/test_examples.py`.

## Testing

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,flask,fastapi]"
ruff check . && ruff format --check .
pytest
```

The tests use `httpx.MockTransport`, so no network or credentials are needed. The same approach works for your own
tests:

```python
import httpx
from sslcommerz_py import SSLCommerz

def handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"status": "VALID", "tran_id": "INV-1", "amount": "100.00", "currency": "BDT"})

sslc = SSLCommerz("store", "pass", transport=httpx.MockTransport(handler))
```

## Security notes

- Keep `store_passwd` on the server, in an environment variable or secret manager. It is redacted from logs, error
  messages and `repr(Config)`.
- Never mark an order paid from the success redirect or the IPN `status` alone. Use `verify_ipn()` with the expected
  amount and currency **from your database**.
- `verify_sign` uses md5 because the gateway mandates it. It only proves the listed fields were not changed; the
  Validation API call is what proves the payment, which is why `verify_ipn()` does both.
- Treat `VALIDATED` as a duplicate: make fulfilment idempotent per `tran_id`.
- Hold delivery when `is_high_risk` is true (`risk_level == 1`), as SSLCommerz recommends.
- Use a unique `tran_id` per attempt and a unique `refund_trans_id` per refund, and store them before calling.
- Serve `ipn_url` over https and answer it quickly with a 2xx.
- Report vulnerabilities as described in [SECURITY.md](SECURITY.md).

## Limitations

- **Not tested against the live gateway.** Endpoints, parameters and response fields follow the
  [SSLCommerz v4 documentation](https://developer.sslcommerz.com/doc/v4/). Test in the sandbox first.
- **Hash algorithm.** The v4 documentation names `verify_sign` and `verify_key` but does not describe the algorithm.
  The implementation follows the hash check in the official SSLCommerz PHP library. It is used only as a first check;
  `verify_ipn()` always confirms with the Validation API too.
- **Missing signed fields** are hashed as empty strings, matching how the reference library behaves for unset values;
  this case is not covered by the documentation.
- **Field lengths.** Lengths that the documentation states (for example `tran_id` 30, URLs 255, `refund_trans_id` 30,
  `bank_tran_id` 80) are enforced. Customer field limits (50/20 characters) are conservative values, not documented
  ones; send longer values via `extra` if the gateway accepts them.
- **Refund status `cancelled`.** The documentation describes it in a way that looks like a typo; it is returned as-is
  and `is_refunded` is only true for `refunded`.
- **Not covered:** EMI-specific responses beyond the raw fields, the hosted checkout JS / easy checkout popup, invoice
  and subscription APIs, and XML output (`format=json` is always sent).
- **Timeouts on session init or refund** leave the outcome unknown; query by `tran_id` or call `refund_status()`
  before trying again.
- Times such as `tran_date` are returned as strings, unparsed.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE) - Copyright (c) 2026 Saizul Amin.

This project is not affiliated with or endorsed by SSLCommerz or SSL Wireless. "SSLCommerz" is a trademark of its
owner.
