"""Command line interface: ``sslcommerz <command>``.

Credentials come from ``SSLCOMMERZ_STORE_ID`` / ``SSLCOMMERZ_STORE_PASSWD``
(preferred, keeps them out of shell history) or ``--store-id`` /
``--store-passwd``.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from decimal import Decimal
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence
from urllib.parse import parse_qsl

from ._version import __version__
from .client import SSLCommerz
from .config import Config, Environment
from .errors import (
    ConfigurationError,
    HashVerificationError,
    NetworkError,
    SSLCommerzError,
    ValidationError,
)
from .hashing import verify_signature
from .models import Customer, PaymentRequest, Product

EXIT_OK = 0
EXIT_API = 1
EXIT_USAGE = 2
EXIT_NETWORK = 3
EXIT_INVALID = 4


def _jsonable(obj: Any, include_raw: bool) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out = {}
        for f in dataclasses.fields(obj):
            if f.name == "raw" and not include_raw:
                continue
            out[f.name] = _jsonable(getattr(obj, f.name), include_raw)
        return out
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, Mapping):
        return {str(k): _jsonable(v, include_raw) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v, include_raw) for v in obj]
    return obj


def _print(obj: Any, args: argparse.Namespace, out: Any) -> None:
    data = _jsonable(obj, getattr(args, "raw", False))
    out.write(json.dumps(data, indent=2 if args.pretty else None, ensure_ascii=False) + "\n")


def _config(args: argparse.Namespace, env: Mapping[str, str]) -> Config:
    overrides: Dict[str, Any] = {}
    if args.store_id:
        overrides["store_id"] = args.store_id
    if args.store_passwd:
        overrides["store_passwd"] = args.store_passwd
    if args.env:
        overrides["environment"] = Environment.parse(args.env)
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.timeout:
        overrides["timeout"] = args.timeout
    return Config.from_env(env, **overrides)


def _read_payload(source: str, stdin: Any) -> Dict[str, Any]:
    text = stdin.read() if source == "-" else open(source, encoding="utf-8").read()  # noqa: SIM115
    text = text.strip()
    if text.startswith("{"):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValidationError("payload", "must be a JSON object")
        return data
    return dict(parse_qsl(text, keep_blank_values=True))


# ----------------------------------------------------------------- commands


def cmd_init(client: SSLCommerz, args: argparse.Namespace) -> Any:
    request = PaymentRequest(
        total_amount=args.amount,
        currency=args.currency,
        tran_id=args.tran_id,
        success_url=args.success_url,
        fail_url=args.fail_url,
        cancel_url=args.cancel_url,
        ipn_url=args.ipn_url,
        customer=Customer(
            name=args.cus_name,
            email=args.cus_email,
            phone=args.cus_phone,
            add1=args.cus_add1,
            city=args.cus_city,
            postcode=args.cus_postcode,
            country=args.cus_country,
        ),
        product=Product(name=args.product_name, category=args.product_category, profile=args.product_profile),
        value_a=args.value_a,
    )
    return client.create_session(request)


def cmd_validate(client: SSLCommerz, args: argparse.Namespace) -> Any:
    return client.validate(args.val_id)


def cmd_query(client: SSLCommerz, args: argparse.Namespace) -> Any:
    if args.session_key:
        return client.query_by_session(args.session_key)
    return client.query_by_tran_id(args.tran_id)


def cmd_refund(client: SSLCommerz, args: argparse.Namespace) -> Any:
    return client.refund(
        bank_tran_id=args.bank_tran_id,
        refund_amount=args.amount,
        refund_remarks=args.remarks,
        refund_trans_id=args.refund_trans_id,
        refe_id=args.refe_id,
    )


def cmd_refund_status(client: SSLCommerz, args: argparse.Namespace) -> Any:
    return client.refund_status(args.refund_ref_id)


# ------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sslcommerz", description="SSLCommerz payment gateway command line tool.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--store-id", help="store id (default: $SSLCOMMERZ_STORE_ID)")
    p.add_argument("--store-passwd", help="store API password (default: $SSLCOMMERZ_STORE_PASSWD)")
    p.add_argument("--env", choices=["sandbox", "live"], help="environment (default: $SSLCOMMERZ_ENV or sandbox)")
    p.add_argument("--base-url", help="override the API host")
    p.add_argument("--timeout", type=float, help="request timeout in seconds")
    p.add_argument("--pretty", action="store_true", help="indent JSON output")
    p.add_argument("--raw", action="store_true", help="include the raw gateway response")
    sub = p.add_subparsers(dest="command", metavar="command")
    sub.required = True

    s = sub.add_parser("init", help="create a payment session and print GatewayPageURL")
    s.add_argument("--amount", required=True)
    s.add_argument("--currency", default="BDT")
    s.add_argument("--tran-id", required=True)
    s.add_argument("--success-url", required=True)
    s.add_argument("--fail-url", required=True)
    s.add_argument("--cancel-url", required=True)
    s.add_argument("--ipn-url")
    s.add_argument("--cus-name", required=True)
    s.add_argument("--cus-email", required=True)
    s.add_argument("--cus-phone", required=True)
    s.add_argument("--cus-add1", required=True)
    s.add_argument("--cus-city", default="Dhaka")
    s.add_argument("--cus-postcode", default="1000")
    s.add_argument("--cus-country", default="Bangladesh")
    s.add_argument("--product-name", required=True)
    s.add_argument("--product-category", default="general")
    s.add_argument("--product-profile", default="general")
    s.add_argument("--value-a")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("validate", help="validate a payment by val_id")
    s.add_argument("val_id")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("query", help="query transactions by tran_id or session key")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--tran-id")
    g.add_argument("--session-key")
    s.set_defaults(func=cmd_query)

    s = sub.add_parser("refund", help="initiate a refund")
    s.add_argument("--bank-tran-id", required=True)
    s.add_argument("--amount", required=True)
    s.add_argument("--remarks", required=True)
    s.add_argument("--refund-trans-id", required=True, help="your unique id for this refund")
    s.add_argument("--refe-id")
    s.set_defaults(func=cmd_refund)

    s = sub.add_parser("refund-status", help="check a refund by refund_ref_id")
    s.add_argument("refund_ref_id")
    s.set_defaults(func=cmd_refund_status)

    s = sub.add_parser("verify-hash", help="check verify_sign of a saved IPN payload (offline)")
    s.add_argument("payload", help="JSON or form-encoded file, or - for stdin")
    s.set_defaults(func=None)
    return p


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
    client_factory: Optional[Callable[[Config], SSLCommerz]] = None,
    stdout: Any = None,
    stderr: Any = None,
    stdin: Any = None,
) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code or 0)
    environ = os.environ if env is None else env

    try:
        config = _config(args, environ)
        if args.command == "verify-hash":
            payload = _read_payload(args.payload, stdin or sys.stdin)
            ok = verify_signature(payload, config.store_passwd)
            _print({"valid": ok, "verify_key": payload.get("verify_key")}, args, out)
            return EXIT_OK if ok else EXIT_INVALID
        factory = client_factory or (lambda c: SSLCommerz(config=c))
        client = factory(config)
        try:
            result = args.func(client, args)
        finally:
            client.close()
        _print(result, args, out)
        paid = getattr(result, "is_paid", None)
        if args.command == "validate" and paid is False:
            return EXIT_INVALID
        return EXIT_OK
    except (ConfigurationError, ValidationError) as exc:
        err.write(f"error: {exc}\n")
        return EXIT_USAGE
    except HashVerificationError as exc:
        err.write(f"error: {exc}\n")
        return EXIT_INVALID
    except NetworkError as exc:
        err.write(f"error: {exc}\n")
        return EXIT_NETWORK
    except SSLCommerzError as exc:
        err.write(f"error: {exc}\n")
        return EXIT_API
    except (OSError, json.JSONDecodeError) as exc:
        err.write(f"error: {exc}\n")
        return EXIT_USAGE


def _entry() -> None:  # pragma: no cover
    sys.exit(main())


__all__: List[str] = ["build_parser", "main"]
