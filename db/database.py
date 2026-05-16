"""
TANEKOU BOT PO — Base de données SQLite
Stockage local : trades, statistiques, sessions
"""
import sqlite3
import os
from datetime import datetime, date


DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tanekou.db")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Crée les tables si elles n'existent pas."""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id        TEXT UNIQUE,
                pair            TEXT NOT NULL,
                direction       TEXT NOT NULL,   -- 'call' | 'put'
                amount          REAL NOT NULL,
                payout          REAL,
                result          TEXT,            -- 'win' | 'loss' | 'pending'
                profit          REAL DEFAULT 0,
                martingale_level INTEGER DEFAULT 0,
                signal_score    INTEGER,
                signal_type     TEXT,
                is_demo         INTEGER NOT NULL,
                opened_at       TEXT NOT NULL,
                closed_at       TEXT,
                expiration_sec  INTEGER
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at      TEXT NOT NULL,
                ended_at        TEXT,
                is_demo         INTEGER NOT NULL,
                total_trades    INTEGER DEFAULT 0,
                wins            INTEGER DEFAULT 0,
                losses          INTEGER DEFAULT 0,
                net_profit      REAL DEFAULT 0,
                starting_balance REAL
            );

            CREATE TABLE IF NOT EXISTS daily_stats (
                stat_date       TEXT PRIMARY KEY,
                is_demo         INTEGER NOT NULL,
                total_trades    INTEGER DEFAULT 0,
                wins            INTEGER DEFAULT 0,
                losses          INTEGER DEFAULT 0,
                net_profit      REAL DEFAULT 0,
                max_consecutive_losses INTEGER DEFAULT 0,
                starting_balance REAL
            );
        """)


# ── TRADES ────────────────────────────────────────────────────────────────────

def insert_trade(
    trade_id: str,
    pair: str,
    direction: str,
    amount: float,
    martingale_level: int,
    signal_score: int,
    signal_type: str,
    is_demo: bool,
    expiration_sec: int,
) -> int:
    with _get_conn() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO trades
               (trade_id, pair, direction, amount, martingale_level,
                signal_score, signal_type, is_demo, opened_at, result, expiration_sec)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                trade_id, pair, direction, amount, martingale_level,
                signal_score, signal_type, int(is_demo),
                datetime.utcnow().isoformat(), "pending", expiration_sec,
            ),
        )
        return cur.lastrowid


def update_trade_result(trade_id: str, result: str, profit: float, payout: float) -> None:
    with _get_conn() as conn:
        conn.execute(
            """UPDATE trades
               SET result=?, profit=?, payout=?, closed_at=?
               WHERE trade_id=?""",
            (result, profit, payout, datetime.utcnow().isoformat(), trade_id),
        )


# ── STATISTIQUES ─────────────────────────────────────────────────────────────

def get_today_stats(is_demo: bool) -> dict:
    today = date.today().isoformat()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM daily_stats WHERE stat_date=? AND is_demo=?",
            (today, int(is_demo)),
        ).fetchone()
    if row is None:
        return {
            "total_trades": 0, "wins": 0, "losses": 0,
            "net_profit": 0.0, "winrate": 0.0,
            "max_consecutive_losses": 0,
        }
    d = dict(row)
    d["winrate"] = round(d["wins"] / d["total_trades"] * 100, 1) if d["total_trades"] else 0.0
    return d


def record_trade_result(result: str, profit: float, is_demo: bool) -> None:
    """Met à jour les stats journalières après chaque trade."""
    today = date.today().isoformat()
    with _get_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM daily_stats WHERE stat_date=? AND is_demo=?",
            (today, int(is_demo)),
        ).fetchone()

        if existing is None:
            conn.execute(
                """INSERT INTO daily_stats
                   (stat_date, is_demo, total_trades, wins, losses, net_profit)
                   VALUES (?,?,?,?,?,?)""",
                (
                    today, int(is_demo), 1,
                    1 if result == "win" else 0,
                    1 if result == "loss" else 0,
                    profit,
                ),
            )
        else:
            conn.execute(
                """UPDATE daily_stats
                   SET total_trades = total_trades + 1,
                       wins = wins + ?,
                       losses = losses + ?,
                       net_profit = net_profit + ?
                   WHERE stat_date=? AND is_demo=?""",
                (
                    1 if result == "win" else 0,
                    1 if result == "loss" else 0,
                    profit, today, int(is_demo),
                ),
            )


def get_last_trades(is_demo: bool, limit: int = 10) -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM trades
               WHERE is_demo=?
               ORDER BY opened_at DESC LIMIT ?""",
            (int(is_demo), limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_global_stats(is_demo: bool) -> dict:
    with _get_conn() as conn:
        row = conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses,
                SUM(profit) as net_profit,
                MAX(profit) as best_trade,
                MIN(profit) as worst_trade
               FROM trades WHERE is_demo=? AND result != 'pending'""",
            (int(is_demo),),
        ).fetchone()
    if row is None:
        return {}
    d = dict(row)
    d["winrate"] = round(d["wins"] / d["total"] * 100, 1) if d["total"] else 0.0
    return d
