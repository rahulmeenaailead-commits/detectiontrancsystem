from brightdata_scoring import score_serp


def _serp(organic):
    return {"organic": organic}


def test_scamadviser_hit_lowers_score():
    rep = score_serp("BadCo", _serp([
        {"title": "BadCo scam alert", "description": "Avoid",
         "link": "https://www.scamadviser.com/check-website/badco.com"},
    ]))
    assert rep.mode == "scored"
    assert rep.score < 30
    assert any("scamadviser" in s.lower() for s in rep.signals)


def test_trustpilot_high_rating_raises_score():
    rep = score_serp("GoodCo", _serp([
        {"title": "GoodCo Reviews", "description": "Rated 4.7 / 5 based on 12,000 reviews",
         "link": "https://www.trustpilot.com/review/goodco.com"},
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


def test_top_results_captured_with_domain():
    rep = score_serp("MixedCo", _serp([
        {"title": "MixedCo on Reuters", "description": "news",
         "link": "https://www.reuters.com/markets/mixedco"},
    ]))
    assert len(rep.top_results) == 1
    assert rep.top_results[0].source_domain == "reuters.com"
