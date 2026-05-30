# Phase 2 — Fraud Simulator Report

**Mode:** DeepSeek (LLM)
**Run:** 2026-05-19T21:30–21:38 UTC

## Traffic Summary

- **Sent:** 50 transactions (+ 25 baseline pre-seeds)
- **Intended mix:** LOW=35, MEDIUM=10, HIGH=5
- **Classified:** LOW=34, MEDIUM=10, HIGH=6
- **Total in DB after run:** 85 transactions

## Account Freezes

All 5 users frozen: **u1, u2, u3, u4, u5**

Each freeze was triggered by a HIGH-classified transaction (wire transfers, crypto exchanges, offshore accounts). Note: u4 continued to receive and process transactions after being frozen — the $480 Southwest Airlines txn posted after the $390 United Airlines freeze and returned LOW.

## Surprises (4)

| ID | Intended | Got | User | Amount | Merchant | Notes |
|----|----------|-----|------|--------|----------|-------|
| tx-sim-1779206694-307 | LOW | MEDIUM | u2 | $55 | Target | 2.5x avg; LLM flagged ratio deviation at routine retail |
| tx-sim-1779206694-332 | LOW | MEDIUM | u2 | $80 | Best Buy Accessories | 2.3x avg; LLM cited potential anomaly |
| tx-sim-1779206694-339 | MEDIUM | HIGH | u4 | $390 | United Airlines | 6x avg; LLM escalated to HIGH, triggered account freeze |
| tx-sim-1779206694-344 | MEDIUM | LOW | u4 | $480 | Southwest Airlines | 6.6x avg; LLM rationalized as legitimate domestic travel |

## Key Findings

1. **All 5 HIGH-intended transactions correctly caught** — amounts $6000-$12000 to Lagos, Pyongyang, Moscow, Cayman Islands, Dubai all returned HIGH. Confirms LLM is reliable for extreme-value + foreign-locale combinations.

2. **LLM under-classifies boundary zone ($300-$600)** — consistent with Phase 1 drift. Southwest Airlines $480 returned LOW vs United Airlines $390 returning HIGH. Merchant reputation overrides ratio signals inconsistently.

3. **LLM over-sensitive at LOW end for u2** — $55 Target and $80 Best Buy Accessories were flagged MEDIUM because u2's running average was low (~$21-$34). The LLM tracks ratio updates in real-time as the average grows.

4. **Explanations are LLM-generated, not templated** — each explanation references specific merchant names, exact dollar amounts, and calculated ratios. Natural language varies per transaction. No boilerplate detected.

5. **Post-freeze processing confirmed** — u4 was frozen on tx-339 (United Airlines HIGH) but tx-344 (Southwest Airlines) still processed and returned LOW. The freeze flag does not block analysis.

## Mode

DeepSeek (LLM-generated explanations, merchant-aware reasoning)
