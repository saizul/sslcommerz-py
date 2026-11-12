"""Create a sandbox payment session and print the gateway URL.

export SSLCOMMERZ_STORE_ID=your_sandbox_store_id
export SSLCOMMERZ_STORE_PASSWD=your_sandbox_store_password
python examples/create_session.py 500
"""

from __future__ import annotations

import sys
import uuid

from sslcommerz_py import CartItem, Customer, PaymentRequest, Product, SSLCommerz

amount = sys.argv[1] if len(sys.argv) > 1 else "100.00"

with SSLCommerz.from_env() as sslc:
    session = sslc.create_session(
        PaymentRequest(
            total_amount=amount,
            tran_id=uuid.uuid4().hex[:30],
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
            product=Product(name="Demo order", category="general"),
            cart=[CartItem(product="Demo item", quantity=1, amount=amount)],
            value_a="order-42",
        )
    )
    print("sessionkey:", session.sessionkey)
    print("open:", session.gateway_page_url)
