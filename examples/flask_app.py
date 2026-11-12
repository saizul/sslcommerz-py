"""Flask checkout with an SSLCommerz IPN listener.

    pip install "sslcommerz-py[flask]"
    export SSLCOMMERZ_STORE_ID=your_sandbox_store_id
    export SSLCOMMERZ_STORE_PASSWD=your_sandbox_store_password
    export PUBLIC_BASE_URL=https://your-tunnel.example.com   # must be reachable by SSLCommerz for IPN
    flask --app examples/flask_app.py run

Flow: POST /checkout -> redirect to GatewayPageURL -> customer pays ->
SSLCommerz POSTs to /sslc/ipn (server to server) and redirects the customer
to /sslc/success, /sslc/fail or /sslc/cancel.
"""

from __future__ import annotations

import os
import uuid
from typing import Dict, Optional

from flask import Flask, abort, jsonify, redirect, request

from sslcommerz_py import Customer, IPNVerifier, PaymentRequest, Product, SSLCommerz, SSLCommerzError


def create_app(client: Optional[SSLCommerz] = None, orders: Optional[Dict[str, dict]] = None) -> Flask:
    app = Flask(__name__)
    sslc = client or SSLCommerz.from_env()
    # Stand-in for your database: tran_id -> order.
    db: Dict[str, dict] = orders if orders is not None else {}
    base = os.environ.get("PUBLIC_BASE_URL", "http://localhost:5000").rstrip("/")

    def lookup(tran_id: str):
        order = db.get(tran_id)
        return (order["amount"], order["currency"]) if order else None

    verifier = IPNVerifier(sslc, lookup)

    @app.post("/checkout")
    def checkout():
        tran_id = uuid.uuid4().hex[:30]
        amount = "1250.00"  # from your cart, never from the browser
        db[tran_id] = {"amount": amount, "currency": "BDT", "status": "pending"}
        session = sslc.create_session(
            PaymentRequest(
                total_amount=amount,
                tran_id=tran_id,
                success_url=f"{base}/sslc/success",
                fail_url=f"{base}/sslc/fail",
                cancel_url=f"{base}/sslc/cancel",
                ipn_url=f"{base}/sslc/ipn",
                customer=Customer(
                    name="Test Customer",
                    email="customer@example.com",
                    phone="01700000000",
                    add1="House 1, Road 2",
                    city="Dhaka",
                    postcode="1207",
                ),
                product=Product(name="Order " + tran_id, category="general", profile="physical-goods"),
            )
        )
        db[tran_id]["sessionkey"] = session.sessionkey
        return redirect(session.gateway_page_url, code=303)

    @app.post("/sslc/ipn")
    def ipn():
        outcome = verifier.handle(request.form)
        order = db.get(outcome.tran_id or "")
        if outcome.ok and order is not None and outcome.payment is not None:
            # Idempotent: duplicate IPNs (status VALIDATED) leave the order paid.
            order["status"] = "paid"
            order["val_id"] = outcome.payment.validation.val_id
            order["bank_tran_id"] = outcome.payment.validation.bank_tran_id
            if outcome.payment.is_high_risk:
                order["status"] = "review"
        elif (
            order is not None
            and order["status"] == "pending"
            and outcome.status in ("FAILED", "CANCELLED", "EXPIRED", "UNATTEMPTED")
        ):
            order["status"] = outcome.status.lower()
        if outcome.error is not None:
            app.logger.warning("IPN rejected for %s: %s", outcome.tran_id, outcome.error)
        return "", outcome.http_status

    @app.post("/sslc/success")
    def success():
        # The redirect carries the same signed fields as the IPN. Verify them
        # too: the IPN may arrive after the customer.
        tran_id = request.form.get("tran_id", "")
        if tran_id not in db:
            abort(404)
        if db[tran_id]["status"] != "paid":
            try:
                verifier.verify(request.form)
                db[tran_id]["status"] = "paid"
            except SSLCommerzError as exc:
                return jsonify({"tran_id": tran_id, "status": "unverified", "reason": str(exc)}), 400
        return jsonify({"tran_id": tran_id, "status": db[tran_id]["status"]})

    @app.post("/sslc/fail")
    @app.post("/sslc/cancel")
    def not_paid():
        tran_id = request.form.get("tran_id", "")
        return jsonify({"tran_id": tran_id, "status": db.get(tran_id, {}).get("status", "unknown")})

    @app.get("/orders/<tran_id>")
    def order(tran_id: str):
        return jsonify(db.get(tran_id) or {})

    return app


if __name__ == "__main__":  # pragma: no cover
    create_app().run(debug=False)
