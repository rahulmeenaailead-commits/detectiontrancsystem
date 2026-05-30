# Sentinel × Bright Data — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **No-git policy:** Per user request, do NOT run any `git` commands. Every "Save checkpoint" step is a no-op marker — just verify the files saved successfully and move on.

**Goal:** Add Bright Data SERP-driven merchant reputation enrichment to Sentinel's `/analyze` flow and route LLM calls through AI/ML API, qualifying for the Web Data UNLOCKED hackathon's Security & Compliance main track + AI/ML API partner bonus.

**Architecture:** New `brightdata.py` (SERP client + SQLite cache + scoring) and `aimlapi.py` (OpenAI-compatible client) plug into `agent.analyze_transaction` between user-history fetch and LLM call. Reputation surfaces in the dashboard via a new "Web Rep" column with a click-to-expand evidence modal. Per-merchant cache (24h TTL) keeps p95 latency unchanged after first lookup.

**Tech Stack:** FastAPI, Pydantic v2, SQLite (in-memory), `httpx` (already a transitive dep via `openai`), `respx` (test-only), Next.js 14 App Router, Tailwind v4.

**Spec:** [docs/superpowers/specs/2026-05-27-brightdata-reputation-integration-design.md](../specs/2026-05-27-brightdata-reputation-integration-design.md)

---

## Phase 1 — Backend Foundation

### Task 1: Database schema additions

**Files:**
- Modify: `backend/database.py` (CREATE TABLE block ~line 17 for transactions, ~line 34 for users)

- [ ] **Step 1: Add three columns to the transactions CREATE TABLE**

In `init_db()`, extend the `CREATE TABLE IF NOT EXISTS transactions` statement to include:

```sql
web_rep_score INTEGER,
web_rep_signals TEXT,
web_rep_cached INTEGER
```

All nullable. Place them at the end of the column list, before the closing `)`. `web_rep_cached` is `0`/`1` (SQLite has no native bool).

- [ ] **Step 2: Add the merchant_reputation CREATE TABLE statement**

Inside `init_db()`, immediately after the existing `CREATE TABLE` for `users`, add:

```python
cursor.execute("""
CREATE TABLE IF NOT EXISTS merchant_reputation (
    merchant TEXT PRIMARY KEY,
    score INTEGER,
    mode TEXT NOT NULL,
    signals TEXT NOT NULL,
    top_results TEXT NOT NULL,
    fetched_at TIMESTAMP NOT NULL
)
""")
conn.commit()
```

- [ ] **Step 3: Verify schema by running the backend once**

Run: `cd backend && ./venv/bin/python -c "import database; print('OK')"`
Expected: prints `OK` with no exception.

- [ ] **Step 4: Save checkpoint** (no git)

---

### Task 2: MerchantReputation Pydantic model

**Files:**
- Modify: `backend/models.py`

- [ ] **Step 1: Append MerchantReputation model**

Add to `backend/models.py`:

```python
from typing import Literal, Optional


class MerchantReputationResult(BaseModel):
    title: str
    snippet: str
    url: str
    source_domain: str


class MerchantReputation(BaseModel):
    merchant: str
    score: Optional[int] = None
    mode: Literal["scored", "unknown", "disabled", "timeout", "error"]
    signals: list[str] = Field(default_factory=list)
    top_results: list[MerchantReputationResult] = Field(default_factory=list)
    cached: bool = False
```

- [ ] **Step 2: Verify model imports cleanly**

Run: `cd backend && ./venv/bin/python -c "from models import MerchantReputation; print(MerchantReputation(merchant='x', mode='disabled'))"`
Expected: prints a model instance with `mode='disabled'`, `score=None`, empty lists.

- [ ] **Step 3: Save checkpoint** (no git)

---

### Task 3: Bright Data client — disabled mode + empty-merchant short-circuit (TDD)

**Files:**
- Create: `backend/test_brightdata.py`
- Create: `backend/brightdata.py`

- [ ] **Step 1: Write failing tests**

Create `backend/test_brightdata.py`:

```python
import os
from unittest.mock import patch

from brightdata import lookup_merchant


def test_disabled_when_no_api_key():
    with patch.dict(os.environ, {"BRIGHTDATA_API_KEY": ""}, clear=False):
        rep = lookup_merchant("Starbucks")
    assert rep.mode == "disabled"
    assert rep.score is None
    assert rep.cached is False


def test_disabled_when_placeholder_key():
    with patch.dict(os.environ, {"BRIGHTDATA_API_KEY": "your_key_here"}, clear=False):
        rep = lookup_merchant("Starbucks")
    assert rep.mode == "disabled"


def test_empty_merchant_returns_unknown():
    with patch.dict(os.environ, {"BRIGHTDATA_API_KEY": "real-key"}, clear=False):
        rep = lookup_merchant("")
    assert rep.mode == "unknown"
    assert rep.merchant == ""
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `cd backend && ./venv/bin/python -m pytest test_brightdata.py -v`
Expected: `ModuleNotFoundError: No module named 'brightdata'`.

- [ ] **Step 3: Create minimal `brightdata.py`**

```python
import os

from models import MerchantReputation


def _is_disabled() -> bool:
    key = os.getenv("BRIGHTDATA_API_KEY", "").strip()
    return key in ("", "your_key_here")


def lookup_merchant(merchant: str) -> MerchantReputation:
    if _is_disabled():
        return MerchantReputation(merchant=merchant, mode="disabled")
    if not merchant.strip():
        return MerchantReputation(merchant=merchant, mode="unknown")
    raise NotImplementedError("HTTP path comes in Task 4")
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `cd backend && ./venv/bin/python -m pytest test_brightdata.py -v`
Expected: 3 passed.

- [ ] **Step 5: Save checkpoint** (no git)

---

### Task 4: Bright Data client — cache hit / miss flow with mocked HTTP

**Files:**
- Modify: `backend/test_brightdata.py`
- Modify: `backend/brightdata.py`

- [ ] **Step 1: Install `respx` in the venv** (HTTP-mocking lib for `httpx`)

Run: `cd backend && ./venv/bin/pip install respx pytest-asyncio`

Also add `respx` and `pytest-asyncio` to `backend/requirements.txt` (dev only — they don't break prod).

- [ ] **Step 2: Add failing cache tests**

Append to `backend/test_brightdata.py`:

```python
import json
import respx
import httpx
from database import cursor, conn


def _clear_cache():
    cursor.execute("DELETE FROM merchant_reputation")
    conn.commit()


@respx.mock
def test_cache_miss_then_hit(monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
    monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_test")
    _clear_cache()

    fake_serp = {
        "organic": [
            {"title": "Acme Corp — Trusted Vendor",
             "description": "Rated 4.6 / 5 based on 2,000 reviews on Trustpilot",
             "link": "https://www.trustpilot.com/review/acme.com"}
        ]
    }
    route = respx.post("https://api.brightdata.com/request").mock(
        return_value=httpx.Response(200, json=fake_serp)
    )

    rep1 = lookup_merchant("Acme Corp")
    assert rep1.cached is False
    assert rep1.mode == "scored"
    assert route.call_count == 1

    rep2 = lookup_merchant("Acme Corp")
    assert rep2.cached is True
    assert route.call_count == 1  # cache hit, no second HTTP call
```

- [ ] **Step 3: Run, confirm failure**

Run: `cd backend && ./venv/bin/python -m pytest test_brightdata.py::test_cache_miss_then_hit -v`
Expected: FAIL (NotImplementedError or similar).

- [ ] **Step 4: Implement the cache + HTTP path in `brightdata.py`**

Replace the file contents:

```python
import json
import os
from datetime import datetime, timedelta, timezone

import httpx

from database import cursor, conn
from models import MerchantReputation, MerchantReputationResult

BRIGHTDATA_URL = "https://api.brightdata.com/request"


def _is_disabled() -> bool:
    key = os.getenv("BRIGHTDATA_API_KEY", "").strip()
    return key in ("", "your_key_here")


def _ttl_hours() -> int:
    return int(os.getenv("MERCHANT_REPUTATION_TTL_HOURS", "24"))


def _timeout() -> float:
    return float(os.getenv("BRIGHTDATA_TIMEOUT_SECONDS", "5"))


def _zone() -> str:
    return os.getenv("BRIGHTDATA_SERP_ZONE", "serp_api1")


def _load_cached(merchant: str) -> MerchantReputation | None:
    cursor.execute(
        "SELECT score, mode, signals, top_results, fetched_at FROM merchant_reputation WHERE merchant = ?",
        (merchant,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    score, mode, signals_json, top_json, fetched_at = row
    fetched = datetime.fromisoformat(fetched_at)
    if datetime.now(timezone.utc) - fetched > timedelta(hours=_ttl_hours()):
        return None
    top = [MerchantReputationResult(**r) for r in json.loads(top_json)]
    return MerchantReputation(
        merchant=merchant, score=score, mode=mode,
        signals=json.loads(signals_json), top_results=top, cached=True,
    )


def _persist(rep: MerchantReputation) -> None:
    cursor.execute(
        "INSERT OR REPLACE INTO merchant_reputation "
        "(merchant, score, mode, signals, top_results, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            rep.merchant, rep.score, rep.mode,
            json.dumps(rep.signals),
            json.dumps([r.model_dump() for r in rep.top_results]),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def _fetch_serp(merchant: str) -> dict:
    payload = {
        "zone": _zone(),
        "url": f"https://www.google.com/search?q={merchant}+reviews+scam+complaints&brd_json=1",
        "format": "raw",
    }
    headers = {"Authorization": f"Bearer {os.getenv('BRIGHTDATA_API_KEY')}"}
    r = httpx.post(BRIGHTDATA_URL, json=payload, headers=headers, timeout=_timeout())
    r.raise_for_status()
    return r.json()


def lookup_merchant(merchant: str) -> MerchantReputation:
    if _is_disabled():
        return MerchantReputation(merchant=merchant, mode="disabled")
    if not merchant.strip():
        return MerchantReputation(merchant=merchant, mode="unknown")

    cached = _load_cached(merchant)
    if cached:
        return cached

    try:
        serp_json = _fetch_serp(merchant)
    except httpx.TimeoutException:
        return MerchantReputation(merchant=merchant, mode="timeout")
    except httpx.HTTPError:
        return MerchantReputation(merchant=merchant, mode="error")

    from brightdata_scoring import score_serp  # Task 5
    rep = score_serp(merchant, serp_json)
    _persist(rep)
    return rep
```

- [ ] **Step 5: Stub `brightdata_scoring.py` so the import resolves**

Create `backend/brightdata_scoring.py`:

```python
from models import MerchantReputation


def score_serp(merchant: str, serp_json: dict) -> MerchantReputation:
    return MerchantReputation(merchant=merchant, score=50, mode="scored")
```

- [ ] **Step 6: Run cache tests, confirm pass**

Run: `cd backend && ./venv/bin/python -m pytest test_brightdata.py -v`
Expected: all tests pass (the 3 from Task 3 + cache miss/hit test).

- [ ] **Step 7: Save checkpoint** (no git)

---

### Task 5: SERP scoring rules

**Files:**
- Create: `backend/test_brightdata_scoring.py`
- Modify: `backend/brightdata_scoring.py`

- [ ] **Step 1: Write failing scoring tests**

Create `backend/test_brightdata_scoring.py`:

```python
from brightdata_scoring import score_serp


def _serp(organic):
    return {"organic": organic}


def test_scamadviser_hit_lowers_score():
    rep = score_serp("BadCo", _serp([
        {"title": "BadCo scam alert", "description": "Avoid", "link": "https://www.scamadviser.com/check-website/badco.com"},
    ]))
    assert rep.mode == "scored"
    assert rep.score < 30
    assert any("scamadviser" in s.lower() for s in rep.signals)


def test_trustpilot_high_rating_raises_score():
    rep = score_serp("GoodCo", _serp([
        {"title": "GoodCo Reviews", "description": "Rated 4.7 / 5 based on 12,000 reviews", "link": "https://www.trustpilot.com/review/goodco.com"},
    ]))
    assert rep.score > 60
    assert any("trustpilot" in s.lower() for s in rep.signals)


def test_no_results_marks_unknown():
    rep = score_serp("NoSuchCo", _serp([]))
    assert rep.mode == "unknown"
    assert rep.score is None


def test_clamps_to_range():
    bad = [{"title": f"scam {i}", "description": "x",
            "link": f"https://www.scamadviser.com/{i}"} for i in range(10)]
    rep = score_serp("VeryBad", _serp(bad))
    assert rep.score == 0
```

- [ ] **Step 2: Run, confirm failure**

Run: `cd backend && ./venv/bin/python -m pytest test_brightdata_scoring.py -v`
Expected: 4 failures.

- [ ] **Step 3: Implement scoring**

Replace `backend/brightdata_scoring.py`:

```python
import re
from urllib.parse import urlparse

from models import MerchantReputation, MerchantReputationResult

SCAM_DOMAINS = {
    "scamadviser.com", "scam-detector.com", "fraud.org", "ripoffreport.com",
}
NEWS_DOMAINS = {
    "nytimes.com", "reuters.com", "bbc.com", "wsj.com", "ft.com", "bloomberg.com",
}
TRUSTPILOT_RE = re.compile(r"(\d(?:\.\d)?)\s*/\s*5", re.IGNORECASE)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def score_serp(merchant: str, serp_json: dict) -> MerchantReputation:
    organic = serp_json.get("organic", [])[:5]
    if not organic:
        return MerchantReputation(merchant=merchant, mode="unknown")

    score = 50
    signals: list[str] = []
    top: list[MerchantReputationResult] = []
    scam_hits = 0

    for item in organic:
        title = item.get("title", "")
        snippet = item.get("description", "") or item.get("snippet", "")
        url = item.get("link", "") or item.get("url", "")
        domain = _domain(url)
        text = f"{title} {snippet}".lower()

        top.append(MerchantReputationResult(
            title=title, snippet=snippet, url=url, source_domain=domain,
        ))

        if any(domain.endswith(d) for d in SCAM_DOMAINS):
            scam_hits += 1
            signals.append(f"{domain} flag")
            continue
        if "trustpilot.com" in domain:
            m = TRUSTPILOT_RE.search(snippet) or TRUSTPILOT_RE.search(title)
            if m:
                rating = float(m.group(1))
                if rating >= 4.5:
                    score += 20
                    signals.append(f"Trustpilot {rating}★")
                elif rating <= 2.0:
                    score -= 25
                    signals.append(f"Trustpilot {rating}★ (low)")
            continue
        if "bbb.org" in domain:
            score += 15
            signals.append("BBB listing")
            continue
        if "reddit.com" in domain and "r/scams" in url.lower():
            score -= 20
            signals.append("Reddit r/scams hit")
            continue
        if any(domain.endswith(d) for d in NEWS_DOMAINS):
            score += 10
            signals.append(f"News mention ({domain})")

    score -= min(scam_hits, 2) * 30  # cap scam penalty at -60
    score = max(0, min(100, score))
    return MerchantReputation(
        merchant=merchant, score=score, mode="scored",
        signals=signals, top_results=top,
    )
```

- [ ] **Step 4: Run all backend tests, confirm pass**

Run: `cd backend && ./venv/bin/python -m pytest test_brightdata.py test_brightdata_scoring.py -v`
Expected: all green.

- [ ] **Step 5: Save checkpoint** (no git)

---

### Task 6: Bright Data failure-mode tests

**Files:**
- Modify: `backend/test_brightdata.py`

- [ ] **Step 1: Add timeout + 5xx tests**

Append to `backend/test_brightdata.py`:

```python
@respx.mock
def test_timeout_returns_timeout_mode(monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
    _clear_cache()
    respx.post("https://api.brightdata.com/request").mock(
        side_effect=httpx.TimeoutException("slow")
    )
    rep = lookup_merchant("SlowCo")
    assert rep.mode == "timeout"
    assert rep.cached is False


@respx.mock
def test_5xx_returns_error_mode(monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
    _clear_cache()
    respx.post("https://api.brightdata.com/request").mock(
        return_value=httpx.Response(503, text="server error")
    )
    rep = lookup_merchant("DownCo")
    assert rep.mode == "error"
```

- [ ] **Step 2: Run, confirm pass** (the client already handles these)

Run: `cd backend && ./venv/bin/python -m pytest test_brightdata.py -v`
Expected: all pass.

- [ ] **Step 3: Save checkpoint** (no git)

---

## Phase 2 — AI/ML API Client

### Task 7: aimlapi.py thin client

**Files:**
- Create: `backend/aimlapi.py`
- Create: `backend/test_aimlapi.py`

- [ ] **Step 1: Write failing test (disabled + happy path with mocked OpenAI client)**

Create `backend/test_aimlapi.py`:

```python
import os
from unittest.mock import MagicMock, patch

from aimlapi import chat_completion, is_enabled


def test_disabled_without_key(monkeypatch):
    monkeypatch.setenv("AIMLAPI_KEY", "")
    assert is_enabled() is False


def test_enabled_with_key(monkeypatch):
    monkeypatch.setenv("AIMLAPI_KEY", "real")
    assert is_enabled() is True


def test_chat_completion_calls_openai_client(monkeypatch):
    monkeypatch.setenv("AIMLAPI_KEY", "real")
    monkeypatch.setenv("AIMLAPI_MODEL", "gpt-4o-mini")

    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="Risk: HIGH\nExplanation: bad"))]
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_resp

    with patch("aimlapi._client", return_value=fake_client):
        text = chat_completion([{"role": "user", "content": "hi"}])

    assert "HIGH" in text
    fake_client.chat.completions.create.assert_called_once()
```

- [ ] **Step 2: Run, confirm failure**

Run: `cd backend && ./venv/bin/python -m pytest test_aimlapi.py -v`
Expected: `ModuleNotFoundError: No module named 'aimlapi'`.

- [ ] **Step 3: Implement `aimlapi.py`**

```python
import os

from openai import OpenAI


def is_enabled() -> bool:
    key = os.getenv("AIMLAPI_KEY", "").strip()
    return key not in ("", "your_key_here")


def _base_url() -> str:
    return os.getenv("AIMLAPI_BASE_URL", "https://api.aimlapi.com/v1")


def _model() -> str:
    return os.getenv("AIMLAPI_MODEL", "gpt-4o-mini")


def _client() -> OpenAI:
    return OpenAI(base_url=_base_url(), api_key=os.getenv("AIMLAPI_KEY"))


def chat_completion(messages: list[dict]) -> str:
    resp = _client().chat.completions.create(
        model=_model(), messages=messages, temperature=0.0, max_tokens=500,
    )
    return resp.choices[0].message.content or ""
```

- [ ] **Step 4: Run, confirm pass**

Run: `cd backend && ./venv/bin/python -m pytest test_aimlapi.py -v`
Expected: 3 passed.

- [ ] **Step 5: Save checkpoint** (no git)

---

## Phase 3 — Agent Wiring

### Task 8: Agent — provider selection + reputation in prompt + heuristic floor

**Files:**
- Modify: `backend/agent.py` (lines 30–34 for provider init, lines 62–78 for `_build_prompt`, lines 95–113 for `_heuristic`, lines 164+ for `analyze_transaction`)

- [ ] **Step 1: Replace LLM client init with provider-selection block**

In `backend/agent.py`, replace lines around 30–34 (the `_api_key`, `_use_mock`, `client = ...` lines):

```python
import aimlapi
from brightdata import lookup_merchant

_deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
_use_aimlapi = aimlapi.is_enabled()
_use_deepseek = (not _use_aimlapi) and _deepseek_key not in ("", "your_key_here")
_use_mock = not (_use_aimlapi or _use_deepseek)

deepseek_client = (
    OpenAI(base_url=DEEPSEEK_BASE_URL, api_key=_deepseek_key)
    if _use_deepseek else None
)
```

- [ ] **Step 2: Extend `_build_prompt` to include reputation block**

Change the signature of `_build_prompt` to accept a `reputation: MerchantReputation | None` parameter. Inside the function, when `reputation` is not None and `reputation.mode == "scored"`, append a block like:

```
Web reputation for merchant "{reputation.merchant}":
  Score: {reputation.score}/100
  Signals: {", ".join(reputation.signals) or "none"}
```

When `mode in ("disabled","unknown","timeout","error")` — append `Web reputation: unavailable ({mode}).` Add `from models import MerchantReputation` to the imports if not present.

- [ ] **Step 3: Extend `_heuristic` to apply the reputation floor**

Change `_heuristic` signature to accept `reputation: MerchantReputation | None`. After computing the existing risk_level, if `reputation and reputation.score is not None and reputation.score < 30`:

```python
risk_level = _max_risk(risk_level, "MEDIUM")  # bump LOW -> MEDIUM
if reputation.score < 15:
    risk_level = _max_risk(risk_level, "HIGH")
explanation = f"{explanation} | Web reputation low ({reputation.score})"
```

- [ ] **Step 4: Wire reputation into `analyze_transaction`**

At the top of `analyze_transaction` (after the existing velocity/geo/structuring checks but before the LLM call), add:

```python
reputation = lookup_merchant(transaction.merchant)
```

Pass `reputation` into both `_build_prompt(...)` and `_heuristic(...)` calls.

Replace the LLM call so it routes through whichever provider is selected:

```python
if _use_aimlapi:
    raw = aimlapi.chat_completion([
        {"role": "system", "content": "You are a fraud detection analyst."},
        {"role": "user", "content": prompt},
    ])
elif _use_deepseek:
    completion = deepseek_client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "system", "content": "You are a fraud detection analyst."},
                  {"role": "user", "content": prompt}],
        temperature=0.0, max_tokens=500,
    )
    raw = completion.choices[0].message.content or ""
else:
    raise RuntimeError("No LLM provider configured")  # caught below
```

Keep the existing try/except around the LLM call so it falls back to `_heuristic(transaction, avg, reputation)` on any exception (and when `_use_mock`).

Add `reputation` fields to the dict returned by `analyze_transaction`:

```python
result["web_rep_score"] = reputation.score
result["web_rep_mode"] = reputation.mode
result["web_rep_signals"] = reputation.signals
result["web_rep_cached"] = reputation.cached
```

- [ ] **Step 5: Quick sanity run**

Run: `cd backend && ./venv/bin/python -c "from agent import analyze_transaction; print('imports OK')"`
Expected: prints `imports OK`.

- [ ] **Step 6: Save checkpoint** (no git)

---

### Task 9: Agent integration tests — reputation drives decisions

**Files:**
- Modify: `backend/test_agent.py`

- [ ] **Step 1: Add 3 new test functions**

Append to `backend/test_agent.py` (keep existing `run()` intact):

```python
from unittest.mock import patch
from models import MerchantReputation


def _fake_rep(score, mode="scored"):
    return MerchantReputation(merchant="X", score=score, mode=mode)


def test_low_reputation_bumps_low_to_medium():
    cursor.execute("INSERT OR REPLACE INTO users (id, name, account_frozen) VALUES (?,?,0)", ("u2","Bob"))
    conn.commit()
    txn = Transaction(id="rep-low", user_id="u2", amount=50.0, location="NYC",
                      timestamp="2026-05-28T12:00:00", merchant="ShadyVendor")
    with patch("agent.lookup_merchant", return_value=_fake_rep(20)), \
         patch("agent._use_mock", True):
        result = analyze_transaction(txn)
    assert result["risk_level"] in ("MEDIUM", "HIGH")
    assert result["web_rep_score"] == 20


def test_high_reputation_keeps_low():
    cursor.execute("INSERT OR REPLACE INTO users (id, name, account_frozen) VALUES (?,?,0)", ("u3","Carol"))
    conn.commit()
    txn = Transaction(id="rep-hi", user_id="u3", amount=50.0, location="NYC",
                      timestamp="2026-05-28T12:00:00", merchant="Starbucks")
    with patch("agent.lookup_merchant", return_value=_fake_rep(85)), \
         patch("agent._use_mock", True):
        result = analyze_transaction(txn)
    assert result["risk_level"] == "LOW"
    assert result["web_rep_score"] == 85


def test_reputation_disabled_does_not_break_flow():
    cursor.execute("INSERT OR REPLACE INTO users (id, name, account_frozen) VALUES (?,?,0)", ("u4","Dan"))
    conn.commit()
    txn = Transaction(id="rep-off", user_id="u4", amount=50.0, location="NYC",
                      timestamp="2026-05-28T12:00:00", merchant="Anywhere")
    with patch("agent.lookup_merchant", return_value=_fake_rep(None, mode="disabled")), \
         patch("agent._use_mock", True):
        result = analyze_transaction(txn)
    assert result["risk_level"] == "LOW"
    assert result["web_rep_mode"] == "disabled"
```

- [ ] **Step 2: Run all backend tests**

Run: `cd backend && ./venv/bin/python -m pytest -v`
Expected: all green. The original `test_agent.run()` is not auto-discovered (no `test_` prefix), so it's safe to leave.

- [ ] **Step 3: Save checkpoint** (no git)

---

## Phase 4 — API Surface

### Task 10: Persist + expose web_rep fields on /analyze and /transactions

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/database.py` (find the `INSERT INTO transactions` statement)

- [ ] **Step 1: Locate the INSERT — it lives inline in `main.py /analyze`**

There is no `save_transaction` helper in `database.py`; the INSERT is inline in `main.py`'s `/analyze` handler. Open `backend/main.py`, find the `INSERT INTO transactions (...)` SQL inside the analyze handler.

- [ ] **Step 2: Extend the INSERT columns and bindings**

Add `web_rep_score, web_rep_signals, web_rep_cached` to the column list and three more `?` placeholders. Pass the values from the `result` dict returned by `analyze_transaction`:

```python
cursor.execute(
    "INSERT INTO transactions (... existing cols ..., web_rep_score, web_rep_signals, web_rep_cached) "
    "VALUES (..., ?, ?, ?)",
    (..., result.get("web_rep_score"),
          json.dumps(result.get("web_rep_signals", [])),
          1 if result.get("web_rep_cached") else 0),
)
```

Add `import json` to `main.py` if not already present.

- [ ] **Step 3: Update `GET /transactions` to return the new fields**

In the SELECT statement, add `web_rep_score, web_rep_signals, web_rep_cached`. In the row-to-dict mapping, expose them as:

```python
"web_rep_score": row["web_rep_score"],
"web_rep_top_signals": json.loads(row["web_rep_signals"]) if row["web_rep_signals"] else [],
"web_rep_cached": bool(row["web_rep_cached"]) if row["web_rep_cached"] is not None else None,
```

- [ ] **Step 4: Smoke test the endpoint**

Restart backend (`cd backend && uvicorn main:app --reload` in a separate shell). Then:

Run: `curl -s -H "X-API-Key: sentinel-dev-key" http://localhost:8000/transactions | head -c 400`
Expected: JSON includes `"web_rep_score"` and `"web_rep_top_signals"` keys (may be null/empty until a /analyze runs).

- [ ] **Step 5: Save checkpoint** (no git)

---

### Task 11: New endpoint — GET /transactions/{id}/web-rep

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add the endpoint**

After the existing `/transactions` route:

```python
@app.get("/transactions/{txn_id}/web-rep")
def get_web_rep(txn_id: str, _: None = Depends(require_api_key)):
    cursor.execute("SELECT merchant FROM transactions WHERE id = ?", (txn_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="transaction not found")
    merchant = row[0]
    cursor.execute(
        "SELECT score, mode, signals, top_results, fetched_at "
        "FROM merchant_reputation WHERE merchant = ?", (merchant,),
    )
    rep = cursor.fetchone()
    if not rep:
        return {"merchant": merchant, "mode": "unknown", "score": None,
                "signals": [], "top_results": [], "fetched_at": None}
    score, mode, signals, top_results, fetched_at = rep
    return {"merchant": merchant, "score": score, "mode": mode,
            "signals": json.loads(signals), "top_results": json.loads(top_results),
            "fetched_at": fetched_at}
```

Add `import json` if not already imported.

- [ ] **Step 2: Smoke test**

Run: `curl -s -H "X-API-Key: sentinel-dev-key" http://localhost:8000/transactions/some-id/web-rep`
Expected: either a 404 (if id unknown) or the JSON shape above.

- [ ] **Step 3: Save checkpoint** (no git)

---

## Phase 5 — Frontend

### Task 12: Extend Transaction type in TransactionContext

**Files:**
- Modify: `frontend/app/context/TransactionContext.tsx` (Transaction type at ~line 21)

- [ ] **Step 1: Add fields**

```ts
export type Transaction = {
  // ...existing fields...
  web_rep_score: number | null;
  web_rep_cached: boolean | null;
  web_rep_top_signals: string[] | null;
};
```

- [ ] **Step 2: Save checkpoint** (no git)

---

### Task 13: WebRepBadge component

**Files:**
- Create: `frontend/app/components/WebRepBadge.tsx`

- [ ] **Step 1: Create the component**

```tsx
type Props = {
  score: number | null;
  cached: boolean | null;
  loading?: boolean;
};

function classify(score: number | null) {
  if (score == null) return { color: "bg-gray-200 text-gray-700", label: "—" };
  if (score < 30) return { color: "bg-red-200 text-red-900", label: String(score) };
  if (score <= 70) return { color: "bg-yellow-200 text-yellow-900", label: String(score) };
  return { color: "bg-green-200 text-green-900", label: String(score) };
}

export function WebRepBadge({ score, cached, loading }: Props) {
  if (loading) return <span className="text-xs text-blue-600">🌐 Live web lookup…</span>;
  const { color, label } = classify(score);
  return (
    <span className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-semibold ${color}`}>
      {label}
      {cached ? <span title="cached" className="opacity-60">·c</span> : null}
    </span>
  );
}
```

- [ ] **Step 2: Save checkpoint** (no git)

---

### Task 14: WebRepDetailModal

**Files:**
- Create: `frontend/app/components/WebRepDetailModal.tsx`

- [ ] **Step 1: Create the modal**

```tsx
"use client";
import { useEffect, useState } from "react";

type WebRepDetail = {
  merchant: string;
  score: number | null;
  mode: string;
  signals: string[];
  top_results: { title: string; snippet: string; url: string; source_domain: string }[];
  fetched_at: string | null;
};

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY = process.env.NEXT_PUBLIC_API_KEY || "sentinel-dev-key";

export function WebRepDetailModal({ txnId, onClose }: { txnId: string; onClose: () => void }) {
  const [data, setData] = useState<WebRepDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/transactions/${txnId}/web-rep`, { headers: { "X-API-Key": KEY } })
      .then((r) => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(setData).catch((e) => setErr(String(e)));
  }, [txnId]);

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg p-6 max-w-2xl w-full max-h-[80vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold">Web Reputation</h2>
          <button onClick={onClose} className="text-gray-500">✕</button>
        </div>
        {err && <p className="text-red-600">Error: {err}</p>}
        {!data && !err && <p>Loading…</p>}
        {data && (
          <>
            <p className="text-sm mb-2"><strong>{data.merchant}</strong> — score {data.score ?? "n/a"} ({data.mode})</p>
            <p className="text-xs text-gray-500 mb-3">Fetched: {data.fetched_at ?? "never"}</p>
            <div className="mb-3"><strong>Signals:</strong> {data.signals.length ? data.signals.join(", ") : "none"}</div>
            <ul className="space-y-3">
              {data.top_results.map((r, i) => (
                <li key={i} className="border-b pb-2">
                  <a href={r.url} target="_blank" className="text-blue-600 font-medium">{r.title}</a>
                  <p className="text-xs text-gray-500">{r.source_domain}</p>
                  <p className="text-sm text-gray-700">{r.snippet}</p>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Save checkpoint** (no git)

---

### Task 15: Wire the new column into page.tsx

**Files:**
- Modify: `frontend/app/page.tsx`

- [ ] **Step 1: Import the new components and add state**

At top of `Dashboard()`:

```tsx
import { useState } from "react";
import { WebRepBadge } from "./components/WebRepBadge";
import { WebRepDetailModal } from "./components/WebRepDetailModal";

const [openTxnId, setOpenTxnId] = useState<string | null>(null);
```

- [ ] **Step 2: Add header cell + body cell**

In the `<thead>`, insert a new `<th className="px-4 py-3">Web Rep</th>` between "Risk" and "Explanation".

In the row map, insert a corresponding `<td>` after the Risk cell:

```tsx
<td className="px-4 py-3 cursor-pointer" onClick={() => setOpenTxnId(t.id)}>
  <WebRepBadge score={t.web_rep_score} cached={t.web_rep_cached} />
</td>
```

Also bump the empty-state `colSpan={7}` to `colSpan={8}`.

- [ ] **Step 3: Render the modal**

At the end of the `Dashboard()` JSX (before the closing fragment), add:

```tsx
{openTxnId && <WebRepDetailModal txnId={openTxnId} onClose={() => setOpenTxnId(null)} />}
```

- [ ] **Step 4: Verify in browser**

Run: `cd frontend && npm run dev` (in a separate shell if not already running). Open `http://localhost:3000`.
Expected: page renders with new "Web Rep" column; existing transactions show `—` badge; click does nothing destructive even on missing data.

- [ ] **Step 5: Save checkpoint** (no git)

---

## Phase 6 — Demo + Smoke Verification

### Task 16: Extend simulate_attack.sh with known-good and known-bad merchants

**Files:**
- Modify: `scripts/simulate_attack.sh`

- [ ] **Step 1: Add two transactions to the existing script**

After the existing "normal" loop and before the "HIGH-risk" loop, add these two calls (match the existing script's variable names — `API`, `API_KEY`, etc.):

```bash
echo "→ Known-good merchant (Starbucks) — expect green badge"
curl -s -X POST "$API/analyze" \
  -H "Content-Type: application/json" -H "X-API-Key: $API_KEY" \
  -d '{"id":"rep-good-1","user_id":"u-demo","amount":25.00,"location":"Seattle","timestamp":"2026-05-28T10:00:00","merchant":"Starbucks"}' \
  | head -c 200; echo

echo "→ Known-bad merchant (FreeMoneyCryptoLottery) — expect red badge"
curl -s -X POST "$API/analyze" \
  -H "Content-Type: application/json" -H "X-API-Key: $API_KEY" \
  -d '{"id":"rep-bad-1","user_id":"u-demo","amount":40.00,"location":"Online","timestamp":"2026-05-28T10:01:00","merchant":"FreeMoneyCryptoLottery"}' \
  | head -c 200; echo
```

If the existing script doesn't have `$API` / `$API_KEY` vars, define them at the top: `API=http://localhost:8000`, `API_KEY=sentinel-dev-key`. Amounts are modest so the reputation signal — not the amount — drives any flag.

- [ ] **Step 2: Run the script and observe**

Run: `cd '/Users/rahulmeena/VIKRAM PROJECT' && ./scripts/simulate_attack.sh`
Expected: dashboard shows Starbucks row with a high/green badge and FreeMoneyCryptoLottery with a low/red badge (if `BRIGHTDATA_API_KEY` is configured) or `—` badges in disabled mode.

- [ ] **Step 3: Save checkpoint** (no git)

---

### Task 17: Update .env.example + run final end-to-end verification

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Append the new env keys**

```
# Bright Data SERP API (Web Data UNLOCKED hackathon — main track)
BRIGHTDATA_API_KEY=
BRIGHTDATA_SERP_ZONE=serp_api1
BRIGHTDATA_TIMEOUT_SECONDS=5
MERCHANT_REPUTATION_TTL_HOURS=24

# AI/ML API (Web Data UNLOCKED hackathon — partner bonus)
AIMLAPI_KEY=
AIMLAPI_BASE_URL=https://api.aimlapi.com/v1
AIMLAPI_MODEL=gpt-4o-mini
```

- [ ] **Step 2: Run the full backend test suite**

Run: `cd backend && ./venv/bin/python -m pytest -v`
Expected: all green.

- [ ] **Step 3: Manual smoke checklist**

With backend + frontend both running, real keys in `.env`:

1. POST a transaction with merchant `Starbucks` → row appears, badge shows live lookup ~1-2s, settles to green.
2. POST a second `Starbucks` transaction → badge appears instantly, marked cached.
3. POST a transaction with merchant `FreeMoneyCryptoLottery` → badge settles to red, risk level is MEDIUM or HIGH even if amount is small.
4. Click the red badge → modal opens with top web evidence.
5. `curl /transactions/<id>/web-rep` returns the stored JSON.

- [ ] **Step 4: Save checkpoint** (no git)

---

## Post-Implementation Submission Checklist

(For the lablab.ai submission form, not implementation tasks)

- [ ] Demo video recorded (2 min, hits all 5 smoke-checklist items).
- [ ] README updated with setup instructions for both new env keys.
- [ ] Screenshot of dashboard with green + red badges visible.
- [ ] Architecture diagram from spec §4 exported as PNG.
- [ ] Submission writeup names Bright Data SERP API and AI/ML API explicitly.
- [ ] Project labeled with Security & Compliance main track + AI/ML API partner bonus.
