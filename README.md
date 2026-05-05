# hermes-rainman 🎯

An AI-native prediction market trading bot for [Kalshi](https://kalshi.com) + [Polymarket](https://polymarket.com).

Scans markets, scrapes news, estimates true probabilities with Claude, sizes positions with Kelly criterion, and executes on Kalshi's demo (and live) API.

---

## Architecture

```
Market Scanner  →  AI Analyst  →  Edge Detector  →  Risk Manager  →  Executor
(Kalshi+Poly)      (Claude+news)   (Kelly sizing)    (guardrails)     (paper/live)
                                                                          ↓
                                                                     Trade Log
                                                                     (SQLite)
```

## Phases

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ Done | Kalshi RSA auth client, Polymarket reader, market scanner, CLI |
| 2 | ✅ Done | AI Analyst (Claude + news), Edge Detector (Kelly criterion) |
| 3 | ✅ Done | Paper trading loop, SQLite trade journal, P&L reporting |
| 4 | ✅ Done | Live order execution, risk manager, positions/fills/settle |

---

## Setup

```bash
git clone https://github.com/tusharnandy08/hermes-rainman
cd hermes-rainman
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Add Kalshi demo credentials
echo "YOUR_KEY_ID" > config/kalshi_api_key_id.txt
cp your_private_key.pem config/kalshi_private_key.pem

# Add Anthropic API key (for AI analysis)
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## CLI Commands

```
status                    Check Kalshi + Polymarket connectivity
balance                   Show Kalshi demo balance
markets [--limit N]       List top open Kalshi markets
search TEXT               Search Polymarket events
scan [--limit N]          Dual-platform scan + cross-market spreads

analyze TICKER            AI deep-dive on a single Kalshi market
edge [--bankroll $] ...   Full scan → AI analysis → ranked edge table

paper [options]           Paper trading: full pipeline, log to SQLite
live  [options]           Live trading: places real Kalshi demo orders
report [--mode paper]     P&L report, daily summary, open positions
positions [--mode live]   Current Kalshi positions or open paper trades
fills [--limit N]         Kalshi fill history
settle TRADE_ID yes|no    Manually settle a paper trade
```

### Key flags

```
--limit N         Markets to scan (default 30)
--bankroll N      Virtual bankroll for Kelly sizing (default $100)
--min-edge N      Minimum edge % to consider (default 4)
--daily-cap N     Daily spend cap in dollars (default $50)
--no-news         Skip news fetching (faster, less accurate)
--dry-run         Show plan without executing any trades
```

---

## Example workflow

```bash
# 1. Check you're connected
python -m src.main status

# 2. Run a paper trading session (safe, no real money)
python -m src.main paper --bankroll 120 --daily-cap 50

# 3. Review your paper trades
python -m src.main report

# 4. Settle a paper trade that resolved
python -m src.main settle <trade-id> yes

# 5. When ready, preview live trades first
python -m src.main live --dry-run

# 6. Place real Kalshi demo orders (requires confirmation prompt)
python -m src.main live --bankroll 120 --daily-cap 30

# 7. Check live positions and fills
python -m src.main positions
python -m src.main fills
```

---

## Risk controls

The `RiskManager` enforces these guardrails before every trade:

| Rule | Default |
|------|---------|
| Daily spend cap | $50 |
| Max single trade | $20 |
| Max per ticker | $30 |
| Max open positions | 10 |
| Min AI confidence | medium |
| paper_only flag | True (flip to False for live) |

Kelly sizing: full Kelly → 25% fraction → confidence multiplier (1.0/0.5/0.1) → 10% bankroll cap.

---

## Data

- `data/trades.db` — SQLite trade journal (paper + live)
- `config/` — credentials (gitignored)
- `logs/` — runtime logs (empty until Phase 4 daemon)

---

## Notes

- Kalshi demo credentials are separate from production
- Add mock funds at [demo.kalshi.co](https://demo.kalshi.co) (current balance: $120)
- Polymarket is read-only from the US — used as data source only
- AI model: `claude-haiku-4-5` (fast + cheap for market analysis)
- Cross-market spread detection uses keyword matching — semantic matching is a future upgrade
