# Sentinel — Submission Dossier
### Web Data UNLOCKED Hackathon (Bright Data × lablab.ai)

> A complete reference for building the submission PDF, slides, and lablab.ai form.
> Everything below is derived from the actual codebase as of 2026-05-30.

---

## 0. How this maps to the lablab.ai submission form

lablab requires these fields. Copy-paste-ready content for each is in this document:

| Required field | Where to find it here |
|---|---|
| **Project Title** | §1 |
| **Short Description** (one-liner) | §1 |
| **Long Description** | §2–§6 |
| **Technology & Category Tags** | §1 (tags) + §7 (stack) |
| **Cover Image** | §11 (what to show) |
| **Video Presentation** | §10 (demo script / talk track) |
| **Slide Presentation** | §12 (slide outline) |
| **Public GitHub Repository** | your repo URL |
| **Demo Application Platform / Application URL** | deploy target — see §13 |

**Bright Data requirement (mandatory):** ✅ Met — Sentinel calls the **Bright Data SERP API** on every transaction to pull live merchant web reputation. See §4.

**Recommended track:** **Track 3 — Security & Compliance** (primary). Sentinel is an AI agent that *investigates risk indicators across the open web and returns structured risk assessments autonomously*, including third-party/merchant risk and reputational/scam-exposure monitoring — verbatim language from that track. **Track 2 — Finance & Market Intelligence** is a valid secondary fit (live financial-risk signals fused into a decision).

---

## 1. The Pitch

**Project Title:** Sentinel — Autonomous Real-Time Fraud Detection with Live Web Reputation

**Short Description (one-liner):**
> Sentinel is an autonomous fraud-detection agent that scores every transaction, reads the same public web a human investigator would — via the Bright Data SERP API — explains its decision in plain English, and freezes accounts the instant risk goes HIGH.

**Tagline:** *Fraud detection that doesn't guess. It reads the web.*

**Technology & Category Tags:** `AI Agent` · `Fraud Detection` · `Bright Data SERP API` · `Web Data` · `FastAPI` · `Next.js` · `DeepSeek LLM` · `Security & Compliance` · `Risk Intelligence` · `Real-Time`

---

## 2. Problem

Fraud-detection systems reason in a vacuum. A traditional engine sees `amount`, `user history`, maybe a velocity rule — and nothing about *who the merchant actually is*. A brand-new shell merchant called "FreeMoneyCryptoLottery" looks identical to a legitimate one to a model that only sees numbers. The signal that would expose it — scam reports, Trustpilot ratings, BBB complaints, Reddit r/scams threads, news coverage — lives on the **open web**, behind rate limits, bot detection, and geo-blocks that internal systems were never built to reach.

That is exactly the wall this hackathon targets: AI agents that are *locked, throttled, or limited by stale data*.

## 3. Solution

Sentinel gives a fraud agent **live web context on every merchant it sees.** On each transaction it:

1. Runs a deterministic multi-signal risk floor (amount, velocity, impossible-travel geo, structuring).
2. **Calls the Bright Data SERP API** to fetch the public web's verdict on the merchant, scored 0–100.
3. Feeds transaction + user history + web reputation into an LLM (DeepSeek) for a plain-English compliance-grade explanation.
4. Combines all layers by *maximum risk* (no layer can be silently overridden downward).
5. If the verdict is **HIGH**, it **autonomously freezes the account** and rejects all further transactions until a human unfreezes it.

The result is an agent that "isn't guessing — it's reading the same web a fraud investigator would, in real time."

---

## 4. Bright Data Integration (the heart of the submission)

**Product used:** Bright Data **SERP API** (via the unified `https://api.brightdata.com/request` endpoint).

**File:** [backend/brightdata.py](backend/brightdata.py) + scoring in [backend/brightdata_scoring.py](backend/brightdata_scoring.py)

### How it works

For each merchant, Sentinel issues a Google search through Bright Data:

```
query   = "{merchant} reviews scam complaints"
POST https://api.brightdata.com/request
{
  "zone":   "serp_api1",
  "url":    "https://www.google.com/search?q=<query>&brd_json=1",
  "format": "raw"
}
Authorization: Bearer $BRIGHTDATA_API_KEY
```

`brd_json=1` makes Bright Data return the SERP as structured JSON. Sentinel parses the **top 5 organic results** and scores them deterministically:

| Web signal (detected in title/snippet/url) | Score impact |
|---|---|
| Scam-flag domain (scamadviser.com, scam-detector.com, fraud.org, ripoffreport.com) | −30 each (capped at −60) |
| Trustpilot rating ≥ 4.5★ | +20 |
| Trustpilot rating ≤ 2.0★ | −25 |
| BBB (bbb.org) listing | +15 |
| Reddit **r/scams** hit | −20 |
| Reputable news domain (nytimes, reuters, bbc, wsj, ft, bloomberg) | +10 |

Base score = 50, clamped to **[0, 100]**. `< 30` = bad (red), `30–70` = neutral (yellow), `> 70` = good (green).

### Why this is a *meaningful* (not cosmetic) integration

- The web score is wired into the **decision**, not just displayed. In the heuristic path, a merchant scoring `< 30` raises risk to at least MEDIUM; `< 15` forces HIGH — a "reputation floor" the rest of the engine cannot weaken (see [backend/agent.py](backend/agent.py) `_heuristic`).
- In LLM mode, the reputation block is injected into the prompt so the model reasons over real web evidence (`_reputation_block` in agent.py).
- The full SERP evidence (titles, snippets, URLs, source domains) is stored and surfaced in the dashboard so a human can audit *why* — clickable links to the actual scam reports.

### Performance & resilience

- **Caching:** every lookup is persisted to a `merchant_reputation` table with a 24h TTL (`MERCHANT_REPUTATION_TTL_HOURS`). First transaction for a new merchant = live web call (~1–3s); every subsequent one = sub-millisecond cache hit. This is the visible "live lookup → cached" beat in the demo.
- **Disabled-safe:** if `BRIGHTDATA_API_KEY` is empty, lookups return `mode="disabled"` and the system degrades gracefully to numeric heuristics — so judges can run it with or without a key.
- **Failure modes:** timeout → `mode="timeout"`, HTTP error → `mode="error"`, empty merchant → `mode="unknown"`. None of these block a transaction; the agent continues with whatever signal it has.

---

## 5. The Fraud-Detection Engine (defense in depth)

[backend/agent.py](backend/agent.py) → `analyze_transaction()` layers six independent detectors and combines them by **maximum risk**:

| Layer | What it catches | Where |
|---|---|---|
| **Amount / ratio heuristic** | `amount ≥ $5,000` OR `≥ 30× user's recent avg` → HIGH | `_heuristic` |
| **Velocity** | ≥ 5 transactions in 5 min → card-testing pattern → HIGH | `_check_velocity` |
| **Geo / impossible-travel** | Two locations < 5 min apart that can't be physically traveled → HIGH | `_check_geo_velocity` |
| **Structuring / smurfing** | Rolling 60-min total ≥ $20,000 across sub-threshold txns → MEDIUM | `_check_structuring` |
| **Web reputation floor** | Bright Data merchant score < 30 → ≥ MEDIUM; < 15 → HIGH | `_heuristic` |
| **LLM reasoning** | Plain-English, compliance-grade narrative; can only *raise* the rule floor | DeepSeek path |

**Dual-mode by design:** with a real `DEEPSEEK_API_KEY` it uses the LLM (`deepseek-chat`) for the explanation and risk; with no key it falls back to a fully deterministic heuristic — so the demo always works and is reproducible. On any LLM API error it falls back to the heuristic with the error annotated.

**Autonomous action:** any HIGH verdict calls `freeze_user(user_id)`, sets the transaction's `action_taken = "account_frozen"`, and the API then **rejects every future transaction** for that user with HTTP `423 Locked` until an operator hits `POST /unfreeze/{user_id}`. This is the "agent acts without human intervention" requirement, made concrete.

---

## 6. Architecture & Data Flow

```
Next.js Dashboard (localhost:3000)
   │   POST /analyze            GET /transactions (poll every 3s)
   ▼
FastAPI Backend (localhost:8000)  ── API key auth · rate limit · CORS · validation
   │
   ├─ insert transaction ──► SQLite (WAL)
   │
   ├─ agent.analyze_transaction()
   │     ├─ deterministic rules: amount · velocity · geo · structuring
   │     ├─ brightdata.lookup_merchant()
   │     │      ├─ cache hit (<24h)? → return (~1ms)
   │     │      └─ miss → Bright Data SERP API → score → persist
   │     ├─ DeepSeek LLM reasoning (or heuristic fallback)
   │     └─ combine by MAX risk
   │
   ├─ if HIGH ──► freeze_user()  (autonomous action)
   │
   └─ persist verdict + web-rep fields ──► returned to dashboard
```

**Endpoints** ([backend/main.py](backend/main.py)):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Health check |
| `GET` | `/transactions` | All transactions, newest first (incl. web-rep fields) |
| `GET` | `/transactions/{id}/web-rep` | Full cached SERP evidence for a transaction's merchant |
| `POST` | `/analyze` | Analyze + persist + autonomously freeze on HIGH (rate-limited 60/min) |
| `POST` | `/unfreeze/{user_id}` | Human override to restore a frozen account |

**Database** ([backend/database.py](backend/database.py)): SQLite with WAL mode, a global write lock (single-writer safe under FastAPI), `transactions`, `users`, and `merchant_reputation` tables, plus an additive migration that backfills the web-rep columns on pre-existing DB files.

---

## 7. Tech Stack

- **Backend:** FastAPI · Pydantic v2 · SQLite (WAL) · `httpx` (Bright Data calls) · OpenAI Python SDK (DeepSeek client) · SlowAPI (rate limiting)
- **LLM:** DeepSeek `deepseek-chat` (OpenAI-compatible), with a deterministic heuristic fallback
- **Web data:** **Bright Data SERP API**
- **Frontend:** Next.js (App Router) · React · TypeScript · Tailwind CSS · Axios · React Context (3s polling, fade-in on new rows)
- **Infra:** Docker + Docker Compose (one-command bring-up)
- **Testing:** pytest · respx (HTTP mocking) + 6 Claude Code testing subagents and a "Mission Mode" multi-agent test orchestrator

---

## 8. Security & Production-Readiness

These matter for the **Security & Compliance** track and the "Business Value" judging criterion:

- **API-key auth** on all data endpoints (`X-API-Key` header).
- **CORS locked down** to a configurable allow-list (`CORS_ORIGINS`) — no longer wildcard.
- **Rate limiting** — 60/min on `/analyze` via SlowAPI (429 on breach).
- **Strict input validation** — Pydantic `Field` constraints (amount `> 0`, length caps, no inf/nan), 422 on bad input, 409 on duplicate transaction id.
- **Frozen-account enforcement** — 423 Locked on any transaction for a frozen user.
- **Graceful degradation** — every external dependency (Bright Data, DeepSeek) has a defined failure mode that never blocks a transaction.

---

## 9. Testing & Quality

- **Unit tests:** `test_brightdata.py` (cache hit/miss, timeout, empty-merchant short-circuit), `test_brightdata_scoring.py` (signal scoring arithmetic), `test_agent.py` (reputation-driven decisions, no-regression).
- **Six specialist testing agents** in [.claude/agents/](.claude/agents/): `fraud-simulator`, `attack-scenario-runner`, `security-prober`, `load-tester`, `edge-case-hunter`, `regression-validator`.
- **Mission Mode** (`scripts/run_mission.sh`): one command dispatches all six sequentially and synthesizes a single `MISSION_REPORT.md` — a full adversarial sweep (attacks, security, edge cases, load, regression). Past reports live in [reports/](reports/).
- **Validated end-to-end** with 72K+ test transactions; freeze/unfreeze cycle confirmed.

---

## 10. Demo Script (for the video — 2 minutes)

1. Open the dashboard with 0 transactions.
2. Click **Simulate** → normal transactions appear. The first row for a new merchant shows `🌐 Live web lookup…`, then resolves to a **green** reputation badge (~1–3s). Subsequent rows for that merchant render instantly with a `·c` (cached) marker — *the live-web → cache beat.*
3. Click the green badge → modal shows the **actual SERP evidence**: Trustpilot stars, BBB listing, news mentions, with clickable links.
4. Run a suspicious scenario including a bad merchant (e.g. `FreeMoneyCryptoLottery`, `Unknown Wire Transfer`). The row does a live lookup → **red** badge (low score) → risk = **HIGH** → **Account frozen** lights up in the stats bar.
5. Click the red badge → modal shows scamadviser.com / ripoffreport.com / r/scams hits — the evidence trail.
6. Try to send another transaction for that user → rejected (423), proving the autonomous freeze holds.

**Talk track:** *"Sentinel isn't guessing — it's reading the same web a fraud investigator would, in real time. Bright Data unlocks the public web; the agent does the reasoning and acts on its own. And because every merchant verdict is cached, the second time we see it the decision is sub-millisecond."*

---

## 11. Cover Image / Screenshots to capture

- The dashboard mid-demo showing **both a green and a red** reputation badge in the table.
- The **WebRepDetailModal** open on a bad merchant, showing scam-report links (proves real web data).
- The stats bar with **HIGH risk detected** and **Accounts frozen** counters > 0.

---

## 12. Slide Outline (5–7 slides)

1. **Title** — Sentinel + tagline + the one-liner.
2. **Problem** — fraud engines reason in a vacuum; the exposing signal is on the open web (§2).
3. **Solution** — the agent reads the web via Bright Data, reasons, and acts (§3).
4. **Bright Data integration** — SERP API → 0–100 reputation score → wired into the decision (§4). *This is the slide judges care about most.*
5. **Architecture** — the data-flow diagram (§6) + defense-in-depth layers (§5).
6. **Demo** — embedded video / screenshots (§10–§11).
7. **Impact & what's next** — business value, Security & Compliance fit, roadmap (§14).

---

## 13. Run / Deploy

**Local (one command):**
```bash
cp .env.example .env          # set DEEPSEEK_API_KEY and BRIGHTDATA_API_KEY
docker compose up --build
# Dashboard → http://localhost:3000   API → http://localhost:8000
```

**Local dev (no Docker):**
```bash
cd backend && source venv/bin/activate && uvicorn main:app --reload
cd frontend && npm run dev
```

**Bright Data $250 credit (every participant):** sign up at brightdata.com → Billing → Overview → Apply promo code **`unlocked`**.

---

## 14. Roadmap / "What's Next"

- Add Bright Data **Web Unlocker / Scraping Browser** to read full scam-report pages (not just SERP snippets) for richer evidence.
- Continuous background re-scoring of known merchants so reputation stays fresh beyond the 24h TTL.
- Sanctions / watchlist screening via live web sources (deepens the Compliance angle).
- Configurable per-merchant-category risk policies.

---

## 15. ⚠️ Pre-submission fix list (do before recording the demo)

1. **Pass the Bright Data key into Docker.** [docker-compose.yml](docker-compose.yml) currently only forwards `DEEPSEEK_API_KEY` to the backend. Add `BRIGHTDATA_API_KEY` (and `SENTINEL_API_KEY`, `CORS_ORIGINS`, `BRIGHTDATA_SERP_ZONE`) to the backend `environment:` block, or Bright Data runs in `disabled` mode inside the container and your core feature won't fire on stage.
2. **Decide on the AI/ML API partner bonus.** The design spec references AI/ML API as an LLM provider, but it was removed — current code is DeepSeek-only. Either (a) don't mention AI/ML API in the writeup, or (b) re-add it to also qualify for that $1,000 + $1,000 partner challenge.
3. **Refresh README claims** — it says "DeepSeek V4 Pro" / "Next.js 16"; align with the actual model id (`deepseek-chat`) and installed versions before judges read it.
4. **Add a real screenshot** — `README.md` references `docs/screenshot.png` which doesn't exist yet.
5. **Make sure the LLM path is exercised in the demo** if you want to show the plain-English explanations (otherwise the heuristic strings show instead).

---

## Appendix A — Hackathon facts (for reference)

- **Event:** Web Data UNLOCKED — Bright Data AI Agents Web Data Hackathon (hybrid: online + onsite at The Web Data Loft, San Francisco).
- **Hard requirement:** submission must demonstrably use **at least one Bright Data product**. ✅ (SERP API)
- **Three main tracks:** GTM Intelligence · Finance & Market Intelligence · **Security & Compliance** (Sentinel's primary).
- **Judging criteria:** Application of Technology · Presentation · Business Value · Originality.
- **What to submit:** Title, Short + Long Description, Tech/Category tags, Cover Image, Video Presentation, Slide Presentation, public GitHub repo, demo/app URL.
- **Prizes:** $18,300+ total. Online: $700 per track winner. Onsite: $1,000 per track + $3,000. Partner challenges incl. AI/ML API ($1,000 cash + $1,000 credits), Kiro, Featherless, Cognee. Winners may be fast-tracked into the Bright Data AI Startup Program (up to $20K credits).
- **Credits:** $250 Bright Data API credits per participant (promo code `unlocked`).
