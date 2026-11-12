# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-12

### Added

- `SSLCommerz` (sync) and `AsyncSSLCommerz` (async) clients for the SSLCommerz v4 APIs: session init, Validation API,
  transaction query by `tran_id` and by `sessionkey`, refund initiate and refund status.
- Sandbox and live hosts, custom base URL, `Config.from_env()` and `SSLCommerz.from_env()`.
- `verify_ipn()`: hash check, IPN status check, Validation API call, and `tran_id` / amount / currency comparison,
  including foreign-currency orders.
- `verify_signature()` and `compute_signature()` for `verify_sign` / `verify_key`.
- `IPNVerifier` that binds IPN checks to an order lookup.
- Dataclass request models (`PaymentRequest`, `Customer`, `Shipping`, `Product`, `CartItem`) with local validation,
  and response models with `Decimal` amounts and the full `raw` body.
- Typed exception hierarchy, including `APIConnect` mapping.
- `httpx` transport layer with injectable transport/client, timeouts, exponential backoff with jitter for read-only
  calls, and redacted logging.
- `sslcommerz` CLI: `init`, `validate`, `query`, `refund`, `refund-status`, `verify-hash`.
- Flask and FastAPI examples (tested), plus session, refund and reconciliation scripts.
- Dockerfile and a workflow publishing `ghcr.io/saizul/sslcommerz-py`.
- CI on Python 3.9 - 3.13 with ruff lint and format checks.

[Unreleased]: https://github.com/saizul/sslcommerz-py/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/saizul/sslcommerz-py/releases/tag/v0.1.0
