"""Market Scanner — polls both Kalshi and Polymarket for active markets.

Finds markets with volume, identifies cross-platform overlaps,
and surfaces interesting opportunities for the AI Analyst.
"""
import json
from dataclasses import dataclass, field
from typing import Any

from src.clients.kalshi import KalshiClient
from src.clients.polymarket import PolymarketClient


@dataclass
class MarketSnapshot:
    """Unified market representation across platforms."""
    platform: str              # "kalshi" or "polymarket"
    ticker: str                # market identifier
    title: str                 # human-readable question
    yes_price: float           # 0.0 - 1.0
    no_price: float            # 0.0 - 1.0
    volume: float              # USD volume
    status: str                # open, closed, settled
    event_ticker: str = ""     # parent event
    extra: dict = field(default_factory=dict)


class MarketScanner:
    """Scans Kalshi and Polymarket for active markets and cross-platform spreads."""

    def __init__(self, kalshi: KalshiClient, polymarket: PolymarketClient):
        self.kalshi = kalshi
        self.poly = polymarket

    # ── Kalshi scanning ─────────────────────────────────────────────────
    def scan_kalshi(self, limit: int = 50, status: str = "open") -> list[MarketSnapshot]:
        """Fetch active Kalshi markets."""
        data = self.kalshi.get_markets(limit=limit, status=status)
        markets = data.get("markets", [])
        results = []
        for m in markets:
            # API returns _dollars fields (string) or legacy integer cent fields
            def _price(dollar_key: str, cent_key: str) -> float:
                d = m.get(dollar_key)
                if d is not None:
                    try:
                        v = float(d)
                        if v > 0:
                            return v  # already in 0-1 range as dollar (e.g. "0.55")
                    except (ValueError, TypeError):
                        pass
                c = m.get(cent_key)
                if c:
                    try:
                        return int(c) / 100
                    except (ValueError, TypeError):
                        pass
                return None

            yes_price = _price("yes_ask_dollars", "yes_ask")
            no_price  = _price("no_ask_dollars",  "no_ask")

            # Fall back to last traded price, then 0.5 (unknown)
            if not yes_price:
                yes_price = _price("last_price_dollars", "last_price") or 0.5
            if not no_price:
                no_price = round(1.0 - yes_price, 4)

            # Volume: try float field first, then legacy int
            vol_raw = m.get("volume_fp") or m.get("volume", 0)
            try:
                volume = float(vol_raw)
            except (ValueError, TypeError):
                volume = 0.0

            results.append(MarketSnapshot(
                platform="kalshi",
                ticker=m.get("ticker", ""),
                title=m.get("title", m.get("subtitle", "")),
                yes_price=yes_price,
                no_price=no_price,
                volume=volume,
                status=m.get("status", "unknown"),
                event_ticker=m.get("event_ticker", ""),
                extra={"open_interest": m.get("open_interest_fp", m.get("open_interest", 0)),
                       "last_price": m.get("last_price_dollars", m.get("last_price", 0))},
            ))
        return results

    # ── Polymarket scanning ─────────────────────────────────────────────
    def scan_polymarket(self, limit: int = 50) -> list[MarketSnapshot]:
        """Fetch top Polymarket markets by 24h volume."""
        markets = self.poly.get_markets(limit=limit)
        results = []
        for m in markets:
            prices = PolymarketClient.parse_prices(m)
            if prices:
                yes_p, no_p = prices
            else:
                yes_p, no_p = 0.5, 0.5
            results.append(MarketSnapshot(
                platform="polymarket",
                ticker=m.get("conditionId", m.get("id", "")),
                title=m.get("question", ""),
                yes_price=yes_p,
                no_price=no_p,
                volume=float(m.get("volume", 0) or 0),
                status="open" if m.get("active") else "closed",
                event_ticker=m.get("groupItemTitle", ""),
                extra={"liquidity": m.get("liquidity", 0),
                       "volume_24h": m.get("volume24hr", 0)},
            ))
        return results

    # ── Cross-platform comparison ───────────────────────────────────────
    def find_cross_market_spreads(self, kalshi_markets: list[MarketSnapshot],
                                   poly_markets: list[MarketSnapshot],
                                   min_spread: float = 0.03) -> list[dict]:
        """Find markets that exist on both platforms with price divergence.

        This is a simple title-matching heuristic — will be upgraded to
        semantic matching with embeddings later.
        """
        spreads = []
        # Build lookup by normalized title keywords
        poly_index: dict[str, MarketSnapshot] = {}
        for pm in poly_markets:
            key = self._normalize_title(pm.title)
            if key:
                poly_index[key] = pm

        for km in kalshi_markets:
            key = self._normalize_title(km.title)
            if key and key in poly_index:
                pm = poly_index[key]
                spread = abs(km.yes_price - pm.yes_price)
                if spread >= min_spread:
                    spreads.append({
                        "kalshi": km,
                        "polymarket": pm,
                        "spread": spread,
                        "kalshi_yes": km.yes_price,
                        "poly_yes": pm.yes_price,
                    })

        return sorted(spreads, key=lambda x: x["spread"], reverse=True)

    @staticmethod
    def _normalize_title(title: str) -> str:
        """Crude title normalization for cross-platform matching."""
        import re
        title = title.lower().strip()
        title = re.sub(r'[^a-z0-9\s]', '', title)
        words = sorted(set(title.split()))
        return " ".join(words) if len(words) >= 3 else ""

    # ── Full scan ───────────────────────────────────────────────────────
    def full_scan(self, limit: int = 50) -> dict:
        """Run a complete scan of both platforms."""
        kalshi = self.scan_kalshi(limit=limit)
        poly = self.scan_polymarket(limit=limit)
        spreads = self.find_cross_market_spreads(kalshi, poly)
        return {
            "kalshi_markets": kalshi,
            "polymarket_markets": poly,
            "cross_market_spreads": spreads,
            "kalshi_count": len(kalshi),
            "poly_count": len(poly),
            "spread_count": len(spreads),
        }
