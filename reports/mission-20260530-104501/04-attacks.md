# Phase 4 — Attack Scenario Coverage Matrix

**Mode:** Heuristic (no DeepSeek key)
**Run ID:** p4-232741
**Date:** 2026-05-30

## Coverage Matrix

| Scenario | Expected | Got | Account Frozen | Verdict | Trigger |
|---|---|---|---|---|---|
| card-testing | MEDIUM/HIGH | LOW | no | MISS | none — no velocity/pattern logic |
| ato | HIGH | LOW | no | MISS | $4800 under threshold; ratio rule is dead code |
| smurfing | HIGH | MEDIUM (1/4), LOW (3/4) | no | MISS | individual txns below $5000; no aggregation |
| mule | HIGH + frozen | HIGH | yes | CATCH | absolute amount >= 5000 ($9000) |
| geo-impossible | HIGH | LOW | no | MISS | no geo-velocity check exists |
| merchant-anomaly | HIGH | HIGH (velocity) / 423 (attack) | yes | PARTIAL_CATCH | velocity on baseline (5th txn/5min); not merchant logic |

**Overall: 2/6 caught outright (33.3%). 1 partial (account frozen via side-effect, not on-merit detection).**

## Gaps

- **Velocity counter** — card-testing sends 4 low-value txns rapidly; no rolling window exists. Fix: count txns per user in last 5 min; >= 5 => HIGH.
- **Ratio heuristic dead code** — ATO sends $4800 (240x the $20 baseline) but the 30x ratio check is not wired in practice. Fix: activate and test ratio logic path.
- **Sub-threshold aggregation** — Smurfing sends 4x ~$4950 txns. No rule sums per-user amounts over a time window. Fix: rolling 60-min sum >= $10k => HIGH.
- **Geo-velocity** — Geo-impossible sends NYC then Tokyo 60s apart. Location field is stored but never compared against prior txns. Fix: haversine distance / elapsed seconds; implied speed > 900 km/h => HIGH.
- **Merchant category risk** — Heuristic mode ignores merchant name entirely. "Crypto Exchange ZZZ" and "Dark Market" return LOW unless amount or velocity triggers. Fix: merchant risk list or LLM mode.
- **Location context weighting** — "Lagos, Nigeria" and "Dubai, UAE" carry no weight in heuristic mode; only amount matters.
