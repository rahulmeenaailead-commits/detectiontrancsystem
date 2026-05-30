from unittest.mock import patch

from dotenv import load_dotenv

load_dotenv()

from models import MerchantReputation, Transaction
from database import conn, cursor
from agent import analyze_transaction


def seed():
    cursor.execute(
        "INSERT OR REPLACE INTO users (id, name, account_frozen) VALUES (?, ?, 0)",
        ("u1", "Alice"),
    )
    for i in range(5):
        cursor.execute(
            "INSERT INTO transactions (id, user_id, amount, location, timestamp, merchant) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                f"t{i}",
                "u1",
                50.0 + i,
                "NYC",
                f"2026-05-{10 + i:02d}T12:00:00",
                "Coffee Shop",
            ),
        )
    conn.commit()


def run():
    seed()
    suspicious = Transaction(
        id="t999",
        user_id="u1",
        amount=9000.0,
        location="Lagos, Nigeria",
        timestamp="2026-05-19T03:14:00",
        merchant="Unknown Wire Transfer",
    )
    result = analyze_transaction(suspicious)
    print("Agent result:", result)

    cursor.execute("SELECT account_frozen FROM users WHERE id = ?", ("u1",))
    frozen = bool(cursor.fetchone()[0])
    print(f"User u1 account_frozen: {frozen}")

    assert result["risk_level"] == "HIGH", f"Expected HIGH, got {result['risk_level']}"
    assert frozen, "User account should be frozen on HIGH risk"
    print("PASS")


def _fake_rep(score, mode="scored"):
    return MerchantReputation(merchant="X", score=score, mode=mode)


def test_low_reputation_bumps_low_to_medium():
    cursor.execute(
        "INSERT OR REPLACE INTO users (id, name, account_frozen) VALUES (?,?,0)",
        ("u2", "Bob"),
    )
    conn.commit()
    txn = Transaction(id="rep-low", user_id="u2", amount=50.0, location="NYC",
                      timestamp="2026-05-28T12:00:00", merchant="ShadyVendor")
    with patch("agent.lookup_merchant", return_value=_fake_rep(20)), \
         patch("agent._use_mock", True):
        result = analyze_transaction(txn)
    assert result["risk_level"] in ("MEDIUM", "HIGH")
    assert result["web_rep_score"] == 20


def test_high_reputation_keeps_low():
    cursor.execute(
        "INSERT OR REPLACE INTO users (id, name, account_frozen) VALUES (?,?,0)",
        ("u3", "Carol"),
    )
    conn.commit()
    txn = Transaction(id="rep-hi", user_id="u3", amount=50.0, location="NYC",
                      timestamp="2026-05-28T12:00:00", merchant="Starbucks")
    with patch("agent.lookup_merchant", return_value=_fake_rep(85)), \
         patch("agent._use_mock", True):
        result = analyze_transaction(txn)
    assert result["risk_level"] == "LOW"
    assert result["web_rep_score"] == 85


def test_reputation_disabled_does_not_break_flow():
    cursor.execute(
        "INSERT OR REPLACE INTO users (id, name, account_frozen) VALUES (?,?,0)",
        ("u4", "Dan"),
    )
    conn.commit()
    txn = Transaction(id="rep-off", user_id="u4", amount=50.0, location="NYC",
                      timestamp="2026-05-28T12:00:00", merchant="Anywhere")
    with patch("agent.lookup_merchant", return_value=_fake_rep(None, mode="disabled")), \
         patch("agent._use_mock", True):
        result = analyze_transaction(txn)
    assert result["risk_level"] == "LOW"
    assert result["web_rep_mode"] == "disabled"


if __name__ == "__main__":
    run()
