import daily_negatives
from keyword_review import junk_word, negative_rule


def term(text, cost, clicks, conversions=0.0, campaign="US - Search"):
    return {"campaign_id": 1, "campaign": campaign, "ad_group_id": 7, "ad_group": "Analytics", "text": text,
            "cost": cost, "clicks": clicks, "conversions": conversions}


def test_negative_rule():
    assert negative_rule("free analytics download", 0.5, 1, 0)[2] is False  # junk word, not held
    assert negative_rule("dashboard templates", 6.0, 3, 0)[1] == "dashboards"
    assert negative_rule("web analytics pricing", 6.0, 3, 0)[2] is True  # winning topic: held for the weekly
    assert negative_rule("web analytics pricing", 6.0, 3, 1) is None  # converted
    assert negative_rule("cheap thing", 1.0, 2, 0) is None  # under both floors
    assert negative_rule("cheap thing", 0.0, 10, 0) is not None  # click floor
    assert negative_rule("one pricey click", 9.0, 1, 0) is None  # cost floor needs negatives.min_cost_clicks clicks
    assert negative_rule("two pricey clicks", 9.0, 2, 0) is None
    assert negative_rule("three pricey clicks", 9.0, 3, 0) is not None
    assert negative_rule("free one click", 0.5, 1, 0) is not None  # a junk word needs one click only
    assert junk_word("Analytics JOBS") == "jobs"


def test_select_rule(use):
    use(**{"negatives.max_per_day": 2})
    terms = {(1, daily_negatives.norm(t["text"])): t for t in [
        term("free dashboard", 1.0, 2),
        term("dashboard templates", 9.0, 4),
        term("pdf report examples", 7.0, 3),
        term("already blocked thing", 8.0, 5),
        term("undone thing", 6.5, 5),
        term("analytics alternative", 12.0, 6),  # winning topic, no junk word: held
        term("reporting software", 2.0, 1),  # under the floors: not a negative
    ]}
    have = {1: {"already blocked thing"}}
    gone = {("US - Search", "undone thing")}
    to_add, held, over_cap, skipped = daily_negatives.select(terms, have, gone, added_today=0)
    assert [r["text"] for r in to_add] == ["dashboard templates", "pdf report examples"]  # highest cost first, cap 2
    assert [r["text"] for r in over_cap] == ["free dashboard"]
    assert [r["text"] for r in held] == ["analytics alternative"]
    assert {r["text"]: r["reason"] for r in skipped} == {"already blocked thing": "already blocked",
                                                          "undone thing": "undone by the weekly"}
    assert all(r["match"] == "EXACT" and r["approve"] for r in to_add)
    # what the ledger already holds for today counts toward the cap
    assert daily_negatives.select(terms, have, gone, added_today=2)[0] == []


def test_ledger_helpers():
    entries = [{"routine": "daily", "field": "negative", "after": "EXACT", "date": "2026-01-07", "campaign": "C",
                "text": "a"},
               {"routine": "weekly", "field": "negative", "after": None, "date": "2026-01-08", "campaign": "C",
                "text": "B  Thing"}]
    assert len(daily_negatives.daily_lines("2026-01-07", entries)) == 1
    assert daily_negatives.daily_lines("2026-01-08", entries) == []
    assert daily_negatives.undone(entries) == {("C", "b thing")}
