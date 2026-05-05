"""Central configuration for prediction-bot."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root so all os.environ.get() calls work
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

# Kalshi
KALSHI_DEMO_BASE = "https://demo-api.kalshi.co/trade-api/v2"
KALSHI_PROD_BASE = "https://trading-api.kalshi.com/trade-api/v2"
KALSHI_API_KEY_FILE = CONFIG_DIR / "kalshi_api_key_id.txt"
KALSHI_PRIVATE_KEY_FILE = CONFIG_DIR / "kalshi_private_key.pem"

# Polymarket (read-only, no auth)
POLY_GAMMA_BASE = "https://gamma-api.polymarket.com"
POLY_CLOB_BASE = "https://clob.polymarket.com"
POLY_DATA_BASE = "https://data-api.polymarket.com"

# Use demo by default — switch to prod only when ready
KALSHI_BASE_URL = KALSHI_DEMO_BASE

def kalshi_api_key_id() -> str:
    return KALSHI_API_KEY_FILE.read_text().strip()

def kalshi_private_key_pem() -> bytes:
    return KALSHI_PRIVATE_KEY_FILE.read_bytes()


# ── Phase 2: AI Analyst ──────────────────────────────────────────────────────
# Anthropic API — loaded from .env (ANTHROPIC_API_KEY)
# Model used for market analysis (cheap + fast)
ANALYST_MODEL = "claude-haiku-4-5"

# Edge detection thresholds
EDGE_MIN_PCT = 4.0          # ignore edges below this %
EDGE_MAX_KELLY = 0.10       # never bet more than 10% of bankroll
EDGE_KELLY_FRACTION = 0.25  # use 25% of full Kelly (quarter-Kelly)
