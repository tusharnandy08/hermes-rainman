"""Trade Log — SQLite-backed journal for all paper and live trades.

Schema is append-only. Never delete rows. Settled trades get their
pnl filled in when the market resolves.
"""
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from config import settings


DB_PATH = settings.DATA_DIR / "trades.db"


# ── Schema ───────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS trades (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    mode            TEXT NOT NULL CHECK(mode IN ('paper','live')),
    ticker          TEXT NOT NULL,
    title           TEXT NOT NULL,
    side            TEXT NOT NULL CHECK(side IN ('yes','no')),
    contracts       INTEGER NOT NULL,
    entry_price     REAL NOT NULL,      -- cents paid per contract (1-99)
    cost_basis      REAL NOT NULL,      -- total cost in dollars
    ai_probability  REAL,               -- AI estimate at time of trade
    edge            REAL,               -- edge at time of trade
    confidence      TEXT,
    status          TEXT NOT NULL DEFAULT 'open'
                        CHECK(status IN ('open','settled','cancelled')),
    kalshi_order_id TEXT,               -- set for live trades
    resolution      TEXT,               -- 'yes' or 'no' when settled
    settle_price    REAL,               -- 1.00 or 0.00
    pnl             REAL,               -- realised P&L in dollars
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS daily_summary (
    date            TEXT PRIMARY KEY,   -- YYYY-MM-DD
    trades_placed   INTEGER DEFAULT 0,
    total_spent     REAL DEFAULT 0.0,
    total_pnl       REAL DEFAULT 0.0,
    open_positions  INTEGER DEFAULT 0
);
"""


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class Trade:
    ticker: str
    title: str
    side: str           # "yes" or "no"
    contracts: int
    entry_price: float  # cents (e.g. 45 = 45¢)
    mode: str           # "paper" or "live"
    ai_probability: float = 0.0
    edge: float = 0.0
    confidence: str = "low"
    kalshi_order_id: str = ""
    notes: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: _now())
    status: str = "open"
    resolution: str | None = None
    settle_price: float | None = None
    pnl: float | None = None

    @property
    def cost_basis(self) -> float:
        """Total cost in dollars."""
        return round(self.contracts * self.entry_price / 100, 4)

    @property
    def potential_gain(self) -> float:
        """Max gain if resolves in our favour."""
        return round(self.contracts * (100 - self.entry_price) / 100, 4)

    def summary(self) -> str:
        pnl_str = f"  PnL=${self.pnl:+.2f}" if self.pnl is not None else ""
        return (
            f"[{self.mode.upper()}] {self.ticker} BUY {self.side.upper()} "
            f"x{self.contracts} @{self.entry_price:.0f}¢ "
            f"cost=${self.cost_basis:.2f}{pnl_str} [{self.status}]"
        )


@dataclass
class DailySummary:
    date: str
    trades_placed: int = 0
    total_spent: float = 0.0
    total_pnl: float = 0.0
    open_positions: int = 0


# ── TradeLog ─────────────────────────────────────────────────────────────────

class TradeLog:
    """Append-only SQLite trade journal."""

    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(DDL)

    # ── Write ─────────────────────────────────────────────────────────────

    def record(self, trade: Trade) -> str:
        """Insert a new trade. Returns trade id."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO trades
                   (id, created_at, mode, ticker, title, side, contracts,
                    entry_price, cost_basis, ai_probability, edge, confidence,
                    status, kalshi_order_id, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    trade.id, trade.created_at, trade.mode,
                    trade.ticker, trade.title, trade.side, trade.contracts,
                    trade.entry_price, trade.cost_basis,
                    trade.ai_probability, trade.edge, trade.confidence,
                    trade.status, trade.kalshi_order_id, trade.notes,
                ),
            )
            self._update_daily(conn, trade.created_at[:10], spent=trade.cost_basis)
        return trade.id

    def settle(self, trade_id: str, resolution: str, settle_price: float):
        """Mark a trade as settled. resolution='yes'|'no'."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT contracts, entry_price, side FROM trades WHERE id=?",
                (trade_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Trade {trade_id} not found")

            # P&L calculation
            contracts = row["contracts"]
            entry = row["entry_price"] / 100  # convert to dollars
            side = row["side"]

            if side == "yes":
                pnl = contracts * (settle_price - entry)
            else:
                # bought NO at (1 - entry_yes_price)
                pnl = contracts * (settle_price - entry)

            conn.execute(
                """UPDATE trades SET status='settled', resolution=?,
                   settle_price=?, pnl=? WHERE id=?""",
                (resolution, settle_price, round(pnl, 4), trade_id),
            )
            date = conn.execute(
                "SELECT created_at FROM trades WHERE id=?", (trade_id,)
            ).fetchone()["created_at"][:10]
            self._update_daily(conn, date, pnl=round(pnl, 4), delta_open=-1)

    def cancel(self, trade_id: str, notes: str = ""):
        with self._connect() as conn:
            conn.execute(
                "UPDATE trades SET status='cancelled', notes=? WHERE id=?",
                (notes, trade_id),
            )

    def _update_daily(
        self, conn: sqlite3.Connection, date: str,
        spent: float = 0.0, pnl: float = 0.0, delta_open: int = 0,
    ):
        conn.execute(
            """INSERT INTO daily_summary (date, trades_placed, total_spent, total_pnl, open_positions)
               VALUES (?, 1, ?, ?, 1)
               ON CONFLICT(date) DO UPDATE SET
                 trades_placed  = trades_placed + 1,
                 total_spent    = total_spent + excluded.total_spent,
                 total_pnl      = total_pnl + ?,
                 open_positions = open_positions + ?""",
            (date, spent, 0, pnl, delta_open),
        )

    # ── Read ──────────────────────────────────────────────────────────────

    def open_trades(self, mode: str | None = None) -> list[Trade]:
        sql = "SELECT * FROM trades WHERE status='open'"
        params: list = []
        if mode:
            sql += " AND mode=?"
            params.append(mode)
        sql += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_trade(r) for r in rows]

    def all_trades(self, mode: str | None = None, limit: int = 100) -> list[Trade]:
        sql = "SELECT * FROM trades"
        params: list = []
        if mode:
            sql += " WHERE mode=?"
            params.append(mode)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_trade(r) for r in rows]

    def get_trade(self, trade_id: str) -> Trade | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        return _row_to_trade(row) if row else None

    def daily_summary(self, days: int = 7) -> list[DailySummary]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM daily_summary ORDER BY date DESC LIMIT ?", (days,)
            ).fetchall()
        return [DailySummary(**dict(r)) for r in rows]

    def total_pnl(self, mode: str | None = None) -> float:
        sql = "SELECT SUM(pnl) FROM trades WHERE status='settled'"
        params: list = []
        if mode:
            sql += " AND mode=?"
            params.append(mode)
        with self._connect() as conn:
            result = conn.execute(sql, params).fetchone()[0]
        return result or 0.0

    def today_spent(self) -> float:
        today = _now()[:10]
        with self._connect() as conn:
            row = conn.execute(
                "SELECT total_spent FROM daily_summary WHERE date=?", (today,)
            ).fetchone()
        return row["total_spent"] if row else 0.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_trade(row: sqlite3.Row) -> Trade:
    d = dict(row)
    return Trade(
        id=d["id"],
        created_at=d["created_at"],
        mode=d["mode"],
        ticker=d["ticker"],
        title=d["title"],
        side=d["side"],
        contracts=d["contracts"],
        entry_price=d["entry_price"],
        ai_probability=d.get("ai_probability") or 0.0,
        edge=d.get("edge") or 0.0,
        confidence=d.get("confidence") or "low",
        status=d["status"],
        kalshi_order_id=d.get("kalshi_order_id") or "",
        resolution=d.get("resolution"),
        settle_price=d.get("settle_price"),
        pnl=d.get("pnl"),
        notes=d.get("notes") or "",
    )
