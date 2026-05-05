"""Executor — routes trade decisions to paper journal or live Kalshi API.

Two modes:
  paper — logs the trade in SQLite, no real orders placed
  live  — sends a limit order to Kalshi demo (or prod), logs the result

The Executor is intentionally thin. Strategy decisions (Kelly sizing,
edge thresholds) belong in EdgeDetector. Safety checks belong in RiskManager.
Executor just carries out the instruction.
"""
import math
from dataclasses import dataclass

from src.clients.kalshi import KalshiClient
from src.edge.edge_detector import EdgeOpportunity
from src.executor.trade_log import Trade, TradeLog
from src.risk.risk_manager import RiskManager, RiskCheck


@dataclass
class ExecutionResult:
    success: bool
    mode: str           # "paper" or "live"
    trade_id: str = ""
    order_id: str = ""  # Kalshi order id (live only)
    message: str = ""
    trade: Trade | None = None


class Executor:
    """Executes trades in paper or live mode."""

    def __init__(
        self,
        trade_log: TradeLog,
        risk_manager: RiskManager,
        kalshi: KalshiClient | None = None,
        mode: str = "paper",   # "paper" | "live"
    ):
        self.log = trade_log
        self.risk = risk_manager
        self.kalshi = kalshi
        self.mode = mode

        if mode == "live" and kalshi is None:
            raise ValueError("KalshiClient required for live mode")

    def execute(self, opportunity: EdgeOpportunity, dollar_bet: float) -> ExecutionResult:
        """Execute a single opportunity. Checks risk first."""

        # Risk gate
        safe_size = self.risk.compute_safe_size(opportunity, dollar_bet, self.mode)
        if safe_size < 0.01:
            return ExecutionResult(
                False, self.mode,
                message="Risk manager: safe_size too small, skipping"
            )

        risk_check = self.risk.check(opportunity, safe_size, self.mode)
        if not risk_check:
            return ExecutionResult(False, self.mode, message=f"Risk: {risk_check.reason}")

        # Compute contract count: dollars / price_per_contract
        price_dollars = opportunity.bet_price  # e.g. 0.45
        contracts = max(1, math.floor(safe_size / price_dollars))
        actual_cost = round(contracts * price_dollars, 4)
        entry_price_cents = round(opportunity.bet_price * 100)

        trade = Trade(
            ticker=opportunity.snapshot.ticker,
            title=opportunity.snapshot.title,
            side=opportunity.side.lower(),   # "yes" or "no"
            contracts=contracts,
            entry_price=entry_price_cents,
            mode=self.mode,
            ai_probability=opportunity.analysis.ai_probability,
            edge=opportunity.edge,
            confidence=opportunity.confidence,
        )

        if self.mode == "paper":
            return self._execute_paper(trade, safe_size)
        else:
            return self._execute_live(trade, entry_price_cents, contracts)

    def _execute_paper(self, trade: Trade, dollar_bet: float) -> ExecutionResult:
        trade.notes = f"paper trade | desired_bet=${dollar_bet:.2f}"
        trade_id = self.log.record(trade)
        return ExecutionResult(
            success=True,
            mode="paper",
            trade_id=trade_id,
            message=(
                f"PAPER BUY {trade.side.upper()} x{trade.contracts} "
                f"@{trade.entry_price:.0f}¢ | cost=${trade.cost_basis:.2f}"
            ),
            trade=trade,
        )

    def _execute_live(
        self, trade: Trade, price_cents: int, contracts: int
    ) -> ExecutionResult:
        try:
            # Place limit order — resting at our price
            body_kwargs: dict = {
                "ticker": trade.ticker,
                "side": trade.side,
                "type": "limit",
                "action": "buy",
                "count": contracts,
            }
            if trade.side == "yes":
                body_kwargs["yes_price"] = price_cents
            else:
                body_kwargs["no_price"] = price_cents

            resp = self.kalshi.create_order(**body_kwargs)
            order = resp.get("order", resp)
            order_id = order.get("order_id", order.get("id", ""))

            trade.kalshi_order_id = order_id
            trade.notes = f"live order submitted | kalshi_id={order_id}"
            trade_id = self.log.record(trade)

            return ExecutionResult(
                success=True,
                mode="live",
                trade_id=trade_id,
                order_id=order_id,
                message=(
                    f"LIVE BUY {trade.side.upper()} x{contracts} "
                    f"@{price_cents}¢ | order_id={order_id} | cost=${trade.cost_basis:.2f}"
                ),
                trade=trade,
            )
        except Exception as exc:
            return ExecutionResult(
                False, "live",
                message=f"Order failed: {exc}",
            )

    def execute_batch(
        self, sized: list[tuple[EdgeOpportunity, float]]
    ) -> list[ExecutionResult]:
        """Execute a ranked list of (opportunity, dollar_bet) pairs."""
        results = []
        for opp, dollar_bet in sized:
            result = self.execute(opp, dollar_bet)
            results.append(result)
            if result.success:
                # Update daily spend cache by re-querying (log is source of truth)
                pass
        return results
