"""Central configuration for prediction-bot."""
from pathlib import Path

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
