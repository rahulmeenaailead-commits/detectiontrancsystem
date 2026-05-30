# Sentinel — Full Mission Test Report

**Date:** 2026-05-30 01:47 IST
**Backend:** http://localhost:8000 (heuristic / mock mode — `DEEPSEEK_API_KEY` empty)
**Mission dir:** `reports/mission-20260530-014659/`
**Phases run:** 6/6 (regression → simulation → edge-cases → attacks → security → load)

---

## Verdict

The system is **functionally sound and performant** in heuristic mode: the API contract is stable, no crashes under any input, and it sustains 1500+ RPS with sub-50ms p99. Detection coverage is **amount-driven only** — it catches large/ratio-anomalous transactions but misses velocity-, threshold-evasion-, and geo-based attacks. Security posture is **deliberately open** (hackathon build): 6 of 7 documented weaknesses confirmed.

| Phase | Status | Headline |
|-------|--------|----------|
| 1. Regression | ✅ PASS | 12/12 tests, no drift, schema stable |
| 2. Simulation | ✅ PASS | 50/50 accepted; 32 LOW / 18 HIGH; no MEDIUM ever |
| 3. Edge cases | ⚠️ PASS w/ surprises | 9 PASS / 2 FAIL / 3 SURPRISE; no crashes |
| 4. Attacks | ⚠️ PARTIAL | 3/6 caught (50% catch rate) |
| 5. Security | 🚨 6/7 CONFIRMED | no-auth + irreversible-freeze = unauth DoS |
| 6. Load | ✅ PASS | 1547 peak RPS, 0% errors, p99 47ms |

---

## Phase 1 — Regression (PASS)

- `/transactions` and `/analyze` schemas validated.
- 12/12 fixture classifications matched baseline; **no drift**.
- Confirmed thresholds: `amount ≥ 5000` **OR** `amount ≥ 30× user-avg` → HIGH.
- Unfreeze restores account → subsequent valid txn classifies LOW. ✅

## Phase 2 — Traffic Simulation (PASS)

- 50 mixed txns across synthetic users, all accepted.
- Distribution: **LOW 32 / MEDIUM 0 / HIGH 18**.
- **Surprise:** heuristic is binary — `fraud_score` is only 0.0 or 1.0, **MEDIUM is never assigned**. The `risk_level` column supports MEDIUM but the heuristic never emits it.
- Freeze cascade observed: once frozen, all of a user's later txns route through the frozen account.

## Phase 3 — Edge Cases (PASS with surprises)

- 14 cases: **9 PASS / 2 FAIL / 3 SURPRISE**. **No crashes** on any malformed input.
- ✅ Handled well: huge amounts (1e18), unicode/emoji merchants, string→float coercion, exact-5000 boundary, zero amount, empty-DB, missing-field → 422.
- ⚠️ **Surprises (weak validation, not crashes):**
  - `amount = -5000` accepted, classified LOW — no negative-amount rejection.
  - `user_id` null/missing accepted — txn stored with null owner.
  - Zero-avg (first-ever txn) ratio check divides by zero but is handled gracefully (absolute threshold still applies).

## Phase 4 — Attack Scenarios (50% catch rate)

| Scenario | Detected | Action | Note |
|----------|----------|--------|------|
| card-testing (rapid $1–2) | ❌ | none | no velocity modeling |
| account-takeover | ✅ | account_frozen | tripped 30× ratio |
| structuring/smurfing (4999×N) | ❌ | none | just under 5000 absolute |
| mule-transfer (large round) | ✅ | account_frozen | ≥5000 absolute |
| geo-impossible | ❌ | none | no geo modeling |
| merchant-anomaly | ✅ | flagged | Bright Data reputation / amount |

**Misses are heuristic design limits, not bugs.** All amount-based attacks caught; all behavioral/velocity/geo attacks missed.

## Phase 5 — Security (6/7 confirmed)

| Weakness | Confirmed | Severity |
|----------|-----------|----------|
| No auth | ✅ | **HIGH** |
| Irreversible/unauth freeze | ✅ | **HIGH** |
| Open CORS (`*`) | ✅ | MEDIUM |
| No rate limit | ✅ | MEDIUM |
| Prompt injection (merchant name → LLM) | ✅ | MEDIUM |
| Weak input validation | ✅ | MEDIUM |
| Type confusion | ❌ not found | — (Pydantic coerces/422s safely) |

**Most critical:** `no_auth` + `irreversible_freeze` combine — anyone can freeze **or** unfreeze any `user_id` with no credentials → account-freeze DoS and freeze bypass. Prompt injection is latent in mock mode but live once a real DeepSeek key is set. All documented in CLAUDE.md as accepted hackathon scope.

## Phase 6 — Load (PASS)

- Peak **1547 RPS**, **0.0% errors**, no 429s (corroborates no-rate-limit finding).
- Latency: **p50 8ms / p95 31ms / p99 47ms**.
- **Knee point: concurrency = 25** — beyond it latency climbs; bottleneck is SQLite write contention.

---

## Top recommendations (priority order)

1. **Add auth to mutating endpoints** (`/analyze`, freeze/unfreeze) before any non-demo use — closes the unauth-freeze DoS (Phase 5, HIGH).
2. **Validate inputs:** reject negative amounts and require `user_id` (Phase 3 + 5).
3. **Add behavioral signals** — velocity (card-testing), just-under-threshold streaks (smurfing), and geo-velocity — to lift catch rate above 50% (Phase 4).
4. **Emit MEDIUM** — wire the middle band so `fraud_score 0.5` is reachable (Phase 2).
5. **Sanitize merchant-derived text** before it enters the LLM prompt (Phase 5, prompt injection) — relevant once a real key is configured.
6. **Tighten CORS** off `*` for deployment (CLAUDE.md already flags this).

---

*Per-phase detail in `01-regression.md` … `06-load.md`; machine-readable summaries in the matching `.json` files.*
