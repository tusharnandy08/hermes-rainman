# prediction-bot

AI-native prediction market trading system. Trades on **Kalshi** (CFTC-regulated, US) using **Polymarket** as a read-only cross-market data source for edge detection.

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Market     │────▶│  AI Analyst  │────▶│    Edge      │
│   Scanner    │     │              │     │   Detector   │
└──────────────┘     └──────────────┘     └──────────────┘
       │                                         │
       │  polls Kalshi + Polymarket              │  price gaps, AI vs market
       │  prices, volumes, spreads               │  disagreements, tail events
       │                                         ▼
       │                                  ┌──────────────┐
       │                                  │    Risk      │
       │                                  │   Manager    │
       │                                  └──────────────┘
       │                                         │
       │                                         │  Kelly sizing, bankroll limits
       │                                         ▼
       │                                  ┌──────────────┐
       └─────────────────────────────────▶│   Executor   │
                                          │              │
                                          └──────────────┘
                                                 │
                                                 │  places orders on Kalshi
                                                 ▼
                                          ┌──────────────┐
                                          │  Kalshi Demo │
                                          │    (paper)   │
                                          └──────────────┘
```

**Five components:**

| Component | Role |
|-----------|------|
| **Market Scanner** | Polls Kalshi + Polymarket for active markets, prices, volumes. Detects cross-platform price gaps. |
| **AI Analyst** | Scrapes news sources, feeds context to an LLM, produces calibrated probability estimates for events. |
| **Edge Detector** | Compares AI probabilities vs market prices. Finds cross-market arbitrage, AI-vs-market disagreements, and underpriced tail events. |
| **Risk Manager** | Kelly criterion position sizing, max exposure per market, bankroll management. Prevents ruin. |
| **Executor** | Places and manages orders on Kalshi. Logs reasoning for every trade. Paper trades first. |

## Setup

```bash
# Clone and install
git clone https://github.com/tusharnandy08/prediction-bot.git
cd prediction-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Add your Kalshi demo credentials
# Get them from https://demo.kalshi.co → Account & Security → API Keys
echo "your-api-key-id" > config/kalshi_api_key_id.txt
# Paste your private key into:
#   config/kalshi_private_key.pem

# Verify connectivity
python -m src.main status
```

## CLI Commands

```bash
python -m src.main status              # Check connectivity to Kalshi + Polymarket
python -m src.main balance             # Show Kalshi demo balance
python -m src.main markets --limit 20  # List active Kalshi markets
python -m src.main search "Trump"      # Search Polymarket events
python -m src.main scan --limit 30     # Full dual-platform scan + spread detection
```

## Roadmap

### Phase 1: Scaffold & Connectivity ✅

Core infrastructure and API clients.

- [x] Project structure with modular component directories
- [x] Kalshi API client with RSA-PSS request signing
- [x] Polymarket read-only client (Gamma, CLOB, Data APIs)
- [x] Market Scanner with dual-platform polling
- [x] Cross-market spread detection (title-matching heuristic)
- [x] CLI with status, balance, markets, search, scan commands
- [x] Demo environment configuration, credentials gitignored

### Phase 2: AI Analyst & Edge Detection

The intelligence layer — where the AI edge comes from.

- [ ] News scraper module (RSS feeds, news APIs, social signals)
- [ ] LLM integration for probability estimation (prompt engineering for calibration)
- [ ] Structured output: event description → probability + confidence + reasoning
- [ ] Edge Detector: compare AI probabilities vs live market prices
- [ ] Cross-market arbitrage detector (Kalshi vs Polymarket price gaps)
- [ ] Tail event detector (markets underpricing low-probability events)
- [ ] Semantic market matching across platforms (upgrade from title keywords to embeddings)
- [ ] Backtesting framework: test AI predictions against historical outcomes

### Phase 3: Risk Management & Paper Trading

Position sizing and live paper trading on Kalshi demo.

- [ ] Kelly criterion position sizing (full Kelly and fractional Kelly)
- [ ] Bankroll management: max exposure per market, per category, total
- [ ] Drawdown protection: pause trading if bankroll drops below threshold
- [ ] Executor module: place limit orders on Kalshi demo
- [ ] Order lifecycle management (create, monitor, amend, cancel)
- [ ] Trade logging: every order records the AI reasoning, edge size, Kelly fraction
- [ ] Portfolio dashboard: positions, P&L, win rate, calibration curve
- [ ] Run paper trading for 2-4 weeks, measure edge and calibration

### Phase 4: Go Live

Real money on Kalshi production, starting small.

- [ ] Production environment configuration (separate API keys)
- [ ] Conservative position limits ($50-100 initial bankroll)
- [ ] Alerting: notify on fills, large price moves, approaching position limits
- [ ] WebSocket integration for real-time price feeds (replace polling)
- [ ] Automated scheduling: periodic scan → analyze → trade cycle
- [ ] Performance tracking: Sharpe ratio, calibration, Brier score
- [ ] Gradual bankroll scaling based on demonstrated edge

### Future Ideas

- Multi-model ensemble (run multiple LLMs, aggregate probabilities)
- Fine-tuned model on prediction market outcomes
- Social sentiment analysis (Twitter/X, Reddit, Telegram)
- Event-driven triggers (breaking news → immediate re-evaluation)
- FIX protocol integration for lower latency
- Web dashboard for monitoring

## Platform Details

| | Kalshi | Polymarket |
|---|---|---|
| **Role** | Primary trading platform | Read-only data source |
| **Regulation** | CFTC-regulated (US) | Crypto-based, no US trading |
| **Auth** | RSA key-pair signing | None needed (public APIs) |
| **Demo/Paper** | Yes — full sandbox | No |
| **Data** | REST + WebSocket + FIX | REST (public) |

## Project Structure

```
prediction-bot/
├── config/
│   ├── settings.py              # Central config (URLs, env toggle)
│   ├── kalshi_api_key_id.txt    # API key ID (gitignored)
│   └── kalshi_private_key.pem   # RSA private key (gitignored)
├── src/
│   ├── clients/
│   │   ├── kalshi.py            # Kalshi API client (auth, trading, portfolio)
│   │   └── polymarket.py        # Polymarket read-only client
│   ├── scanner/
│   │   └── market_scanner.py    # Dual-platform scanner + spread detector
│   ├── analyst/                 # [Phase 2] AI probability estimation
│   ├── edge/                    # [Phase 2] Edge detection
│   ├── risk/                    # [Phase 3] Position sizing
│   ├── executor/                # [Phase 3] Order execution
│   ├── utils/
│   └── main.py                  # CLI entry point
├── data/                        # Market snapshots, trade logs (gitignored)
├── logs/                        # Application logs (gitignored)
├── requirements.txt
└── .gitignore
```

## License

Private — not for redistribution.
