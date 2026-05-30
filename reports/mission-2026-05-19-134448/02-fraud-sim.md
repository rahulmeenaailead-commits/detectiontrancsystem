# Phase 2 — Fraud Simulator Report

**Mode:** DeepSeek (LLM active)
**Run:** 2026-05-19T13:55:00Z – 13:57:30Z

## Results

| Metric | Value |
|--------|-------|
| Sent | 50 |
| Intended LOW | 35 |
| Intended MEDIUM | 10 |
| Intended HIGH | 5 |
| Classified LOW | 43 |
| Classified MEDIUM | 2 |
| Classified HIGH | 5 |

## Accounts Frozen

All 5 sim users frozen: `sim-u01`, `sim-u02`, `sim-u03`, `sim-u04`, `sim-u05`

## Surprises

8 of 10 intended-MEDIUM transactions were downgraded to LOW. The LLM explanations were templated — all followed the pattern "Amount $X.00 is within normal range (user avg $Y). No action required." — suggesting the heuristic comparison path dominated even in DeepSeek mode.

Root cause: because the DB was dirty (pre-existing transactions from prior runs pushed user averages to $60-$103), amounts like $280-$450 at 3-8x the sub-$30 intended baseline were instead 2-5x the inflated real average, landing below the effective MEDIUM threshold. The 2 that did classify MEDIUM ($320 for sim-u01 at avg $102.78 = 3.1x, and $510 for sim-u03 at avg $96.67 = 5.3x) suggest a soft threshold somewhere around 3x, but it was inconsistent ($450 at 4.4x went LOW).

HIGH detection was perfect: all 5 flagged correctly (crypto exchange in Lagos, wire to Pyongyang, dark web in anonymous proxy, international wire to Moscow, offshore shell in Panama) with amounts $5,500-$9,800.

## Mode Assessment

Explanations look **templated / heuristic-formula** rather than LLM-generated prose. DeepSeek may be producing structured output that maps to these short phrases, or the heuristic fallback is engaging more often than expected for borderline cases.
