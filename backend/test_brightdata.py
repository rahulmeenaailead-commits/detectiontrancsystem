import os
from unittest.mock import patch

import httpx
import respx

from brightdata import lookup_merchant
from database import conn, cursor


def _clear_cache():
    cursor.execute("DELETE FROM merchant_reputation")
    conn.commit()


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


@respx.mock
def test_cache_miss_then_hit(monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
    monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_test")
    _clear_cache()

    fake_serp = {
        "organic": [
            {
                "title": "Acme Corp - Trusted Vendor",
                "description": "Rated 4.6 / 5 based on 2,000 reviews on Trustpilot",
                "link": "https://www.trustpilot.com/review/acme.com",
            }
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
