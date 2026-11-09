from datetime import date

import apply_changes

TODAY = date(2026, 1, 7)  # a Wednesday

CAMPS = [
    {"resource": "c/1", "name": "US - Search", "status": "ENABLED", "channel": "SEARCH", "budget_resource": "b/1",
     "budget": 80.0},
    {"resource": "c/2", "name": "UK - Search", "status": "ENABLED", "channel": "SEARCH", "budget_resource": "b/2",
     "budget": 50.0},
    {"resource": "c/3", "name": "PMax", "status": "PAUSED", "channel": "PERFORMANCE_MAX", "budget_resource": "b/3",
     "budget": 40.0},
]
GROUPS = [
    {"campaign": "US - Search", "channel": "SEARCH", "resource": "g/1", "name": "Analytics", "status": "ENABLED", "bid": 2.0},
    {"campaign": "US - Search", "channel": "SEARCH", "resource": "g/2", "name": "Reporting", "status": "ENABLED", "bid": 1.0},
]
KEYWORDS = [
    {"campaign": "US - Search", "ad_group": "Reporting", "resource": "k/1", "text": "pdf report tool", "match": "PHRASE",
     "status": "ENABLED"},
]


def run(changes, history=None, firsts=None):
    return apply_changes.evaluate(changes, CAMPS, GROUPS, KEYWORDS, history or {}, firsts or {}, TODAY)


def test_valid_file_builds_a_plan():
    fails, plan, totals = run({"bids": [{"campaign": "US - Search", "ad_group": "Reporting", "cpc": 1.15}],
                               "budgets": [{"campaign": "UK - Search", "daily_budget": 60}],
                               "status": [{"level": "keyword", "campaign": "US - Search", "ad_group": "Reporting",
                                           "keyword": "PDF Report Tool", "status": "PAUSED"}]})
    assert fails == []
    assert plan[("ad_group", "g/2")]["fields"] == {"cpc_bid_micros": 1_150_000}
    assert plan[("budget", "b/2")]["fields"] == {"amount_micros": 60_000_000}
    assert totals == (130.0, 140.0)
    entry = plan[("ad_group", "g/2")]["ledger"][0]
    assert entry["field"] == "cpc" and entry["topic"] == "reporting" and entry["date"] == "2026-01-07"


def test_budget_cap():
    fails, _, totals = run({"budgets": [{"campaign": "US - Search", "daily_budget": 101}]})
    assert totals[1] == 151.0
    assert any("over the USD 150 cap" in f for f in fails)


def test_enabling_a_campaign_counts_toward_the_cap():
    fails, _, _ = run({"status": [{"level": "campaign", "campaign": "UK - Search", "status": "PAUSED"},
                                  {"level": "campaign", "campaign": "PMax", "status": "ENABLED"}]})
    assert any("Performance Max" in f for f in fails)


def test_weekly_bid_limit_from_monday_bid():
    # the bid was 0.80 on Monday and moved to 1.00 since; 1.00 is +25% from Monday
    history = {"g/2": [("2026-01-05 10:00:00", 0.80, 1.00, False)]}
    fails, _, _ = run({"bids": [{"campaign": "US - Search", "ad_group": "Reporting", "cpc": 1.0}]}, history)
    assert any("over the +/-20% weekly limit" in f for f in fails)
    fails, _, _ = run({"bids": [{"campaign": "US - Search", "ad_group": "Reporting", "cpc": 0.95}]}, history)
    assert fails == []


def test_bid_floor_and_ceiling(use):
    use(**{"limits.bid_floor": 1.1})
    fails, _, _ = run({"bids": [{"campaign": "US - Search", "ad_group": "Reporting", "cpc": 1.05}]})
    assert any("outside" in f for f in fails)


def test_stepping_window_blocks_winning_groups():
    bid = {"bids": [{"campaign": "US - Search", "ad_group": "Analytics", "cpc": 2.1}]}
    fails, _, _ = run(bid, firsts={("US - Search", "Analytics"): date(2026, 1, 1)})
    assert any("still stepping" in f for f in fails)
    fails, _, _ = run(bid)  # no step yet: the window has not started, the daily owns it
    assert any("still stepping" in f for f in fails)
    fails, _, _ = run(bid, firsts={("US - Search", "Analytics"): date(2025, 12, 20)})  # settled after 14 days
    assert fails == []


def test_names_must_match_once_and_not_repeat():
    fails, _, _ = run({"bids": [{"campaign": "US - Search", "ad_group": "Nope", "cpc": 1.0},
                                {"campaign": "US - Search", "ad_group": "Reporting", "cpc": 1.0},
                                {"campaign": "US - Search", "ad_group": "Reporting", "cpc": 1.1}],
                       "status": [{"level": "campaign", "campaign": "US - Search", "status": "OFF"}]})
    assert any("no match" in f for f in fails)
    assert any("listed twice" in f for f in fails)
    assert any("PAUSED or ENABLED" in f for f in fails)


def test_zero_decimal_currency_rounding(use):
    use(**{"account.currency": "JPY", "limits.bid_floor": 10, "limits.bid_ceiling": 500, "limits.daily_budget_cap": 20000})
    groups = [dict(GROUPS[1], bid=100.0)]
    fails, plan, _ = apply_changes.evaluate({"bids": [{"campaign": "US - Search", "ad_group": "Reporting", "cpc": 110.4}]},
                                            CAMPS, groups, [], {}, {}, TODAY)
    assert fails == []
    assert plan[("ad_group", "g/2")]["fields"]["cpc_bid_micros"] == 110_000_000
