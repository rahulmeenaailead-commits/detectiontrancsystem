# Sentinel × Bright Data — Merchant Reputation Integration

**Date:** 2026-05-27
**Hackathon:** Web Data UNLOCKED (lablab.ai × Bright Data)
**Main track:** Security & Compliance
**Partner bonus:** AI/ML API Challenge (Best Use of AI/ML API)
**Status:** Approved design — ready for implementation plan

---

## 1. Goal

Sentinel today reasons about transactions in a vacuum: amount, user history, deterministic heuristic, LLM judgment. This integration gives Sentinel **live web context** on every merchant it sees, so the fraud agent reads the same signals a human investigator would — scam reports, Trustpilot scores, BBB complaints, news mentions — and factors them into its HIGH/MEDIUM/LOW decision.

The submission qualifies for the Security & Compliance main track (Bright Data integration is meaningful, not cosmetic) and the AI/ML API partner bonus (DeepSeek → AI/ML API as the LLM provider).

## 2. Non-Goals

- Cognee memory layer (separate bonus track, intentionally skipped to keep scope tight).
- Bright Data Scraping Browser or Web Unlocker beyond SERP API (single-API integration keeps the demo story sharp).
- Background scam-feed scraping job (would be heavier infrastructure with no commensurate demo gain).
- Reputation cache invalidation UI / admin endpoints.
- Migrating the existing SQLite schema beyond additive changes.

## 3. Architecture

Three new files + additive edits to existing modules. Nothing destructive.

```
backend/
  brightdata.py        NEW — Bright Data SERP client + cache
  aimlapi.py           NEW — AI/ML API thin client (OpenAI-compatible)
  agent.py             EDIT — wires brightdata + aimlapi into analyze_transaction
  database.py          EDIT — adds merchant_reputation table + 2 columns on transactions
  models.py            EDIT — adds MerchantReputation Pydantic model; Transaction model gains optional web_rep_score, web_rep_cached, web_rep_top_signals
  main.py              EDIT — /transactions response includes web rep fields (additive) + NEW endpoint GET /transactions/{id}/web-rep returning full cached top_results for the row's merchant
  test_brightdata.py   NEW — unit tests for cache + parsing + failure modes
  test_agent.py        EDIT — integration tests cover reputation-driven decisions
.env.example           EDIT — adds BRIGHTDATA_* and AIMLAPI_* keys

frontend/
  app/page.tsx                       EDIT — adds "Web Rep" column to table
  app/components/WebRepBadge.tsx     NEW — colored score badge component
  app/components/WebRepDetailModal.tsx NEW — expandable top-results view
  app/context/TransactionContext.tsx EDIT — extends Transaction type
```

### Module responsibilities

| Module | Public surface | Depends on |
|---|---|---|
| `brightdata.py` | `lookup_merchant(name: str) -> MerchantReputation` | `httpx`, `BRIGHTDATA_API_KEY` env, SQLite cache table |
| `aimlapi.py` | `chat_completion(messages: list[dict]) -> str` | `httpx`, `AIMLAPI_KEY` env |
| `agent.py` | `analyze_transaction(txn) -> AnalysisResult` (signature unchanged, result richer) | `brightdata.lookup_merchant`, `aimlapi.chat_completion`, existing heuristic |

Each module is independently testable; consumers depend only on the public surface.

## 4. Data Flow

```
POST /analyze {user_id, merchant, amount, ...}
        │
        ▼
agent.analyze_transaction()
        │
        ├──► brightdata.lookup_merchant(merchant)
        │       │
        │       ├─ SQLite cache hit (< MERCHANT_REPUTATION_TTL_HOURS)?
        │       │      └─► return cached MerchantReputation (cached=True, ~1ms)
        │       │
        │       └─ Miss ──► SERP API call (query: "{merchant} reviews scam complaints")
        │                   │
        │                   ├─ Parse SERP results: domains + snippets + position
        │                   ├─ Score (see §5)
        │                   ├─ Persist row in merchant_reputation table
        │                   └─ Return MerchantReputation (cached=False, ~1–3s)
        │
        ├──► Build LLM prompt: transaction + user history + reputation block
        │
        ├──► AI/ML API chat_completion(...)  ◄── partner bonus integration point
        │       │
        │       └─ On error/timeout ──► fall back to heuristic (with reputation-score floor)
        │
        ├──► Classify HIGH/MEDIUM/LOW
        │
        ├──► If HIGH ──► freeze_user(user_id)
        │
        └──► Persist transaction with web_rep_score + web_rep_signals

Frontend (existing 3s poll on /transactions):
  Each transaction row now carries web_rep_score, web_rep_cached,
  web_rep_top_signals → renders "Web Rep" badge + click-to-expand modal.
```

### First-lookup vs cache-hit demo moment

On the first transaction for a previously-unseen merchant, the frontend briefly shows a `🌐 Live web lookup…` placeholder in the Web Rep cell, replaced ~1-3s later by the badge. Subsequent transactions for the same merchant render instantly with a `cached` marker. This is the visible "live web data" beat in the demo.

## 5. Reputation Scoring

`brightdata.py` returns a score in `[0, 100]` and a list of signals. Heuristic, fully deterministic, runs over the SERP result set:

| Signal source | Score impact |
|---|---|
| Domain in scam-flag list (scamadviser.com, scam-detector.com, fraud.org, ripoffreport.com appears in top 5) | −30 each (cap at −60) |
| Trustpilot rating ≥ 4.5 detected in snippet | +20 |
| Trustpilot rating ≤ 2.0 detected in snippet | −25 |
| BBB accreditation snippet | +15 |
| Reddit r/scams hit in top 5 | −20 |
| News-domain hit (nytimes.com, reuters.com, bbc.com, …) referencing the merchant | +10 (legitimacy) |
| No SERP results returned | score = `None`, mode = `"unknown"` |

Base score = 50. Clamp final to `[0, 100]`. Score `< 30` = bad, `30-70` = neutral, `> 70` = good.

**Signal detection method:** all signals above are detected via case-insensitive substring/regex matching on the SERP result `title + snippet + url` text — no secondary HTTP calls to Trustpilot, BBB, etc. The SERP snippet itself contains the rating/badge text (e.g. `"Rated 4.6 / 5 based on 12,453 reviews"`), which is sufficient evidence for v1.

The full SERP top-5 results (title, snippet, url, source-domain) are stored alongside the score so the dashboard modal can show evidence.

## 6. Database Changes

Additive only. Because SQLite is in-memory and resets every process restart (existing convention), there is no migration story — both changes are baked into the `CREATE TABLE` statements in `init_db()`:

```sql
CREATE TABLE IF NOT EXISTS merchant_reputation (
    merchant     TEXT PRIMARY KEY,
    score        INTEGER,                 -- nullable when mode != "scored"
    mode         TEXT NOT NULL,           -- "scored" | "unknown" | "disabled" | "timeout" | "error"
    signals      TEXT NOT NULL,           -- JSON array of strings
    top_results  TEXT NOT NULL,           -- JSON array of {title, snippet, url, source_domain}
    fetched_at   TIMESTAMP NOT NULL
);

-- transactions table CREATE statement gains two new columns:
--   web_rep_score    INTEGER          (nullable)
--   web_rep_signals  TEXT             (JSON, nullable)
```

## 7. API Contract (additive only)

`GET /transactions` and `POST /analyze` response shapes gain three optional fields per transaction:

```json
{
  "id": "...",
  "user_id": "...",
  "merchant": "Starbucks",
  "amount": 42.50,
  "risk_level": "LOW",
  "fraud_score": 0.0,
  "action_taken": null,
  "...": "...existing fields...",
  "web_rep_score": 82,
  "web_rep_cached": true,
  "web_rep_top_signals": [
    "Trustpilot 4.6★",
    "BBB accredited",
    "Reuters news mention"
  ]
}
```

Full top-results (urls + snippets) are NOT returned by default to keep `/transactions` payload small; the frontend fetches them on row click via a new `GET /transactions/{id}/web-rep` endpoint that reads the cached `merchant_reputation` row.

## 8. Configuration

`.env.example` gains:

```
# Bright Data
BRIGHTDATA_API_KEY=
BRIGHTDATA_SERP_ZONE=serp_api1
BRIGHTDATA_TIMEOUT_SECONDS=5
MERCHANT_REPUTATION_TTL_HOURS=24

# AI/ML API (partner bonus — OpenAI-compatible endpoint)
AIMLAPI_KEY=
AIMLAPI_BASE_URL=https://api.aimlapi.com/v1
AIMLAPI_MODEL=gpt-4o-mini

# DeepSeek retained as fallback option (existing)
DEEPSEEK_API_KEY=
```

Boot-time LLM provider selection in `agent.py`:
1. If `AIMLAPI_KEY` set → use AI/ML API.
2. Else if `DEEPSEEK_API_KEY` set → use DeepSeek.
3. Else → heuristic only.

Existing demos without new keys continue to work unchanged.

## 9. Error Handling

| Failure | Behavior |
|---|---|
| `BRIGHTDATA_API_KEY` empty or `"your_key_here"` | `lookup_merchant` returns `MerchantReputation(mode="disabled")`. Agent treats reputation as neutral. |
| Bright Data SERP timeout (> `BRIGHTDATA_TIMEOUT_SECONDS`) | Return `mode="timeout"`, log warning, transaction continues. |
| Bright Data 4xx/5xx | Return `mode="error"`, log, transaction continues. |
| AI/ML API timeout or error | Fall back to existing heuristic. Heuristic now reads `reputation.score`: score `< 30` bumps risk level up by one (LOW→MEDIUM, MEDIUM→HIGH). |
| Merchant field missing or empty string | Skip Bright Data call. `reputation = None` in prompt. |
| Cache table missing on first boot | `init_db()` creates it (existing pattern). |
| Cache write race (two concurrent first-lookups for same merchant) | `INSERT OR REPLACE` — last write wins, both lookups complete successfully. |

No new freeze paths. No change to the existing autonomous-freeze semantics.

## 10. Testing Strategy

### `backend/test_brightdata.py` (new)
- Mock HTTP layer with `respx` or monkeypatched `httpx`; never hit real Bright Data.
- Cache hit returns without HTTP call (verify by asserting `respx.calls.call_count == 0`).
- Cache miss makes exactly one HTTP call, persists row, returns `cached=False`.
- Timeout path: simulated `httpx.TimeoutException` → `mode="timeout"`, score `None`, no row persisted (so the next call retries).
- Empty merchant string short-circuits before any HTTP call.
- Score parsing fixtures: scamadviser hit → low score; trustpilot 4.6★ → high score; mixed signals → arithmetic verified.

### `backend/test_agent.py` (extend existing)
- Reputation score 20 + amount $7,500 → HIGH (no regression vs current behavior).
- Reputation score 25 + amount $500 (would be LOW today) → MEDIUM (heuristic floor kicks in).
- Reputation score 85 → LLM prompt string explicitly contains the positive signal (assert substring).
- AI/ML API client mocked; verifies the prompt is built with the reputation block.

### Smoke / demo
`scripts/simulate_attack.sh` extended with:
- One known-good merchant: `Starbucks`
- One known-bad merchant: `FreeMoneyCryptoLottery` (or similar — expected to surface scam-domain hits)
- Verifies the demo shows both code paths (cached + live lookup) and a reputation-driven flag.

### Existing suites — must keep passing
- `regression-validator` — API contract additive only, existing fields unchanged.
- `edge-case-hunter` — empty/long/unicode merchant strings handled gracefully.
- `load-tester` — after the first request per merchant, latency is unchanged (cache hit ≈ 1ms).

## 11. Demo Script (2-minute version)

1. Open dashboard with 0 transactions.
2. Click Simulate → 5 normal Starbucks + Whole Foods transactions appear. First Starbucks row shows `🌐 Live web lookup…` for ~2s, then green badge (`82 ✓ cached for next time`). Other Starbucks rows resolve instantly.
3. Click the Starbucks badge → modal shows Trustpilot 4.6★, BBB accreditation, Reuters news mentions — clear evidence panel.
4. Click "Run suspicious scenario" → adds 3 transactions including `FreeMoneyCryptoLottery $3,000`. Row shows live lookup, then red badge (`18`). Risk level = HIGH. Account frozen.
5. Modal on the bad row shows scamadviser.com, ripoffreport.com, reddit r/scams hits.
6. Talk track: "Sentinel isn't guessing — it's reading the same web a fraud investigator would, in real time. Bright Data unlocks the public web; AI/ML API does the reasoning. The cache means once a merchant is known, decisions are sub-millisecond."

## 12. Submission Checklist

- [ ] Bright Data SERP API used and visible in demo (main track requirement).
- [ ] AI/ML API used as LLM provider (partner bonus requirement).
- [ ] README updated: setup, env vars, demo script.
- [ ] Screenshot of dashboard with both green and red reputation badges.
- [ ] 2-min demo video showing live lookup → cache hit → bad-merchant flag.
- [ ] Architecture diagram (this doc's §4 rendered as image).
- [ ] Submission writeup names both Bright Data and AI/ML API explicitly and explains the integration.
