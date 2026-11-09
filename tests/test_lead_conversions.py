"""Negatives, positives, pauses and match type proposals judge lead-signal conversions only (never noise). No network."""
from types import SimpleNamespace as NS

import daily_negatives
import keyword_review
from keyword_review import negative_rule


class Ga:
    """search_stream stub: metric queries answered with `plain`, conversion-action queries with `conv`."""
    def __init__(self, plain, conv):
        self.plain, self.conv, self.queries = plain, conv, []

    def search_stream(self, customer_id, query):
        self.queries.append(query)
        return [NS(results=self.conv if "segments.conversion_action_name" in query else self.plain)]


def term_row(text, cost, clicks, ad_group=11, status="NONE"):
    return NS(campaign=NS(id=1), ad_group=NS(id=ad_group, name="Analytics"),
              search_term_view=NS(search_term=text, status=NS(name=status)),
              metrics=NS(cost_micros=int(cost * 1e6), clicks=clicks))


def conv_row(text, conversions, ad_group=11):
    return NS(campaign=NS(id=1), ad_group=NS(id=ad_group), search_term_view=NS(search_term=text),
              metrics=NS(all_conversions=conversions))


def test_search_terms_merge_lead_signals_and_keep_rows_without_conversions():
    ga = Ga([term_row("dashboard templates", 9.0, 4), term_row("web analytics demo", 12.0, 6),
             term_row("added already", 5.0, 3, status="ADDED")],
            [conv_row("web analytics demo", 2.0)])
    out = keyword_review.search_terms(ga, {1: "US - Search"}, "segments.date DURING LAST_7_DAYS")
    got = {row["text"]: (m.clicks, m.conversions) for row, m in out}
    assert got == {"dashboard templates": (4, 0.0), "web analytics demo": (6, 2.0)}
    conv_query = next(q for q in ga.queries if "conversion_action_name" in q)
    assert "'Demo Request'" in conv_query and "'Signup'" in conv_query and "Chat Widget Open" not in conv_query
    plain_query = next(q for q in ga.queries if "conversion_action_name" not in q)
    assert "metrics.conversions" not in plain_query


def test_noise_conversions_no_longer_save_a_junk_term():
    # 'Chat Widget Open' (a noise signal) fired on this term; the conversion query only counts lead signals, so the
    # stub's conversion answer is empty and the term is judged as 0 conversions
    ga = Ga([term_row("dashboard templates", 9.0, 4)], [])
    (row, m), = keyword_review.search_terms(ga, {1: "US - Search"}, "segments.date DURING LAST_7_DAYS")
    assert m.conversions == 0.0 and negative_rule(row["text"], row["cost"], m.clicks, m.conversions) is not None


def test_conversions_go_to_one_row_only():
    rows = [term_row("a", 1.0, 1), term_row("a", 2.0, 1)]  # the same key twice: count it once
    merged = keyword_review.with_conversions(rows, keyword_review.TERM_KEY, {(1, 11, "a"): 3.0})
    assert [m.conversions for _, m in merged] == [3.0, 0.0]


def test_keyword_stats_for_pauses_use_lead_signals():
    kw = NS(resource_name="customers/1/adGroupCriteria/11~5", keyword=NS(text="x", match_type=NS(name="BROAD")),
            quality_info=NS(quality_score=5))
    plain = [NS(campaign=NS(id=1), ad_group=NS(name="Analytics"), ad_group_criterion=kw,
                metrics=NS(cost_micros=50_000_000, clicks=20))]
    conv = [NS(ad_group_criterion=NS(resource_name=kw.resource_name), metrics=NS(all_conversions=1.0))]
    (_, m), = keyword_review.keyword_stats(Ga(plain, conv), "1", "segments.date DURING LAST_30_DAYS")
    assert m.conversions == 1.0
    (_, m), = keyword_review.keyword_stats(Ga(plain, []), "1", "segments.date DURING LAST_30_DAYS")
    assert m.conversions == 0.0


def test_daily_negatives_select_on_lead_signal_totals():
    terms = {(1, "dashboard templates"): {"campaign_id": 1, "campaign": "US - Search", "ad_group_id": 11,
                                          "ad_group": "Dashboards", "text": "dashboard templates", "cost": 9.0,
                                          "clicks": 4, "conversions": 0.0}}
    to_add, _, _, _ = daily_negatives.select(terms, {}, set(), 0)
    assert [r["text"] for r in to_add] == ["dashboard templates"]
    assert "0 lead signals" in to_add[0]["reason"]
