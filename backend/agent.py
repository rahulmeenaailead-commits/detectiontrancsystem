import os
from datetime import datetime, timedelta, timezone

from openai import OpenAI

from brightdata import lookup_merchant, lookup_merchant_cached
from models import MerchantReputation, Transaction
from database import (
    count_recent_transactions,
    freeze_user,
    get_last_transaction,
    get_recent_transactions,
    get_user_average,
    sum_recent_transactions,
)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

RISK_SCORES = {"LOW": 0.0, "MEDIUM": 0.5, "HIGH": 1.0}
RISK_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

HARD_AMOUNT_THRESHOLD = float(os.getenv("SENTINEL_HARD_AMOUNT", "5000"))
RATIO_THRESHOLD = float(os.getenv("SENTINEL_RATIO_THRESHOLD", "30"))
VELOCITY_WINDOW_MIN = int(os.getenv("SENTINEL_VELOCITY_WIN_MIN", "5"))
VELOCITY_COUNT_LIMIT = int(os.getenv("SENTINEL_VELOCITY_COUNT", "5"))
GEO_VELOCITY_WINDOW_MIN = int(os.getenv("SENTINEL_GEO_WIN_MIN", "5"))
STRUCTURING_WINDOW_MIN = int(os.getenv("SENTINEL_STRUCT_WIN_MIN", "60"))
STRUCTURING_SUM_THRESHOLD = float(os.getenv("SENTINEL_STRUCT_SUM", "20000"))

# LLM provider selection (boot-time): DeepSeek > heuristic-only mock.
_deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
_use_deepseek = _deepseek_key not in ("", "your_key_here")
_use_mock = not _use_deepseek

deepseek_client = (
    OpenAI(base_url=DEEPSEEK_BASE_URL, api_key=_deepseek_key) if _use_deepseek else None
)


def _parse_ts(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _max_risk(*risks: str) -> str:
    return max(risks, key=lambda r: RISK_RANK.get(r, 0))


def _format_history(history: list[dict]) -> str:
    if not history:
        return "  (no prior transactions)"
    lines = []
    for h in history:
        lines.append(
            f"  - ${h['amount']:.2f} at {h.get('merchant', '?')} "
            f"({h.get('location', '?')}) on {h.get('timestamp', '?')}"
        )
    return "\n".join(lines)


def _reputation_block(reputation: MerchantReputation | None) -> str:
    if reputation is None:
        return ""
    if reputation.mode == "scored":
        return (
            f'\nWeb reputation for merchant "{reputation.merchant}":\n'
            f"- Score: {reputation.score}/100 (0=worst, 100=best)\n"
            f'- Signals: {", ".join(reputation.signals) or "none"}\n'
        )
    return f"\nWeb reputation: unavailable ({reputation.mode}).\n"


def _build_prompt(
    transaction: Transaction,
    avg: float,
    history: list[dict],
    reputation: MerchantReputation | None = None,
) -> str:
    return (
        "You are a fraud detection analyst for a bank's compliance team.\n\n"
        "Transaction under review:\n"
        f"- Amount: ${transaction.amount}\n"
        f"- Merchant: {transaction.merchant}\n"
        f"- Location: {transaction.location}\n"
        f"- Timestamp: {transaction.timestamp}\n"
        f"- User's average transaction amount (last 10): ${avg:.2f}\n"
        f"{_reputation_block(reputation)}\n"
        f"Recent history (most recent first):\n{_format_history(history)}\n\n"
        "Classify the risk as LOW, MEDIUM, or HIGH, then write a one-paragraph "
        "plain-English explanation suitable for a bank compliance audit.\n\n"
        "Respond in EXACTLY this format:\n"
        "RISK: <LOW|MEDIUM|HIGH>\n"
        "EXPLANATION: <one paragraph>\n"
    )


def _parse_response(text: str) -> tuple[str, str]:
    risk = "MEDIUM"
    explanation = text.strip()
    for line in text.splitlines():
        upper = line.upper()
        if upper.startswith("RISK:"):
            for level in ("HIGH", "MEDIUM", "LOW"):
                if level in upper:
                    risk = level
                    break
        elif upper.startswith("EXPLANATION:"):
            explanation = line.split(":", 1)[1].strip()
    return risk, explanation


def _heuristic(
    transaction: Transaction,
    avg: float,
    reputation: MerchantReputation | None = None,
) -> tuple[str, str]:
    baseline = avg if avg > 0 else 100.0
    ratio = transaction.amount / baseline
    if ratio >= RATIO_THRESHOLD or transaction.amount >= HARD_AMOUNT_THRESHOLD:
        risk = "HIGH"
        explanation = (
            f"Transaction of ${transaction.amount:.2f} at {transaction.merchant} "
            f"({transaction.location}) is {ratio:.1f}x this user's recent average "
            f"of ${baseline:.2f}. Recommend immediate account freeze."
        )
    elif ratio >= 5:
        risk = "MEDIUM"
        explanation = (
            f"Amount ${transaction.amount:.2f} is {ratio:.1f}x the user's recent "
            f"average (${baseline:.2f}). Recommend secondary verification."
        )
    else:
        risk = "LOW"
        explanation = (
            f"Amount ${transaction.amount:.2f} is within normal range "
            f"(user avg ${baseline:.2f})."
        )

    # Reputation floor: a low web-reputation merchant can only raise the risk.
    if reputation is not None and reputation.score is not None and reputation.score < 30:
        risk = _max_risk(risk, "MEDIUM")
        if reputation.score < 15:
            risk = _max_risk(risk, "HIGH")
        explanation = f"{explanation} | Web reputation low ({reputation.score})."

    return risk, explanation


def _check_velocity(transaction: Transaction) -> tuple[str, str | None]:
    now = _parse_ts(transaction.timestamp) or datetime.now(timezone.utc)
    since = (now - timedelta(minutes=VELOCITY_WINDOW_MIN)).isoformat()
    count = count_recent_transactions(transaction.user_id, since)
    if count >= VELOCITY_COUNT_LIMIT:
        return "HIGH", (
            f"Velocity anomaly: {count} transactions in the last "
            f"{VELOCITY_WINDOW_MIN} minutes for user {transaction.user_id} "
            f"(threshold {VELOCITY_COUNT_LIMIT}). Pattern consistent with card testing."
        )
    return "LOW", None


def _check_geo_velocity(transaction: Transaction) -> tuple[str, str | None]:
    last = get_last_transaction(transaction.user_id)
    if not last:
        return "LOW", None
    if (last.get("location") or "").strip() == (transaction.location or "").strip():
        return "LOW", None
    last_ts = _parse_ts(last.get("timestamp") or "")
    cur_ts = _parse_ts(transaction.timestamp)
    if not last_ts or not cur_ts:
        return "LOW", None
    delta = abs((cur_ts - last_ts).total_seconds()) / 60.0
    if delta <= GEO_VELOCITY_WINDOW_MIN:
        return "HIGH", (
            f"Impossible-travel: prior transaction at '{last['location']}' "
            f"~{delta:.1f} minutes ago; current at '{transaction.location}'. "
            "Geo pattern inconsistent with physical travel."
        )
    return "LOW", None


def _check_structuring(transaction: Transaction) -> tuple[str, str | None]:
    now = _parse_ts(transaction.timestamp) or datetime.now(timezone.utc)
    since = (now - timedelta(minutes=STRUCTURING_WINDOW_MIN)).isoformat()
    rolling_sum = sum_recent_transactions(transaction.user_id, since) + transaction.amount
    if (
        rolling_sum >= STRUCTURING_SUM_THRESHOLD
        and transaction.amount < HARD_AMOUNT_THRESHOLD
    ):
        return "MEDIUM", (
            f"Possible structuring: rolling {STRUCTURING_WINDOW_MIN}-min total "
            f"${rolling_sum:.2f} across multiple sub-threshold transactions "
            f"exceeds aggregation limit ${STRUCTURING_SUM_THRESHOLD:.0f}."
        )
    return "LOW", None


def _rule_layer(
    transaction: Transaction, reputation: MerchantReputation
) -> tuple[float, str, str, list[str]]:
    """Deterministic rule layer — pure DB reads, no network, no LLM.

    Returns (avg, rule_risk, floor_reason, rule_notes). This is the floor the
    LLM/enrichment can only raise, never weaken.
    """
    avg = get_user_average(transaction.user_id)
    floor_risk, floor_reason = _heuristic(transaction, avg, reputation)
    vel_risk, vel_reason = _check_velocity(transaction)
    geo_risk, geo_reason = _check_geo_velocity(transaction)
    struct_risk, struct_reason = _check_structuring(transaction)

    rule_risk = _max_risk(floor_risk, vel_risk, geo_risk, struct_risk)
    rule_notes = [n for n in (vel_reason, geo_reason, struct_reason) if n]
    return avg, rule_risk, floor_reason, rule_notes


def _finalize(
    transaction: Transaction,
    risk: str,
    explanation: str,
    reputation: MerchantReputation,
) -> dict:
    """Apply the autonomous action (freeze on HIGH) and shape the verdict dict."""
    fraud_score = RISK_SCORES.get(risk, 0.5)
    action_taken = "none"
    if risk == "HIGH":
        freeze_user(transaction.user_id)
        action_taken = "account_frozen"

    return {
        "risk_level": risk,
        "fraud_score": fraud_score,
        "explanation": explanation,
        "action_taken": action_taken,
        "web_rep_score": reputation.score,
        "web_rep_mode": reputation.mode,
        "web_rep_signals": reputation.signals,
        "web_rep_cached": reputation.cached,
    }


def analyze_transaction_fast(transaction: Transaction) -> dict:
    """Immediate deterministic verdict — no network, no LLM.

    Uses only cached merchant reputation so the /analyze response (and the
    dashboard row) is never stuck at 'pending' while a live Bright Data SERP
    lookup or DeepSeek call runs. The slow web-reputation + LLM enrichment
    happens afterward via analyze_transaction() in a background task and can
    only escalate the risk.
    """
    reputation = lookup_merchant_cached(transaction.merchant)
    _avg, rule_risk, floor_reason, rule_notes = _rule_layer(transaction, reputation)

    explanation = floor_reason
    if rule_notes:
        explanation = explanation + " " + " ".join(rule_notes)

    return _finalize(transaction, rule_risk, explanation, reputation)


def analyze_transaction(transaction: Transaction) -> dict:
    """Full verdict: live web reputation + LLM, layered over the rule floor.

    This is the slow path (live Bright Data SERP + DeepSeek). It runs as a
    background enrichment after analyze_transaction_fast has already produced
    an immediate verdict.
    """
    history = get_recent_transactions(transaction.user_id, limit=10)

    # Live web reputation for the merchant (cached; disabled-safe).
    reputation = lookup_merchant(transaction.merchant)

    # Deterministic rule layer first — provides a floor the LLM cannot weaken.
    avg, rule_risk, floor_reason, rule_notes = _rule_layer(transaction, reputation)

    if _use_mock:
        risk = rule_risk
        explanation = floor_reason
        if rule_notes:
            explanation = explanation + " " + " ".join(rule_notes)
    else:
        try:
            prompt = _build_prompt(transaction, avg, history, reputation)
            response = deepseek_client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": "You are an expert fraud detection analyst."},
                    {"role": "user", "content": prompt},
                ],
            )
            text = response.choices[0].message.content or ""
            llm_risk, llm_explanation = _parse_response(text)
            risk = _max_risk(llm_risk, rule_risk)
            explanation = llm_explanation
            if rule_notes:
                explanation = explanation + " Rule signals: " + " ".join(rule_notes)
        except Exception as e:
            risk = rule_risk
            explanation = f"[fallback after API error: {e}] {floor_reason}"
            if rule_notes:
                explanation = explanation + " " + " ".join(rule_notes)

    return _finalize(transaction, risk, explanation, reputation)
