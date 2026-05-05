"""Edge Detector — applies Kelly criterion to AI analysis results.

Ranks markets by expected value and computes Kelly-optimal bet sizes.
This is the decision layer that sits between the AI Analyst and the Executor.
"""
from dataclasses import dataclass
from typing import Sequence

from src.analyst.ai_analyst import AnalysisResult
from src.scanner.market_scanner import MarketSnapshot


@dataclass
class EdgeOpportunity:
    """A market opportunity with Kelly-optimal sizing."""
    snapshot: MarketSnapshot
    analysis: AnalysisResult

    # Edge metrics
    edge: float             # ai_prob - market_price (signed)
    expected_value: float   # EV per dollar: edge * (1 - market_price) for YES buys
    kelly_fraction: float   # Kelly criterion bet size (fraction of bankroll)
    kelly_capped: float     # Kelly fraction capped at max_kelly

    # Trade recommendation
    side: str               # "YES" or "NO"
    bet_price: float        # price you'd pay (market_price for YES, 1-market_price for NO)
    confidence: str

    @property
    def direction(self) -> str:
        return f"BUY {self.side}"

    def summary(self) -> str:
        return (
            f"{self.snapshot.ticker:25s} | "
            f"mkt={self.bet_price*100:.0f}¢ "
            f"ai={self.analysis.ai_probability*100:.0f}% "
            f"edge={self.edge*100:+.1f}% "
            f"EV={self.expected_value*100:.2f}% "
            f"Kelly={self.kelly_capped*100:.1f}% "
            f"→{self.direction} [{self.confidence}]"
        )


class EdgeDetector:
    """Ranks markets by edge and computes Kelly-optimal position sizes.

    Kelly fraction for a binary bet:
      p = AI probability of YES
      q = 1 - p
      b = payout odds (if you bet $1 at 0.40 and win, you get $1/0.40 = $2.50 net)

    Full Kelly:   f* = (p*b - q) / b  =  p - q/b
    Fractional:   cap at max_kelly to reduce variance
    """

    def __init__(
        self,
        min_edge: float = 0.04,         # ignore edges below 4%
        min_ev: float = 0.02,           # ignore EV below 2%
        max_kelly: float = 0.10,        # never bet more than 10% of bankroll on one trade
        kelly_fraction: float = 0.25,   # use 25% of full Kelly (quarter-Kelly)
        confidence_multipliers: dict | None = None,
    ):
        self.min_edge = min_edge
        self.min_ev = min_ev
        self.max_kelly = max_kelly
        self.kelly_fraction = kelly_fraction
        self.confidence_multipliers = confidence_multipliers or {
            "high": 1.0,
            "medium": 0.5,
            "low": 0.1,
        }

    def evaluate(
        self,
        snapshot: MarketSnapshot,
        analysis: AnalysisResult,
    ) -> EdgeOpportunity | None:
        """Evaluate a single market. Returns None if no edge found."""
        p = analysis.ai_probability  # AI's YES probability

        # Determine if YES or NO is the better side
        yes_edge = p - snapshot.yes_price
        no_edge = (1 - p) - snapshot.no_price

        if abs(yes_edge) >= abs(no_edge):
            side = "YES"
            edge = yes_edge
            bet_price = snapshot.yes_price
            q = 1 - p           # probability of losing (market goes NO)
        else:
            side = "NO"
            edge = no_edge
            p_no = 1 - p        # AI's NO probability
            bet_price = snapshot.no_price
            p = p_no            # redefine p as probability of winning the NO bet
            q = 1 - p

        # Skip if edge is too small or wrong direction
        if edge < self.min_edge:
            return None

        # Kelly calculation
        # b = net odds (if bet_price = 0.40 → win $0.60 net on $1 risk → b = 0.60/0.40)
        if bet_price <= 0 or bet_price >= 1:
            return None
        b = (1 - bet_price) / bet_price

        # Full Kelly: f* = (p*b - q) / b
        full_kelly = (p * b - q) / b
        full_kelly = max(0.0, full_kelly)

        # Apply quarter-Kelly and confidence multiplier
        conf_mult = self.confidence_multipliers.get(analysis.confidence, 0.1)
        kelly = min(full_kelly * self.kelly_fraction * conf_mult, self.max_kelly)

        # Expected value: EV = edge * (1 - bet_price) — gain when right
        ev = edge * (1 - bet_price)

        if ev < self.min_ev:
            return None

        return EdgeOpportunity(
            snapshot=snapshot,
            analysis=analysis,
            edge=edge,
            expected_value=ev,
            kelly_fraction=full_kelly,
            kelly_capped=kelly,
            side=side,
            bet_price=bet_price,
            confidence=analysis.confidence,
        )

    def rank(
        self,
        pairs: Sequence[tuple[MarketSnapshot, AnalysisResult]],
    ) -> list[EdgeOpportunity]:
        """Evaluate and rank a list of (snapshot, analysis) pairs by EV."""
        opportunities = []
        for snapshot, analysis in pairs:
            opp = self.evaluate(snapshot, analysis)
            if opp is not None:
                opportunities.append(opp)

        # Sort by EV descending, then by edge descending
        return sorted(
            opportunities,
            key=lambda o: (o.expected_value, abs(o.edge)),
            reverse=True,
        )

    def dollar_sizes(
        self,
        opportunities: list[EdgeOpportunity],
        bankroll: float,
    ) -> list[tuple[EdgeOpportunity, float]]:
        """Compute actual dollar bet sizes given a bankroll.

        Returns list of (opportunity, dollar_amount) tuples.
        Ensures total exposure stays within the bankroll.
        """
        result = []
        remaining = bankroll
        for opp in opportunities:
            if remaining <= 0:
                break
            dollar_bet = min(opp.kelly_capped * bankroll, remaining)
            result.append((opp, round(dollar_bet, 2)))
            remaining -= dollar_bet
        return result
