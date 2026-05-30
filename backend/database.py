import json
import os
import sqlite3
import threading

DB_PATH = os.getenv("SENTINEL_DB_PATH", "sentinel.db")

_lock = threading.Lock()
conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
conn.execute("PRAGMA busy_timeout=5000")
cursor = conn.cursor()

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        amount REAL,
        location TEXT,
        timestamp TEXT,
        merchant TEXT,
        fraud_score REAL,
        risk_level TEXT,
        explanation TEXT,
        account_frozen INTEGER DEFAULT 0,
        action_taken TEXT,
        web_rep_score INTEGER,
        web_rep_signals TEXT,
        web_rep_cached INTEGER
    )
    """
)
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        name TEXT,
        account_frozen INTEGER DEFAULT 0
    )
    """
)
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS merchant_reputation (
        merchant TEXT PRIMARY KEY,
        score INTEGER,
        mode TEXT NOT NULL,
        signals TEXT NOT NULL,
        top_results TEXT NOT NULL,
        fetched_at TIMESTAMP NOT NULL
    )
    """
)
cursor.execute(
    "CREATE INDEX IF NOT EXISTS idx_tx_user_ts ON transactions(user_id, timestamp DESC)"
)

# Additive migration: pre-existing sentinel.db files won't have the web_rep
# columns from the CREATE TABLE above (CREATE IF NOT EXISTS is a no-op on an
# existing table). Add them in place so reads/writes never hit "no such column".
_tx_cols = {row[1] for row in cursor.execute("PRAGMA table_info(transactions)").fetchall()}
for _col, _type in (
    ("web_rep_score", "INTEGER"),
    ("web_rep_signals", "TEXT"),
    ("web_rep_cached", "INTEGER"),
):
    if _col not in _tx_cols:
        cursor.execute(f"ALTER TABLE transactions ADD COLUMN {_col} {_type}")


def get_user_average(user_id: str) -> float:
    with _lock:
        cursor.execute(
            """
            SELECT AVG(amount) FROM (
                SELECT amount FROM transactions
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT 10
            )
            """,
            (user_id,),
        )
        row = cursor.fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0


def get_recent_transactions(user_id: str, limit: int = 10) -> list[dict]:
    with _lock:
        cursor.execute(
            "SELECT amount, location, timestamp, merchant FROM transactions "
            "WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit),
        )
        rows = cursor.fetchall()
    return [dict(r) for r in rows]


def count_recent_transactions(user_id: str, since_iso: str) -> int:
    with _lock:
        cursor.execute(
            "SELECT COUNT(*) FROM transactions WHERE user_id = ? AND timestamp >= ?",
            (user_id, since_iso),
        )
        row = cursor.fetchone()
    return int(row[0]) if row else 0


def sum_recent_transactions(user_id: str, since_iso: str) -> float:
    with _lock:
        cursor.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions "
            "WHERE user_id = ? AND timestamp >= ?",
            (user_id, since_iso),
        )
        row = cursor.fetchone()
    return float(row[0]) if row else 0.0


def get_last_transaction(user_id: str) -> dict | None:
    with _lock:
        cursor.execute(
            "SELECT location, timestamp FROM transactions WHERE user_id = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (user_id,),
        )
        row = cursor.fetchone()
    return dict(row) if row else None


def freeze_user(user_id: str) -> None:
    with _lock:
        cursor.execute(
            "INSERT OR IGNORE INTO users (id, name, account_frozen) VALUES (?, ?, 1)",
            (user_id, user_id),
        )
        cursor.execute("UPDATE users SET account_frozen = 1 WHERE id = ?", (user_id,))


def unfreeze_user(user_id: str) -> bool:
    with _lock:
        cursor.execute("SELECT account_frozen FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return False
        cursor.execute("UPDATE users SET account_frozen = 0 WHERE id = ?", (user_id,))
        cursor.execute(
            "UPDATE transactions SET account_frozen = 0, action_taken = 'unfrozen' "
            "WHERE user_id = ? AND account_frozen = 1",
            (user_id,),
        )
    return True


def is_user_frozen(user_id: str) -> bool:
    with _lock:
        cursor.execute("SELECT account_frozen FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
    return bool(row and row[0])


def list_transactions() -> list[dict]:
    with _lock:
        cursor.execute(
            "SELECT id, user_id, amount, location, timestamp, merchant, "
            "fraud_score, risk_level, explanation, account_frozen, action_taken, "
            "web_rep_score, web_rep_signals, web_rep_cached "
            "FROM transactions ORDER BY timestamp DESC"
        )
        rows = cursor.fetchall()
    return [
        {
            "id": r["id"],
            "user_id": r["user_id"],
            "amount": r["amount"],
            "location": r["location"],
            "timestamp": r["timestamp"],
            "merchant": r["merchant"],
            "fraud_score": r["fraud_score"],
            "risk_level": r["risk_level"],
            "explanation": r["explanation"],
            "account_frozen": bool(r["account_frozen"]),
            "action_taken": r["action_taken"],
            "web_rep_score": r["web_rep_score"],
            "web_rep_top_signals": json.loads(r["web_rep_signals"]) if r["web_rep_signals"] else [],
            "web_rep_cached": bool(r["web_rep_cached"]) if r["web_rep_cached"] is not None else None,
        }
        for r in rows
    ]


def get_transaction_merchant(tx_id: str) -> str | None:
    with _lock:
        cursor.execute("SELECT merchant FROM transactions WHERE id = ?", (tx_id,))
        row = cursor.fetchone()
    return row["merchant"] if row else None


def get_merchant_reputation(merchant: str) -> dict | None:
    with _lock:
        cursor.execute(
            "SELECT score, mode, signals, top_results, fetched_at "
            "FROM merchant_reputation WHERE merchant = ?",
            (merchant,),
        )
        row = cursor.fetchone()
    if not row:
        return None
    return {
        "merchant": merchant,
        "score": row["score"],
        "mode": row["mode"],
        "signals": json.loads(row["signals"]),
        "top_results": json.loads(row["top_results"]),
        "fetched_at": row["fetched_at"],
    }


def insert_transaction(tx) -> None:
    with _lock:
        cursor.execute(
            "INSERT INTO transactions (id, user_id, amount, location, timestamp, merchant) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tx.id, tx.user_id, tx.amount, tx.location, tx.timestamp, tx.merchant),
        )


def update_transaction_verdict(
    tx_id: str,
    fraud_score: float,
    risk_level: str,
    explanation: str,
    account_frozen: int,
    action_taken: str,
    web_rep_score: int | None = None,
    web_rep_signals: list[str] | None = None,
    web_rep_cached: bool | None = None,
) -> None:
    with _lock:
        cursor.execute(
            "UPDATE transactions SET fraud_score = ?, risk_level = ?, explanation = ?, "
            "account_frozen = ?, action_taken = ?, "
            "web_rep_score = ?, web_rep_signals = ?, web_rep_cached = ? WHERE id = ?",
            (
                fraud_score, risk_level, explanation, account_frozen, action_taken,
                web_rep_score,
                json.dumps(web_rep_signals) if web_rep_signals is not None else None,
                (1 if web_rep_cached else 0) if web_rep_cached is not None else None,
                tx_id,
            ),
        )
