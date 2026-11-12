"""FastAPI IPN listener using the async client.

pip install "sslcommerz-py[fastapi]" uvicorn
uvicorn examples.fastapi_app:app --reload
"""

from __future__ import annotations

from typing import Dict, Optional

from fastapi import FastAPI, Request, Response

from sslcommerz_py import AsyncSSLCommerz, PaymentNotValidError, SSLCommerzError


def create_app(client: Optional[AsyncSSLCommerz] = None, orders: Optional[Dict[str, dict]] = None) -> FastAPI:
    app = FastAPI(title="SSLCommerz IPN listener")
    sslc = client or AsyncSSLCommerz.from_env()
    db: Dict[str, dict] = orders if orders is not None else {}

    @app.post("/sslc/ipn")
    async def ipn(request: Request) -> Response:
        form = dict(await request.form())
        tran_id = str(form.get("tran_id", ""))
        order = db.get(tran_id)
        if order is None:
            return Response(status_code=200)  # unknown order: acknowledge, do nothing
        try:
            paid = await sslc.verify_ipn(
                form,
                expected_tran_id=tran_id,
                expected_amount=order["amount"],
                expected_currency=order["currency"],
            )
        except PaymentNotValidError as exc:
            if order["status"] == "pending":
                order["status"] = exc.status.lower() or "failed"
        except SSLCommerzError:
            # Hash mismatch, amount mismatch or gateway trouble: leave the
            # order as it is and reconcile later with query_by_tran_id().
            pass
        else:
            order["status"] = "review" if paid.is_high_risk else "paid"
            order["bank_tran_id"] = paid.validation.bank_tran_id
        return Response(status_code=200)

    @app.get("/orders/{tran_id}")
    async def get_order(tran_id: str) -> dict:
        return db.get(tran_id, {})

    return app


try:  # pragma: no cover - only when credentials are configured
    app = create_app()
except SSLCommerzError:  # pragma: no cover
    app = None
