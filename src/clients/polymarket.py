"""Polymarket read-only API client.

Queries the Gamma (discovery), CLOB (prices/books), and Data (trades) APIs.
No auth required — all public endpoints.
"""
import json
from typing import Any

import httpx

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from config.settings import POLY_GAMMA_BASE, POLY_CLOB_BASE, POLY_DATA_BASE


class PolymarketClient:
    """Read-only Polymarket client for price discovery and cross-market comparison."""

    def __init__(self):
        self.http = httpx.Client(timeout=30.0)

    # ── Gamma API (discovery) ───────────────────────────────────────────
    def search_markets(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search for markets/events."""
        resp = self.http.get(
            f"{POLY_GAMMA_BASE}/events",
            params={"title": query, "limit": limit, "active": True, "closed": False},
        )
        resp.raise_for_status()
        return resp.json()

    def get_market(self, condition_id: str) -> dict:
        resp = self.http.get(f"{POLY_GAMMA_BASE}/markets/{condition_id}")
        resp.raise_for_status()
        return resp.json()

    def get_markets(self, limit: int = 20, offset: int = 0,
                    order: str = "volume24hr", ascending: bool = False,
                    active: bool = True) -> list[dict]:
        """Fetch markets sorted by volume or other criteria."""
        resp = self.http.get(
            f"{POLY_GAMMA_BASE}/markets",
            params={
                "limit": limit, "offset": offset,
                "order": order, "ascending": ascending,
                "active": active, "closed": False,
            },
        )
        resp.raise_for_status()
        return resp.json()

    def get_events(self, limit: int = 20, offset: int = 0,
                   active: bool = True) -> list[dict]:
        resp = self.http.get(
            f"{POLY_GAMMA_BASE}/events",
            params={"limit": limit, "offset": offset,
                    "active": active, "closed": False},
        )
        resp.raise_for_status()
        return resp.json()

    # ── CLOB API (prices/orderbooks) ────────────────────────────────────
    def get_orderbook(self, token_id: str) -> dict:
        resp = self.http.get(f"{POLY_CLOB_BASE}/book", params={"token_id": token_id})
        resp.raise_for_status()
        return resp.json()

    def get_price(self, token_id: str) -> dict:
        resp = self.http.get(f"{POLY_CLOB_BASE}/price", params={"token_id": token_id})
        resp.raise_for_status()
        return resp.json()

    def get_midpoint(self, token_id: str) -> dict:
        resp = self.http.get(f"{POLY_CLOB_BASE}/midpoint", params={"token_id": token_id})
        resp.raise_for_status()
        return resp.json()

    # ── Data API (trades/OI) ────────────────────────────────────────────
    def get_trades(self, condition_id: str | None = None,
                   limit: int = 100) -> list[dict]:
        params = {"limit": limit}
        if condition_id: params["condition_id"] = condition_id
        resp = self.http.get(f"{POLY_DATA_BASE}/trades", params=params)
        resp.raise_for_status()
        return resp.json()

    # ── Helpers ─────────────────────────────────────────────────────────
    @staticmethod
    def parse_prices(market: dict) -> tuple[float, float] | None:
        """Extract (yes_price, no_price) from double-encoded outcomePrices."""
        raw = market.get("outcomePrices")
        if not raw:
            return None
        try:
            prices = json.loads(raw) if isinstance(raw, str) else raw
            return (float(prices[0]), float(prices[1]))
        except (json.JSONDecodeError, IndexError, TypeError):
            return None

    @staticmethod
    def parse_token_ids(market: dict) -> tuple[str, str] | None:
        """Extract (yes_token, no_token) from double-encoded clobTokenIds."""
        raw = market.get("clobTokenIds")
        if not raw:
            return None
        try:
            ids = json.loads(raw) if isinstance(raw, str) else raw
            return (ids[0], ids[1])
        except (json.JSONDecodeError, IndexError, TypeError):
            return None

    def health_check(self) -> bool:
        try:
            resp = self.http.get(f"{POLY_GAMMA_BASE}/markets", params={"limit": 1})
            return resp.status_code == 200
        except Exception:
            return False

    def close(self):
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
