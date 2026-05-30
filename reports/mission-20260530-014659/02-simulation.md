# Phase 2: Fraud Simulation Report

**Mode:** heuristic (DEEPSEEK_API_KEY not set — deterministic fallback)
**Transactions sent:** 50 across users u1-u5

---

## Batch Composition

| Category   | Intended | Classified |
|------------|----------|------------|
| LOW        | 35       | 42         |
| MEDIUM     | 10       | 3          |
| HIGH       | 5        | 5          |

---

## Methodology

1. Built per-user baselines: 5 transactions each ($5-$62) at coffee shops, groceries, transit, pharmacies — all classified LOW as expected.
2. Sent 10 additional LOW transactions (varied amounts $6-$44) across all users.
3. Sent 10 intended MEDIUM transactions ($140-$380 at electronics/travel merchants).
4. Sent 5 HIGH transactions ($6,500-$15,000 at wire transfers, crypto exchanges, foreign locations).

---

## HIGH Transactions (5/5 correct)

All five HIGH-risk transactions were correctly classified and accounts frozen:

- u1: $7,500 at Unknown Wire Transfer (Lagos, Nigeria) — HIGH, account_frozen
- u2: $12,000 at Crypto Exchange XYZ (Pyongyang, North Korea) — HIGH, account_frozen
- u3: $8,900 at Offshore Wire Transfer (Accra, Ghana) — HIGH, account_frozen + velocity anomaly noted (10 txns in 5 min window)
- u4: $6,500 at Bitcoin ATM (Moscow, Russia) — HIGH, account_frozen
- u5: $15,000 at Luxury Goods International (Dubai, UAE) — HIGH, account_frozen

All accounts were unfrozen post-run via POST /unfreeze/{user_id}.

---

## Accounts Frozen

All five users (u1, u2, u3, u4, u5) were frozen during the HIGH phase and subsequently unfrozen.

---

## Surprises (7 of 10 MEDIUM intended came back LOW)

The heuristic's rolling average includes every prior transaction in the pool, including the baseline and additional LOW batches. By the time MEDIUM transactions were submitted, user averages had risen substantially, pushing the 5x MEDIUM threshold above the intended MEDIUM amounts:

| Transaction ID              | User | Amount | Avg at Time | Ratio | Intended | Got |
|-----------------------------|------|--------|-------------|-------|----------|-----|
| tx-sim-1780085997-36        | u1   | $180   | $39.47      | 4.56x | MEDIUM   | LOW |
| tx-sim-1780085997-39        | u4   | $195   | $45.06      | 4.33x | MEDIUM   | LOW |
| tx-sim-1780085997-41        | u1   | $140   | $50.64      | 2.77x | MEDIUM   | LOW |
| tx-sim-1780085997-42        | u2   | $220   | $63.56      | 3.46x | MEDIUM   | LOW |
| tx-sim-1780085997-43        | u3   | $380   | $95.08      | 4.00x | MEDIUM   | LOW |
| tx-sim-1780085997-44        | u4   | $160   | $57.83      | 2.77x | MEDIUM   | LOW |
| tx-sim-1780085997-45        | u5   | $310   | $81.03      | 3.83x | MEDIUM   | LOW |

Root cause: the rolling average is not windowed or time-bounded. Every previously submitted transaction for a user is included, and the MEDIUM transactions themselves are immediately added to the average once processed, further diluting the ratio for subsequent MEDIUM transactions in the same batch. To reliably trigger MEDIUM, amounts must exceed 5x the current (inflated) average.

---

## Classification Mode

Heuristic (templated). Explanations follow fixed patterns:
- LOW: "Amount $X is within normal range (user avg $Y)."
- MEDIUM: "Amount $X is Nx the user's recent average ($Y). Recommend secondary verification."
- HIGH: "Transaction of $X at [merchant] ([location]) is Nx this user's recent average of $Y. Recommend immediate account freeze."

No LLM-generated text detected.

---

## Key Behavioral Observations

- The rolling average inflates with every transaction — this is a design property the edge-case-hunter should probe at exact ratio boundaries (4.99x, 5.0x, 29.9x, 30.0x).
- The velocity check (5 txns/5 min per user) fired for u3 alongside the amount-based HIGH trigger. This is cumulative with the simulation run's rapid submissions.
- The $5,000 hard threshold is the most reliable HIGH trigger in this mode — ratio-based HIGH is harder to control given average drift.
- POST /unfreeze/{user_id} restored all accounts cleanly; 423 behavior on frozen accounts was not observed during this run (all HIGH txns succeeded before freeze was detected for that request).
