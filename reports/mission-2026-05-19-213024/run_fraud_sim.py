#!/usr/bin/env python3
"""Fraud simulator: sends mixed batch and collects results."""
import urllib.request
import urllib.error
import json
import time

BASE = "http://localhost:8000"
EPOCH = 1779206694

def post_analyze(payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE}/analyze",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e), "risk_level": "ERROR"}

def get_transactions():
    req = urllib.request.Request(f"{BASE}/transactions", method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())

results = []
n = 300  # offset from baseline

# === LOW RISK: 35 txns (70%) ===
low_txns = [
    ("u1", 12, "Starbucks", "New York, NY", "2026-05-19T08:15:00Z"),
    ("u2", 18, "Whole Foods", "Chicago, IL", "2026-05-19T09:22:00Z"),
    ("u3", 25, "Uber", "Austin, TX", "2026-05-19T10:05:00Z"),
    ("u4", 8, "CVS Pharmacy", "Seattle, WA", "2026-05-19T11:30:00Z"),
    ("u5", 42, "Trader Joe's", "Boston, MA", "2026-05-19T12:00:00Z"),
    ("u1", 15, "Dunkin Donuts", "New York, NY", "2026-05-19T07:45:00Z"),
    ("u2", 55, "Target", "Chicago, IL", "2026-05-19T14:10:00Z"),
    ("u3", 30, "McDonald's", "Austin, TX", "2026-05-19T13:20:00Z"),
    ("u4", 22, "Metro Transit", "Seattle, WA", "2026-05-19T08:05:00Z"),
    ("u5", 18, "Walgreens", "Boston, MA", "2026-05-19T15:40:00Z"),
    ("u1", 45, "Subway", "New York, NY", "2026-05-19T12:55:00Z"),
    ("u2", 10, "7-Eleven", "Chicago, IL", "2026-05-19T06:30:00Z"),
    ("u3", 65, "Costco", "Austin, TX", "2026-05-19T16:00:00Z"),
    ("u4", 35, "Lyft", "Seattle, WA", "2026-05-19T17:25:00Z"),
    ("u5", 28, "Panera Bread", "Boston, MA", "2026-05-19T09:00:00Z"),
    ("u1", 9, "Netflix", "New York, NY", "2026-05-19T20:00:00Z"),
    ("u2", 72, "Safeway", "Chicago, IL", "2026-05-19T18:30:00Z"),
    ("u3", 14, "Chipotle", "Austin, TX", "2026-05-19T13:00:00Z"),
    ("u4", 60, "Grocery Outlet", "Seattle, WA", "2026-05-19T10:45:00Z"),
    ("u5", 33, "Shell Gas", "Boston, MA", "2026-05-19T07:10:00Z"),
    ("u1", 19, "Peet's Coffee", "New York, NY", "2026-05-19T08:00:00Z"),
    ("u2", 40, "H&M", "Chicago, IL", "2026-05-19T15:00:00Z"),
    ("u3", 75, "Whole Foods", "Austin, TX", "2026-05-19T11:00:00Z"),
    ("u4", 28, "Domino's Pizza", "Seattle, WA", "2026-05-19T19:30:00Z"),
    ("u5", 16, "Starbucks", "Boston, MA", "2026-05-19T08:20:00Z"),
    ("u1", 50, "Uber Eats", "New York, NY", "2026-05-19T21:00:00Z"),
    ("u2", 22, "CVS Pharmacy", "Chicago, IL", "2026-05-19T16:45:00Z"),
    ("u3", 38, "Spotify", "Austin, TX", "2026-05-19T22:01:00Z"),
    ("u4", 12, "Starbucks", "Seattle, WA", "2026-05-19T07:30:00Z"),
    ("u5", 48, "Kroger", "Boston, MA", "2026-05-19T14:20:00Z"),
    ("u1", 25, "Chase ATM", "New York, NY", "2026-05-19T10:10:00Z"),
    ("u2", 80, "Best Buy Accessories", "Chicago, IL", "2026-05-19T13:50:00Z"),
    ("u3", 20, "Subway", "Austin, TX", "2026-05-19T12:40:00Z"),
    ("u4", 55, "Cheesecake Factory", "Seattle, WA", "2026-05-19T19:00:00Z"),
    ("u5", 70, "TJ Maxx", "Boston, MA", "2026-05-19T15:15:00Z"),
]

# === MEDIUM RISK: 10 txns (20%) — 3-8x baseline avg of ~$22 => $66-$176 ===
medium_txns = [
    ("u1", 320, "Apple Store", "New York, NY", "2026-05-19T14:00:00Z"),
    ("u2", 280, "Delta Airlines", "Chicago, IL", "2026-05-19T10:30:00Z"),
    ("u3", 450, "Best Buy", "Austin, TX", "2026-05-19T16:30:00Z"),
    ("u4", 390, "United Airlines", "Seattle, WA", "2026-05-19T09:15:00Z"),
    ("u5", 220, "Hotel Marriott", "Boston, MA", "2026-05-19T11:45:00Z"),
    ("u1", 550, "Samsung Store", "New York, NY", "2026-05-19T15:20:00Z"),
    ("u2", 175, "REI Outdoor", "Chicago, IL", "2026-05-19T13:00:00Z"),
    ("u3", 340, "Nordstrom", "Austin, TX", "2026-05-19T17:00:00Z"),
    ("u4", 480, "Southwest Airlines", "Seattle, WA", "2026-05-19T12:10:00Z"),
    ("u5", 260, "Hilton Hotels", "Boston, MA", "2026-05-19T08:50:00Z"),
]

# === HIGH RISK: 5 txns (10%) — >=5000 or unusual merchant/foreign locale ===
high_txns = [
    ("u1", 9500, "Unknown Wire Transfer", "Lagos, Nigeria", "2026-05-19T03:15:00Z"),
    ("u2", 7200, "Crypto Exchange XYZ", "Pyongyang, North Korea", "2026-05-19T02:30:00Z"),
    ("u3", 6000, "Western Union Wire", "Moscow, Russia", "2026-05-19T04:45:00Z"),
    ("u4", 12000, "Anonymous Offshore Transfer", "Cayman Islands", "2026-05-19T02:10:00Z"),
    ("u5", 8500, "Binance Crypto Purchase", "Dubai, UAE", "2026-05-19T03:55:00Z"),
]

all_intended = (
    [(row, "LOW") for row in low_txns] +
    [(row, "MEDIUM") for row in medium_txns] +
    [(row, "HIGH") for row in high_txns]
)

print(f"Sending {len(all_intended)} transactions...")
print(f"Intended: LOW={len(low_txns)}, MEDIUM={len(medium_txns)}, HIGH={len(high_txns)}")
print()

for (uid, amt, merch, loc, ts), intended in all_intended:
    n += 1
    txn_id = f"tx-sim-{EPOCH}-{n}"
    payload = {
        "id": txn_id,
        "user_id": uid,
        "amount": amt,
        "location": loc,
        "timestamp": ts,
        "merchant": merch
    }
    resp = post_analyze(payload)
    rl = resp.get("risk_level", "ERROR")
    exp = resp.get("explanation", "")[:120]
    frozen = resp.get("account_frozen", False)
    results.append({
        "id": txn_id,
        "user_id": uid,
        "amount": amt,
        "merchant": merch,
        "intended": intended,
        "got": rl,
        "frozen": frozen,
        "explanation": exp,
        "surprise": intended != rl
    })
    flag = " <<SURPRISE>>" if intended != rl else ""
    print(f"{intended}->{rl}{flag} | {txn_id} | {uid} | ${amt} | {merch} | frozen={frozen}")

print()
print("=== TALLY ===")
classified = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "ERROR": 0}
for r in results:
    classified[r["got"]] = classified.get(r["got"], 0) + 1

print(f"Classified: {classified}")

frozen_users = list(set(r["user_id"] for r in results if r["frozen"]))
print(f"Frozen users from sim batch: {frozen_users}")

surprises = [r for r in results if r["surprise"]]
print(f"\nSurprises ({len(surprises)}):")
for s in surprises:
    print(f"  {s['intended']}->got {s['got']} | {s['id']} | ${s['amount']} | {s['merchant']} | {s['explanation'][:100]}")

# Fetch all transactions to get full frozen list
print("\nFetching all transactions...")
all_txns = get_transactions()
all_frozen = list(set(t["user_id"] for t in all_txns if t.get("account_frozen")))
print(f"All frozen users (from /transactions): {all_frozen}")
print(f"Total transactions in DB: {len(all_txns)}")

# Save summary data for writing files
summary = {
    "results": results,
    "classified": classified,
    "frozen_users": frozen_users,
    "all_frozen": all_frozen,
    "total_db_txns": len(all_txns),
    "surprises": surprises
}
with open("/Users/rahulmeena/VIKRAM PROJECT/reports/mission-2026-05-19-213024/sim_results.json", "w") as f:
    json.dump(summary, f, indent=2)
print("\nResults saved to sim_results.json")
