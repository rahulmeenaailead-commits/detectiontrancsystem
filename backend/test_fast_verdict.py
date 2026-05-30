"""Regression test for the 'pending' dashboard bug.

The /analyze path used to block ~30-42s on a live Bright Data SERP lookup
(+ DeepSeek LLM) while the transaction row sat in the DB with a NULL verdict,
which the 3s dashboard poll rendered as 'pending'. The fix gives an immediate
deterministic verdict via analyze_transaction_fast (no network, no LLM) and
defers the slow enrichment to a background task.

This test asserts the fast path is both correct and fast.
"""

import time

from agent import analyze_transaction_fast
from brightdata import lookup_merchant_cached
from models import Transaction


def _tx(amount: float, merchant: str) -> Transaction:
    return Transaction(
        id=f"test-fast-{time.time_ns()}",
        user_id=f"test-fast-user-{time.time_ns()}",
        amount=amount,
        location="Caracas, Venezuela",
        timestamp="2026-05-30T12:00:00",
        merchant=merchant,
    )


def test_cached_lookup_never_blocks_on_network():
    """An uncached, made-up merchant must return instantly (no live SERP)."""
    t0 = time.time()
    rep = lookup_merchant_cached("Totally Uncached Merchant XYZ 9999")
    dt = time.time() - t0
    assert dt < 1.0, f"cached lookup took {dt:.2f}s — it made a network call"
    assert rep.mode in ("unknown", "disabled")
    assert rep.score is None


def test_fast_verdict_is_immediate_and_non_null():
    """Fast verdict must be sub-second and never None for an uncached merchant."""
    t0 = time.time()
    result = analyze_transaction_fast(_tx(11802.0, "Anonymous P2P 12345"))
    dt = time.time() - t0
    assert dt < 1.0, f"fast verdict took {dt:.2f}s — too slow for the request path"
    assert result["risk_level"] in ("LOW", "MEDIUM", "HIGH")
    assert result["fraud_score"] is not None


def test_large_amount_is_high_and_frozen_immediately():
    """A $11,802 transaction is HIGH by the deterministic floor, no LLM needed."""
    result = analyze_transaction_fast(_tx(11802.0, "Crypto Exchange XYZ 777"))
    assert result["risk_level"] == "HIGH"
    assert result["action_taken"] == "account_frozen"


if __name__ == "__main__":
    test_cached_lookup_never_blocks_on_network()
    test_fast_verdict_is_immediate_and_non_null()
    test_large_amount_is_high_and_frozen_immediately()
    print("All fast-verdict tests passed.")
