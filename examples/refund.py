"""Initiate a refund and poll its status.

python examples/refund.py <bank_tran_id> <amount> "<remarks>"
"""

from __future__ import annotations

import sys
import time
import uuid

from sslcommerz_py import RefundError, SSLCommerz

if len(sys.argv) != 4:
    sys.exit("usage: refund.py <bank_tran_id> <amount> <remarks>")

bank_tran_id, amount, remarks = sys.argv[1:]

with SSLCommerz.from_env() as sslc:
    # Store refund_trans_id before calling, so a retry after a crash reuses it.
    refund_trans_id = "RF" + uuid.uuid4().hex[:28]
    try:
        refund = sslc.refund(
            bank_tran_id=bank_tran_id,
            refund_amount=amount,
            refund_remarks=remarks,
            refund_trans_id=refund_trans_id,
        )
    except RefundError as exc:
        sys.exit(f"refund rejected: {exc.reason}")

    print("status:", refund.status, "refund_ref_id:", refund.refund_ref_id)
    if refund.refund_ref_id:
        for _ in range(5):
            status = sslc.refund_status(refund.refund_ref_id)
            print("refund status:", status.status)
            if status.status != "processing":
                break
            time.sleep(10)
