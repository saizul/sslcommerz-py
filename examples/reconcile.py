"""Reconcile orders whose IPN never arrived.

python examples/reconcile.py examples/orders.csv

The CSV holds what *your* database expects (``tran_id``, ``amount``,
``currency``). Each order is checked with the read-only Transaction Query API;
amount and currency mismatches and double payments are printed first.
The same report is available as ``sslcommerz reconcile orders.csv``.
"""

from __future__ import annotations

import sys

from sslcommerz_py import SSLCommerz, load_orders, reconcile

orders = load_orders(sys.argv[1] if len(sys.argv) > 1 else "examples/orders.csv")

with SSLCommerz.from_env() as sslc:
    report = reconcile(sslc, orders, delay=0.2)

for r in report.problems:
    print("CHECK", r.tran_id, r.status.value, r.detail)
for r in report.results:
    if r.ok:
        print("PAID ", r.tran_id, r.paid_amount, r.paid_currency, r.bank_tran_id, "HIGH RISK" if r.high_risk else "")
for r in report.unpaid:
    print("OPEN ", r.tran_id, r.status.value, " ".join(r.gateway_statuses))
print(report.counts())
sys.exit(1 if report.has_problems else 0)
