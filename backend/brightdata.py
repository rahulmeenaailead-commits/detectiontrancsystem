import json
import os
from datetime import datetime, timedelta, timezone

import httpx

from database import _lock, conn, cursor
from models import MerchantReputation, MerchantReputationResult

BRIGHTDATA_URL = "https://api.brightdata.com/request"


def _is_disabled() -> bool:
    key = os.getenv("BRIGHTDATA_API_KEY", "").strip()
    return key in ("", "your_key_here")


def _ttl_hours() -> int:
    return int(os.getenv("MERCHANT_REPUTATION_TTL_HOURS", "24"))


def _timeout() -> float:
    return float(os.getenv("BRIGHTDATA_TIMEOUT_SECONDS", "30"))


def _zone() -> str:
    return os.getenv("BRIGHTDATA_SERP_ZONE", "serp_api1")


def _load_cached(merchant: str) -> MerchantReputation | None:
    with _lock:
        cursor.execute(
            "SELECT score, mode, signals, top_results, fetched_at "
            "FROM merchant_reputation WHERE merchant = ?",
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
    with _lock:
        cursor.execute(
            "INSERT OR REPLACE INTO merchant_reputation "
            "(merchant, score, mode, signals, top_results, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                rep.merchant, rep.score, rep.mode,
                json.dumps(rep.signals),
                json.dumps([r.model_dump() for r in rep.top_results]),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def _fetch_serp(merchant: str) -> dict:
    query = f"{merchant} reviews scam complaints".replace(" ", "+")
    payload = {
        "zone": _zone(),
        "url": f"https://www.google.com/search?q={query}&brd_json=1",
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

    from brightdata_scoring import score_serp

    rep = score_serp(merchant, serp_json)
    _persist(rep)
    return rep


def lookup_merchant_cached(merchant: str) -> MerchantReputation:
    """Cached-only reputation lookup — never makes a network call.

    Used on the synchronous /analyze request path so a slow live SERP lookup
    (up to BRIGHTDATA_TIMEOUT_SECONDS) can't block the verdict and leave the
    dashboard row stuck at 'pending'. If the merchant isn't in the fresh cache
    we return a lightweight 'unknown' placeholder; the live fetch happens
    afterward via lookup_merchant() in a background task and only ever raises
    the risk.
    """
    if _is_disabled():
        return MerchantReputation(merchant=merchant, mode="disabled")
    if not merchant.strip():
        return MerchantReputation(merchant=merchant, mode="unknown")

    cached = _load_cached(merchant)
    if cached:
        return cached
    return MerchantReputation(merchant=merchant, mode="unknown")
