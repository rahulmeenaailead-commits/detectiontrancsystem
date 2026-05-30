import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

# Load the project-root .env deterministically, regardless of the directory
# uvicorn is launched from. A stale backend/.env (older DeepSeek key only) would
# otherwise shadow it when started via `cd backend && uvicorn`, dropping the
# Bright Data config and silently disabling merchant-reputation lookups.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from models import Transaction
from database import (
    get_merchant_reputation,
    get_transaction_merchant,
    insert_transaction,
    is_user_frozen,
    list_transactions,
    unfreeze_user,
    update_transaction_verdict,
)
from agent import analyze_transaction, analyze_transaction_fast

API_KEY = os.getenv("SENTINEL_API_KEY", "sentinel-dev-key")
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
ANALYZE_RATE = os.getenv("SENTINEL_ANALYZE_RATE", "60/minute")

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Sentinel API")
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
def _ratelimit_handler(request: Request, exc: RateLimitExceeded):
    raise HTTPException(status_code=429, detail="Too many requests")


@app.exception_handler(RequestValidationError)
def _validation_handler(request: Request, exc: RequestValidationError):
    errors = [
        {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not API_KEY:
        return
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@app.get("/")
def health_check():
    return {"status": "ok", "service": "Sentinel"}


@app.get("/transactions")
def get_transactions(_: None = Depends(require_api_key)):
    return list_transactions()


@app.get("/transactions/{txn_id}/web-rep")
def get_web_rep(txn_id: str, _: None = Depends(require_api_key)):
    merchant = get_transaction_merchant(txn_id)
    if merchant is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    rep = get_merchant_reputation(merchant)
    if rep is None:
        return {
            "merchant": merchant, "mode": "unknown", "score": None,
            "signals": [], "top_results": [], "fetched_at": None,
        }
    return rep


def _write_verdict(tx_id: str, result: dict) -> None:
    account_frozen = 1 if result["action_taken"] == "account_frozen" else 0
    update_transaction_verdict(
        tx_id,
        result["fraud_score"],
        result["risk_level"],
        result["explanation"],
        account_frozen,
        result["action_taken"],
        web_rep_score=result.get("web_rep_score"),
        web_rep_signals=result.get("web_rep_signals", []),
        web_rep_cached=result.get("web_rep_cached"),
    )


def _enrich_transaction(transaction: Transaction) -> None:
    """Background: run the slow live web-reputation + LLM pass and overwrite the
    fast verdict. Enrichment can only escalate risk, never weaken the immediate
    deterministic decision. Any failure leaves the fast verdict in place."""
    try:
        result = analyze_transaction(transaction)
    except Exception:
        return
    _write_verdict(transaction.id, result)


@app.post("/analyze")
@limiter.limit(ANALYZE_RATE)
def analyze(
    request: Request,
    transaction: Transaction,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_api_key),
):
    if is_user_frozen(transaction.user_id):
        raise HTTPException(
            status_code=423,
            detail=f"Account {transaction.user_id} is frozen; transaction rejected.",
        )

    try:
        insert_transaction(transaction)
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"Transaction id '{transaction.id}' already exists.",
        )

    # Immediate deterministic verdict (no network / LLM) so the row is never
    # stuck at 'pending'. The slow live Bright Data + DeepSeek enrichment runs
    # in the background and can only raise the risk.
    result = analyze_transaction_fast(transaction)
    _write_verdict(transaction.id, result)
    background_tasks.add_task(_enrich_transaction, transaction)

    return {
        "transaction": transaction.model_dump(),
        **result,
        "account_frozen": bool(result["action_taken"] == "account_frozen"),
    }


@app.post("/unfreeze/{user_id}")
def unfreeze(user_id: str, _: None = Depends(require_api_key)):
    if not unfreeze_user(user_id):
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return {"user_id": user_id, "account_frozen": False}
