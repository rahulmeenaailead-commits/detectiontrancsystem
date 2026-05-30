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
        return urlparse(url).netloc.lower().removeprefix("www.")
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
