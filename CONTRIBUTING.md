# Contributing

Thanks for helping improve sslcommerz-py. Bug reports, documentation fixes and pull requests are welcome.

## Getting started

```bash
git clone https://github.com/saizul/sslcommerz-py.git
cd sslcommerz-py
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,flask,fastapi]"
ruff check . && ruff format --check .
pytest
```

The code must keep working on Python 3.9 (use `typing.Optional`, `List` and so on, with
`from __future__ import annotations`).

## Project layout

| Path | Purpose |
| --- | --- |
| `src/sslcommerz_py/client.py`, `async_client.py` | Public clients (keep them in sync) |
| `src/sslcommerz_py/core.py` | Request builders and response checks shared by both clients (no I/O) |
| `src/sslcommerz_py/transport.py` | httpx wrapper: timeouts, retries, error mapping |
| `src/sslcommerz_py/models.py` | Request and response dataclasses |
| `src/sslcommerz_py/hashing.py` | `verify_sign` / `verify_key` |
| `src/sslcommerz_py/ipn.py` | `IPNVerifier` |
| `src/sslcommerz_py/reconcile.py` | Batch reconciliation over the Transaction Query API (no I/O of its own) |
| `src/sslcommerz_py/cli.py` | `sslcommerz` command |
| `tests/` | pytest suites; `tests/conftest.py` holds the scripted transport and gateway samples |
| `examples/` | Runnable examples (Flask/FastAPI ones are tested) |

## Guidelines

- **Follow the official docs.** Every endpoint and parameter must be traceable to
  [developer.sslcommerz.com](https://developer.sslcommerz.com/doc/v4/). If something cannot be confirmed, make it
  configurable and add it to the README "Limitations" section. Link the doc page in your pull request.
- **No real credentials.** Use the placeholders in `tests/conftest.py` and `.env.example`. Never paste real store
  passwords, card data or customer details.
- **Money-moving calls are not retried blindly.** Changes to retry behaviour for session init or refunds need a test
  showing no duplicate request is sent.
- **Tests for every change**, using `httpx.MockTransport`. `pytest` must pass.
- **Style.** `ruff check .` and `ruff format --check .` must pass. Public functions need docstrings and type hints.
- **Changelog.** Add a line under `[Unreleased]` in `CHANGELOG.md`.

## Releasing

1. Update `version` in `pyproject.toml` and `src/sslcommerz_py/_version.py`; move `[Unreleased]` entries in
   `CHANGELOG.md`.
2. Tag `vX.Y.Z` and publish a GitHub release. The `Publish container image` workflow pushes
   `ghcr.io/saizul/sslcommerz-py:X.Y.Z`.

## Code of conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md). Be respectful and constructive; harassment of any
kind is not tolerated.
