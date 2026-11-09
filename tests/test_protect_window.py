"""The protection window: a lead signal on a term in its campaign over negatives.protect_days keeps it from being
blocked by spend or clicks; junk words still block; noise signals never protect. No network."""
from datetime import date
from types import SimpleNamespace as NS

import daily_negatives
import keyword_review
import match_type_review
from keyword_review import negative_rule, protection


def term(text, cost, clicks, conversions=0.0, campaign="US - Search"):
    return {"campaign_id": 1, "campaign": campaign, "ad_group_id": 7, "ad_group": "Dashboards", "text": text,
            "cost": cost, "clicks": clicks, "conversions": conversions}


def test_a_recent_lead_signal_protects_a_term_from_spend_and_clicks():
    assert negative_rule("dashboard templates", 9.0, 4, 0) is not None  # blocked on the 7-day lookback alone
    assert negative_rule("dashboard templates", 9.0, 4, 0, recent=1) is None  # a lead signal in 30 days: protected
    assert negative_rule("dashboard ideas", 0.0, 12, 0, recent=0.5) is None  # the click rule too
    assert "1 lead signals" in protection("dashboard templates", 9.0, 4, 0, 1)
    assert "30 days" in protection("dashboard templates", 9.0, 4, 0, 1)


def test_junk_words_still_block_inside_the_window():
    negative = negative_rule("free dashboard download", 1.0, 1, 0, recent=3)
    assert negative is not None and negative[0].startswith("junk word")
    assert protection("free dashboard download", 1.0, 1, 0, 3) is None


def test_protection_reason_only_when_it_changed_the_outcome():
    assert protection("cheap thing", 1.0, 2, 0, 2) is None  # under the floors anyway: not a negative to begin with
    assert protection("dashboard templates", 9.0, 4, 0, 0) is None  # no recent lead signal


def test_protection_can_be_switched_off(use):
    use(**{"negatives.protect_days": 0})
    ga = Ga([])
    assert keyword_review.protect_terms(ga, {1: "US - Search"}, date(2026, 1, 6)) == {}
    assert ga.queries == []  # no query at all


def test_protect_days_shorter_than_the_lookback_is_refused():
    import config
    import pytest
    from conftest import make

    with pytest.raises(config.ConfigError, match="protect_days"):
        make(**{"negatives.protect_days": 3, "negatives.lookback_days": 7})


class Ga:
    def __init__(self, conv):
        self.conv, self.queries = conv, []

    def search_stream(self, customer_id, query):
        self.queries.append(query)
        return [NS(results=self.conv)]


def test_protect_terms_counts_lead_signals_only_over_the_window():
    ga = Ga([NS(campaign=NS(id=1), search_term_view=NS(search_term="Dashboard  Templates"),
                metrics=NS(all_conversions=1.0)),
             NS(campaign=NS(id=1), search_term_view=NS(search_term="dashboard templates"),
                metrics=NS(all_conversions=2.0))])
    got = keyword_review.protect_terms(ga, {1: "US - Search"}, date(2026, 1, 31))
    assert got == {(1, "dashboard templates"): 3.0}  # normalised and summed
    q = ga.queries[0]
    assert "BETWEEN '2026-01-02' AND '2026-01-31'" in q  # 30 days ending on the end date
    assert "'Demo Request'" in q and "'Signup'" in q and "Chat Widget Open" not in q  # never a noise signal
    assert "ad_network_type" not in q  # every network: a lead from any click protects the term


def test_daily_negatives_skip_protected_terms_with_the_reason():
    terms = {(1, daily_negatives.norm(t["text"])): t for t in [
        term("dashboard templates", 9.0, 4),
        term("pdf report examples", 7.0, 3),
        term("free dashboard", 1.0, 2),
    ]}
    recent = {(1, "dashboard templates"): 1.0, (1, "free dashboard"): 2.0}
    to_add, held, over_cap, skipped = daily_negatives.select(terms, {}, set(), 0, recent=recent)
    assert [r["text"] for r in to_add] == ["pdf report examples", "free dashboard"]  # the junk word still blocks
    assert [(r["text"], r["reason"].split(":")[0]) for r in skipped] == [("dashboard templates", "protected")]
    assert held == [] and over_cap == []


def test_match_type_off_intent_respects_the_window():
    # a dashboards term in a dashboards group: off-intent only through the negative rule
    assert match_type_review.off_intent("dashboard templates", (9.0, 4, 0), "dashboards")
    assert not match_type_review.off_intent("dashboard templates", (9.0, 4, 0), "dashboards", recent=1)
    assert match_type_review.off_intent("free dashboard", (1.0, 1, 0), "dashboards", recent=1)  # junk word
