"""Kalshi API client with RSA key-pair authentication.

Handles request signing, market discovery, orderbook queries,
portfolio management, and order execution against the Kalshi demo API.
"""
import time
import base64
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from config.settings import KALSHI_BASE_URL, kalshi_api_key_id, kalshi_private_key_pem


class KalshiClient:
    """Authenticated Kalshi API client."""

    def __init__(self, base_url: str | None = None, key_id: str | None = None,
                 private_key_pem: bytes | None = None):
        self.base_url = (base_url or KALSHI_BASE_URL).rstrip("/")
        self.key_id = key_id or kalshi_api_key_id()
        pem = private_key_pem or kalshi_private_key_pem()
        self.private_key = serialization.load_pem_private_key(pem, password=None)
        self.http = httpx.Client(timeout=30.0)

    # ── Auth ────────────────────────────────────────────────────────────
    def _sign(self, timestamp_ms: int, method: str, full_path: str) -> str:
        """RSA-PSS signature over timestamp + method + full_url_path.

        full_path must be the complete URL path from root, e.g.
        /trade-api/v2/portfolio/balance (NOT just /portfolio/balance).
        Query params must be stripped before signing.
        """
        path_no_query = full_path.split("?")[0]
        message = f"{timestamp_ms}{method}{path_no_query}".encode("utf-8")
        sig = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(sig).decode("utf-8")

    def _auth_headers(self, method: str, full_path: str) -> dict[str, str]:
        ts = int(time.time() * 1000)
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": str(ts),
            "KALSHI-ACCESS-SIGNATURE": self._sign(ts, method, full_path),
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        # Extract the full URL path (e.g. /trade-api/v2/portfolio/balance)
        from urllib.parse import urlparse
        full_path = urlparse(url).path
        headers = self._auth_headers(method.upper(), full_path)
        resp = self.http.request(method.upper(), url, headers=headers, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else None

    def get(self, path: str, params: dict | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: dict | None = None) -> Any:
        return self._request("POST", path, json=json)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def put(self, path: str, json: dict | None = None) -> Any:
        return self._request("PUT", path, json=json)

    # ── Market Discovery ────────────────────────────────────────────────
    def get_markets(self, limit: int = 20, cursor: str | None = None,
                    status: str | None = None, ticker: str | None = None,
                    event_ticker: str | None = None) -> dict:
        params = {"limit": limit}
        if cursor: params["cursor"] = cursor
        if status: params["status"] = status
        if ticker: params["ticker"] = ticker
        if event_ticker: params["event_ticker"] = event_ticker
        return self.get("/markets", params=params)

    def get_market(self, ticker: str) -> dict:
        return self.get(f"/markets/{ticker}")

    def get_events(self, limit: int = 20, cursor: str | None = None,
                   status: str | None = None) -> dict:
        params = {"limit": limit}
        if cursor: params["cursor"] = cursor
        if status: params["status"] = status
        return self.get("/events", params=params)

    def get_event(self, event_ticker: str) -> dict:
        return self.get(f"/events/{event_ticker}")

    # ── Market Data ─────────────────────────────────────────────────────
    def get_orderbook(self, ticker: str) -> dict:
        return self.get(f"/markets/{ticker}/orderbook")

    def get_candlesticks(self, ticker: str, period: str = "1h",
                         start_ts: int | None = None,
                         end_ts: int | None = None) -> dict:
        params = {"period_interval": period}
        if start_ts: params["start_ts"] = start_ts
        if end_ts: params["end_ts"] = end_ts
        return self.get(f"/markets/{ticker}/candlesticks", params=params)

    def get_trades(self, ticker: str | None = None, limit: int = 100,
                   cursor: str | None = None) -> dict:
        params = {"limit": limit}
        if ticker: params["ticker"] = ticker
        if cursor: params["cursor"] = cursor
        return self.get("/trades", params=params)

    # ── Portfolio ───────────────────────────────────────────────────────
    def get_balance(self) -> dict:
        return self.get("/portfolio/balance")

    def get_positions(self, limit: int = 100,
                      settlement_status: str | None = None) -> dict:
        params = {"limit": limit}
        if settlement_status: params["settlement_status"] = settlement_status
        return self.get("/portfolio/positions", params=params)

    def get_orders(self, ticker: str | None = None, status: str | None = None,
                   limit: int = 100) -> dict:
        params = {"limit": limit}
        if ticker: params["ticker"] = ticker
        if status: params["status"] = status
        return self.get("/portfolio/orders", params=params)

    def get_fills(self, ticker: str | None = None, limit: int = 100) -> dict:
        params = {"limit": limit}
        if ticker: params["ticker"] = ticker
        return self.get("/portfolio/fills", params=params)

    # ── Order Management ────────────────────────────────────────────────
    def create_order(self, ticker: str, side: str, type: str = "limit",
                     action: str = "buy", count: int = 1,
                     yes_price: int | None = None,
                     no_price: int | None = None,
                     expiration_ts: int | None = None) -> dict:
        """Place an order. Prices in cents (1-99)."""
        body = {
            "ticker": ticker,
            "side": side,      # "yes" or "no"
            "type": type,      # "limit" or "market"
            "action": action,  # "buy" or "sell"
            "count": count,
        }
        if yes_price is not None: body["yes_price"] = yes_price
        if no_price is not None: body["no_price"] = no_price
        if expiration_ts: body["expiration_ts"] = expiration_ts
        return self.post("/portfolio/orders/v2", json=body)

    def cancel_order(self, order_id: str) -> Any:
        return self.delete(f"/portfolio/orders/{order_id}")

    # ── Utilities ───────────────────────────────────────────────────────
    def health_check(self) -> bool:
        """Quick connectivity + auth check: fetch balance."""
        try:
            bal = self.get_balance()
            return "balance" in bal
        except Exception:
            return False

    def close(self):
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
