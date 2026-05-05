"""AI Analyst — uses Claude to estimate the probability of a market outcome.

Sends market title + recent news headlines to Claude claude-haiku-4-5 (cheap + fast)
and extracts a calibrated probability estimate with reasoning.

Requires ANTHROPIC_API_KEY in environment.
"""
import json
import os
from dataclasses import dataclass

import httpx

from src.analyst.news_fetcher import NewsItem


ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-haiku-4-5"


@dataclass
class AnalysisResult:
    market_title: str
    ai_probability: float       # 0.0 – 1.0, AI's calibrated estimate
    market_price: float         # current market price (reference)
    edge: float                 # ai_probability - market_price (signed)
    reasoning: str              # LLM's brief reasoning
    news_count: int             # how many news articles were fed in
    confidence: str             # "high" | "medium" | "low"
    error: str | None = None    # set if LLM call failed

    @property
    def edge_pct(self) -> float:
        return self.edge * 100

    @property
    def direction(self) -> str:
        if self.edge > 0.03:
            return "BUY YES"
        elif self.edge < -0.03:
            return "BUY NO"
        else:
            return "HOLD"

    def summary(self) -> str:
        lines = [
            f"Market:       {self.market_title[:70]}",
            f"Market price: {self.market_price*100:.1f}%  |  AI estimate: {self.ai_probability*100:.1f}%",
            f"Edge:         {self.edge_pct:+.1f}%  →  {self.direction}",
            f"Confidence:   {self.confidence}  |  News items: {self.news_count}",
            f"Reasoning:    {self.reasoning[:280]}",
        ]
        if self.error:
            lines.append(f"[WARN] {self.error}")
        return "\n".join(lines)


class AIAnalyst:
    """Calls Claude to estimate the probability of a binary market outcome."""

    TIMEOUT = 45.0

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self._client = httpx.Client(timeout=self.TIMEOUT)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._client.close()

    def close(self):
        self._client.close()

    def analyze(
        self,
        market_title: str,
        market_yes_price: float,
        news: list[NewsItem] | None = None,
        extra_context: str = "",
    ) -> AnalysisResult:
        """Return an AI probability estimate for a binary market."""
        if not self.api_key:
            return AnalysisResult(
                market_title=market_title,
                ai_probability=market_yes_price,
                market_price=market_yes_price,
                edge=0.0,
                reasoning="ANTHROPIC_API_KEY not set — returning market price as estimate.",
                news_count=0,
                confidence="low",
                error="No API key",
            )

        news = news or []
        prompt = self._build_prompt(market_title, market_yes_price, news, extra_context)

        try:
            raw = self._call_claude(prompt)
            return self._parse_response(raw, market_title, market_yes_price, len(news))
        except Exception as exc:
            return AnalysisResult(
                market_title=market_title,
                ai_probability=market_yes_price,
                market_price=market_yes_price,
                edge=0.0,
                reasoning=f"LLM call failed: {exc}",
                news_count=len(news),
                confidence="low",
                error=str(exc),
            )

    def _build_prompt(
        self,
        market_title: str,
        market_price: float,
        news: list[NewsItem],
        extra_context: str,
    ) -> str:
        news_block = ""
        if news:
            items = "\n".join(
                f"  {i+1}. {n.to_context_str()}" for i, n in enumerate(news)
            )
            news_block = f"\nRecent news headlines:\n{items}\n"
        else:
            news_block = "\nNo recent news found for this topic.\n"

        extra = f"\nAdditional context:\n{extra_context}\n" if extra_context else ""

        return f"""You are a calibrated prediction market analyst. Your job is to estimate the true probability of a binary outcome and identify mispricing.

Binary market question:
"{market_title}"

Current market price (implied probability): {market_price*100:.1f}%
{news_block}{extra}
Task:
1. Based on the question and the news above, estimate the TRUE probability this resolves YES.
2. Be calibrated — avoid anchoring on the market price.
3. Provide a brief reasoning (2-3 sentences max).
4. Rate your confidence: high (strong evidence), medium (some evidence), or low (speculative).

Respond in this exact JSON format (no other text):
{{
  "probability": <float 0.0-1.0>,
  "confidence": "<high|medium|low>",
  "reasoning": "<2-3 sentence reasoning>"
}}"""

    def _call_claude(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "max_tokens": 256,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        resp = self._client.post(ANTHROPIC_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]

    def _parse_response(
        self,
        raw: str,
        market_title: str,
        market_price: float,
        news_count: int,
    ) -> AnalysisResult:
        """Parse Claude's JSON response into an AnalysisResult."""
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON substring
            import re
            m = re.search(r'\{[^}]+\}', text, re.DOTALL)
            if m:
                parsed = json.loads(m.group())
            else:
                raise ValueError(f"Could not parse JSON from: {text[:200]}")

        probability = float(parsed["probability"])
        probability = max(0.01, min(0.99, probability))
        edge = probability - market_price

        return AnalysisResult(
            market_title=market_title,
            ai_probability=probability,
            market_price=market_price,
            edge=edge,
            reasoning=parsed.get("reasoning", ""),
            news_count=news_count,
            confidence=parsed.get("confidence", "low"),
        )
