"""Reconcile orders whose IPN never arrived.

python examples/reconcile.py TRAN_ID [TRAN_ID ...]
"""

from __future__ import annotations

import sys

from sslcommerz_py import SSLCommerz, SSLCommerzError

with SSLCommerz.from_env() as sslc:
    for tran_id in sys.argv[1:]:
        try:
            result = sslc.query_by_tran_id(tran_id)
        except SSLCommerzError as exc:
            print(tran_id, "error", exc)
            continue
        paid = result.paid
        if paid:
            print(tran_id, "PAID", paid.amount, paid.currency, paid.bank_tran_id)
        elif result.transactions:
            print(tran_id, "NOT PAID", ", ".join(t.status for t in result.transactions))
        else:
            print(tran_id, "NO TRANSACTION")
