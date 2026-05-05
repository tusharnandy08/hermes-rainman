"""Risk Manager — pre-trade safety checks and position sizing guardrails.

All checks are synchronous and stateless relative to the market.
The RiskManager reads from the TradeLog to enforce daily limits.

Rules enforced:
  1. Daily spend cap (default $50)
  2. Max open positions (default 10)
  3. Max single trade size (default $20)
  4. Max exposure per ticker (default $30)
  5. Min AI confidence (default 'medium')
  6. Paper-only mode flag
"""
from dataclasses import dataclass

from src.edge.edge_detector import EdgeOpportunity
from src.executor.trade_log import TradeLog


@dataclass
class RiskCheck:
    passed: bool
    reason: str = ""

    def __bool__(self):
        return self.passed


class RiskManager:
    """Pre-trade guardrails. Call check() before every order."""

    def __init__(
        self,
        trade_log: TradeLog,
        daily_spend_cap: float = 50.0,
        max_open_positions: int = 10,
        max_single_trade: float = 20.0,
        max_per_ticker: float = 30.0,
        min_confidence: str = "medium",  # 'high' | 'medium' | 'low'
        paper_only: bool = True,
    ):
        self.log = trade_log
        self.daily_spend_cap = daily_spend_cap
        self.max_open_positions = max_open_positions
        self.max_single_trade = max_single_trade
        self.max_per_ticker = max_per_ticker
        self.min_confidence = min_confidence
        self.paper_only = paper_only

        self._confidence_rank = {"low": 0, "medium": 1, "high": 2}

    def check(
        self,
        opportunity: EdgeOpportunity,
        dollar_bet: float,
        mode: str,  # "paper" or "live"
    ) -> RiskCheck:
        """Run all risk checks. Returns first failure or pass."""

        # 0. Paper-only mode
        if mode == "live" and self.paper_only:
            return RiskCheck(False, "paper_only=True — set paper_only=False to enable live trading")

        # 1. Trade size cap
        if dollar_bet > self.max_single_trade:
            return RiskCheck(
                False,
                f"Trade size ${dollar_bet:.2f} exceeds max_single_trade=${self.max_single_trade:.2f}"
            )

        # 2. Daily spend cap
        spent_today = self.log.today_spent()
        if spent_today + dollar_bet > self.daily_spend_cap:
            return RiskCheck(
                False,
                f"Daily spend ${spent_today:.2f} + ${dollar_bet:.2f} would exceed "
                f"daily_spend_cap=${self.daily_spend_cap:.2f}"
            )

        # 3. Open position count
        open_trades = self.log.open_trades(mode=mode)
        if len(open_trades) >= self.max_open_positions:
            return RiskCheck(
                False,
                f"Already have {len(open_trades)} open {mode} positions "
                f"(max={self.max_open_positions})"
            )

        # 4. Per-ticker exposure
        ticker = opportunity.snapshot.ticker
        ticker_exposure = sum(
            t.cost_basis for t in open_trades if t.ticker == ticker
        )
        if ticker_exposure + dollar_bet > self.max_per_ticker:
            return RiskCheck(
                False,
                f"Ticker {ticker} exposure ${ticker_exposure:.2f} + ${dollar_bet:.2f} "
                f"would exceed max_per_ticker=${self.max_per_ticker:.2f}"
            )

        # 5. AI confidence floor
        opp_conf = self._confidence_rank.get(opportunity.confidence, 0)
        min_conf = self._confidence_rank.get(self.min_confidence, 1)
        if opp_conf < min_conf:
            return RiskCheck(
                False,
                f"AI confidence '{opportunity.confidence}' below minimum '{self.min_confidence}'"
            )

        return RiskCheck(True, "all checks passed")

    def compute_safe_size(
        self,
        opportunity: EdgeOpportunity,
        desired_dollars: float,
        mode: str,
    ) -> float:
        """Return the largest safe bet size that passes all checks, down to $0."""
        spent_today = self.log.today_spent()
        open_trades = self.log.open_trades(mode=mode)
        ticker_exposure = sum(
            t.cost_basis for t in open_trades
            if t.ticker == opportunity.snapshot.ticker
        )

        caps = [
            self.max_single_trade,
            max(0.0, self.daily_spend_cap - spent_today),
            max(0.0, self.max_per_ticker - ticker_exposure),
            desired_dollars,
        ]
        return round(min(caps), 2)
