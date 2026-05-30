"""
Phase 2: Fraud Simulator
Sends ~50 mixed transactions across users u1-u5, builds baselines first,
then sends medium and high-risk transactions.
"""

import requests
import json
import time
from datetime import datetime, timezone, timedelta

BASE = "http://localhost:8000"
HEADERS = {"X-API-Key": "sentinel-dev-key", "Content-Type": "application/json"}
EPOCH = 1780085997

results = []
surprises = []
frozen_users = set()

def ts(hours_ago=0, minutes_ago=0):
    """Generate ISO-8601 timestamp."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago, minutes=minutes_ago)
    return dt.isoformat()

def analyze(txn_id, user_id, amount, merchant, location, timestamp, intended):
    """POST /analyze and return result."""
    payload = {
        "id": txn_id,
        "user_id": user_id,
        "amount": amount,
        "merchant": merchant,
        "location": location,
        "timestamp": timestamp
    }
    try:
        r = requests.post(f"{BASE}/analyze", json=payload, headers=HEADERS, timeout=15)
        if r.status_code == 423:
            return {"error": "account_frozen", "user_id": user_id, "id": txn_id, "intended": intended}
        if r.status_code != 200:
            return {"error": f"http_{r.status_code}", "user_id": user_id, "id": txn_id, "intended": intended}
        data = r.json()
        risk = data.get("risk_level", "UNKNOWN")
        explanation = data.get("explanation", "")
        action = data.get("action_taken", "")

        if action == "account_frozen":
            frozen_users.add(user_id)

        entry = {
            "id": txn_id,
            "user_id": user_id,
            "amount": amount,
            "merchant": merchant,
            "location": location,
            "intended": intended,
            "got": risk,
            "action_taken": action,
            "explanation": explanation,
        }
        results.append(entry)

        # Check for surprises
        if intended != risk:
            surprises.append({
                "id": txn_id,
                "user_id": user_id,
                "amount": amount,
                "merchant": merchant,
                "intended": intended,
                "got": risk,
                "explanation": explanation
            })

        return entry
    except Exception as e:
        return {"error": str(e), "id": txn_id, "intended": intended}

def unfreeze(user_id):
    """Unfreeze a user account."""
    r = requests.post(f"{BASE}/unfreeze/{user_id}", headers=HEADERS, timeout=10)
    if user_id in frozen_users:
        frozen_users.discard(user_id)
    return r.status_code

# ─── PHASE 1: Build baselines (4-6 small txns per user, spread over time) ───────
# Using distinct timestamp offsets to avoid velocity trigger (>= 5 txns in 5 min)
print("=== Building baselines ===")
n = 1

# u1 baseline: coffee shop, grocery, transit (amounts $8-$45)
for merchant, amount, hrs in [
    ("Starbucks", 8.50, 23), ("Whole Foods", 42.00, 22),
    ("Uber", 14.00, 20), ("Starbucks", 7.25, 18),
    ("CVS Pharmacy", 23.50, 16)
]:
    txid = f"tx-sim-{EPOCH}-{n}"; n += 1
    r = analyze(txid, "u1", amount, merchant, "San Francisco, CA", ts(hours_ago=hrs), "LOW")
    print(f"  {txid} u1 ${amount} {merchant} -> {r.get('got','ERR')}")
    time.sleep(0.3)

# u2 baseline
for merchant, amount, hrs in [
    ("Starbucks", 5.75, 23), ("Trader Joe's", 38.00, 21),
    ("Metro Transit", 3.50, 19), ("McDonald's", 12.00, 17),
    ("Walgreens", 19.00, 15)
]:
    txid = f"tx-sim-{EPOCH}-{n}"; n += 1
    r = analyze(txid, "u2", amount, merchant, "Chicago, IL", ts(hours_ago=hrs), "LOW")
    print(f"  {txid} u2 ${amount} {merchant} -> {r.get('got','ERR')}")
    time.sleep(0.3)

# u3 baseline
for merchant, amount, hrs in [
    ("Dunkin Donuts", 6.00, 23), ("Safeway", 55.00, 21),
    ("Lyft", 18.00, 19), ("Starbucks", 9.50, 17),
    ("CVS Pharmacy", 28.00, 14)
]:
    txid = f"tx-sim-{EPOCH}-{n}"; n += 1
    r = analyze(txid, "u3", amount, merchant, "Seattle, WA", ts(hours_ago=hrs), "LOW")
    print(f"  {txid} u3 ${amount} {merchant} -> {r.get('got','ERR')}")
    time.sleep(0.3)

# u4 baseline
for merchant, amount, hrs in [
    ("Starbucks", 7.00, 22), ("Kroger", 62.00, 20),
    ("Uber", 22.00, 18), ("Starbucks", 6.50, 16),
    ("Rite Aid", 15.00, 13)
]:
    txid = f"tx-sim-{EPOCH}-{n}"; n += 1
    r = analyze(txid, "u4", amount, merchant, "Austin, TX", ts(hours_ago=hrs), "LOW")
    print(f"  {txid} u4 ${amount} {merchant} -> {r.get('got','ERR')}")
    time.sleep(0.3)

# u5 baseline
for merchant, amount, hrs in [
    ("Peet's Coffee", 8.00, 23), ("Whole Foods", 47.00, 21),
    ("Uber", 11.00, 19), ("Starbucks", 6.75, 17),
    ("Target", 35.00, 14)
]:
    txid = f"tx-sim-{EPOCH}-{n}"; n += 1
    r = analyze(txid, "u5", amount, merchant, "Boston, MA", ts(hours_ago=hrs), "LOW")
    print(f"  {txid} u5 ${amount} {merchant} -> {r.get('got','ERR')}")
    time.sleep(0.3)

print(f"Baseline phase done. n={n-1} transactions sent so far.")

# ─── PHASE 2: Additional LOW transactions ─────────────────────────────────────
print("\n=== Sending LOW batch ===")
low_batch = [
    ("u1", 12.50, "Starbucks", "San Francisco, CA", 12),
    ("u2", 6.25, "Starbucks", "Chicago, IL", 11),
    ("u3", 31.00, "Safeway", "Seattle, WA", 10),
    ("u4", 9.00, "Dunkin Donuts", "Austin, TX", 9),
    ("u5", 14.50, "Lyft", "Boston, MA", 8),
    ("u1", 28.00, "Whole Foods", "San Francisco, CA", 7),
    ("u2", 17.50, "Uber", "Chicago, IL", 6),
    ("u3", 8.25, "Starbucks", "Seattle, WA", 5),
    ("u4", 44.00, "Trader Joe's", "Austin, TX", 4),
    ("u5", 22.00, "CVS Pharmacy", "Boston, MA", 3),
]
for uid, amt, merch, loc, hrs in low_batch:
    txid = f"tx-sim-{EPOCH}-{n}"; n += 1
    r = analyze(txid, uid, amt, merch, loc, ts(hours_ago=hrs), "LOW")
    print(f"  {txid} {uid} ${amt} {merch} -> {r.get('got','ERR')}")
    time.sleep(0.3)

# ─── PHASE 3: MEDIUM transactions (3-8x baseline) ─────────────────────────────
print("\n=== Sending MEDIUM batch ===")
# u1 avg ~19 -> 3x = $57, 8x = $152
# u2 avg ~15.5 -> 3x = $46, 8x = $124
# u3 avg ~23 -> 3x = $69, 8x = $184
# u4 avg ~22.5 -> 3x = $67, 8x = $180
# u5 avg ~21.5 -> 3x = $64, 8x = $172
# Use amounts well within 3-8x range and below $5000, below 30x threshold
medium_batch = [
    ("u1", 180.00, "Best Buy", "San Francisco, CA", 2, 30),
    ("u2", 250.00, "Apple Store", "Chicago, IL", 2, 15),
    ("u3", 320.00, "Delta Airlines", "Seattle, WA", 1, 45),
    ("u4", 195.00, "Best Buy", "Austin, TX", 1, 30),
    ("u5", 275.00, "United Airlines", "Boston, MA", 1, 15),
    ("u1", 140.00, "Nordstrom", "San Francisco, CA", 0, 45),
    ("u2", 220.00, "REI", "Chicago, IL", 0, 30),
    ("u3", 380.00, "Home Depot", "Seattle, WA", 0, 15),
    ("u4", 160.00, "Costco", "Austin, TX", 0, 10),
    ("u5", 310.00, "Samsung Store", "Boston, MA", 0, 5),
]
for uid, amt, merch, loc, hrs, mins in medium_batch:
    txid = f"tx-sim-{EPOCH}-{n}"; n += 1
    r = analyze(txid, uid, amt, merch, loc, ts(hours_ago=hrs, minutes_ago=mins), "MEDIUM")
    print(f"  {txid} {uid} ${amt} {merch} -> {r.get('got','ERR')}")
    time.sleep(0.3)

# ─── PHASE 4: HIGH transactions ────────────────────────────────────────────────
print("\n=== Sending HIGH batch ===")

# HIGH-1: u1, large amount >= $5000
txid = f"tx-sim-{EPOCH}-{n}"; n += 1
r = analyze(txid, "u1", 7500.00, "Unknown Wire Transfer", "Lagos, Nigeria",
            ts(hours_ago=2, minutes_ago=30), "HIGH")
print(f"  {txid} u1 $7500 Unknown Wire Transfer -> {r.get('got','ERR')}")
time.sleep(0.3)

# Unfreeze u1 so we can continue
if "u1" in frozen_users:
    unfreeze("u1")
    print("  Unfreezing u1")
    time.sleep(0.3)

# HIGH-2: u2, crypto exchange large amount
txid = f"tx-sim-{EPOCH}-{n}"; n += 1
r = analyze(txid, "u2", 12000.00, "Crypto Exchange XYZ", "Pyongyang, North Korea",
            ts(hours_ago=3, minutes_ago=15), "HIGH")
print(f"  {txid} u2 $12000 Crypto Exchange -> {r.get('got','ERR')}")
time.sleep(0.3)

if "u2" in frozen_users:
    unfreeze("u2")
    print("  Unfreezing u2")
    time.sleep(0.3)

# HIGH-3: u3, midnight wire transfer >= $5000
txid = f"tx-sim-{EPOCH}-{n}"; n += 1
r = analyze(txid, "u3", 8900.00, "Offshore Wire Transfer", "Accra, Ghana",
            ts(hours_ago=26), "HIGH")  # ~2am local
print(f"  {txid} u3 $8900 Offshore Wire -> {r.get('got','ERR')}")
time.sleep(0.3)

if "u3" in frozen_users:
    unfreeze("u3")
    print("  Unfreezing u3")
    time.sleep(0.3)

# HIGH-4: u4, ratio-based HIGH (>= 30x baseline ~$22.5, need > $675)
# With dilution from medium batch, let's use $6000 (above $5000 threshold)
txid = f"tx-sim-{EPOCH}-{n}"; n += 1
r = analyze(txid, "u4", 6500.00, "Bitcoin ATM", "Moscow, Russia",
            ts(hours_ago=4, minutes_ago=0), "HIGH")
print(f"  {txid} u4 $6500 Bitcoin ATM -> {r.get('got','ERR')}")
time.sleep(0.3)

if "u4" in frozen_users:
    unfreeze("u4")
    print("  Unfreezing u4")
    time.sleep(0.3)

# HIGH-5: u5, foreign location + large amount
txid = f"tx-sim-{EPOCH}-{n}"; n += 1
r = analyze(txid, "u5", 15000.00, "Luxury Goods International", "Dubai, UAE",
            ts(hours_ago=3, minutes_ago=45), "HIGH")
print(f"  {txid} u5 $15000 Luxury Goods International -> {r.get('got','ERR')}")
time.sleep(0.3)

if "u5" in frozen_users:
    unfreeze("u5")
    print("  Unfreezing u5")
    time.sleep(0.3)

# ─── PHASE 5: Final count and summary ─────────────────────────────────────────
print(f"\n=== Done. Total transactions sent: {len(results)} ===")
print(f"Frozen users at some point: {frozen_users}")

# Tally
counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "UNKNOWN": 0}
for r in results:
    lvl = r.get("got", "UNKNOWN")
    counts[lvl] = counts.get(lvl, 0) + 1

print(f"Classified: {counts}")
print(f"Surprises: {len(surprises)}")
for s in surprises:
    print(f"  SURPRISE: {s['id']} intended={s['intended']} got={s['got']} amount=${s['amount']} merchant={s['merchant']}")
    print(f"    explanation: {s['explanation'][:120]}")

# Intended mix
intended_counts = {"low": 0, "medium": 0, "high": 0}
for r in results:
    i = r.get("intended", "LOW").lower()
    intended_counts[i] = intended_counts.get(i, 0) + 1

print(f"\nIntended: {intended_counts}")

# Save all results
output = {
    "results": results,
    "surprises": surprises,
    "counts": counts,
    "intended_counts": intended_counts,
    "frozen_users": list(frozen_users),
    "total": len(results),
    "n_sent": n - 1
}
with open("/Users/rahulmeena/VIKRAM PROJECT/reports/mission-20260530-014659/sim_raw.json", "w") as f:
    json.dump(output, f, indent=2)

print("\nRaw results saved to sim_raw.json")
