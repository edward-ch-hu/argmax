import json
from datetime import date

import daily_bids


def decide(bid=1.0, impressions=100, rank_lost=0.6, budget_lost=0.0, approved=True, late=None, start=1.0, weekly=True):
    return daily_bids.decide(bid, impressions, rank_lost, budget_lost, approved, late, start, weekly)


def test_raise_lower_hold():
    assert decide(rank_lost=0.6) == ("raise", "lost 60% to rank", 1.1)
    assert decide(rank_lost=0.1)[0::2] == ("lower", 0.9)
    assert decide(rank_lost=0.3)[0] == "hold"
    assert decide(rank_lost=0.1, impressions=10)[0] == "hold"  # too few impressions to lower


def test_zero_impressions_needs_an_approved_ad():
    assert decide(rank_lost=None, impressions=0)[0] == "raise"
    assert decide(rank_lost=None, impressions=0, approved=False)[0] == "hold"


def test_budget_hold_and_late_change():
    assert "to budget" in decide(budget_lost=0.3)[1]
    assert decide(late=("2026-01-08 09:00:00", 1.0, 1.2))[0] == "hold"


def test_weekly_limit_and_ceiling():
    # Monday bid 1.0, +30% max: 1.28 -> 1.30 at most
    assert decide(bid=1.28, start=1.0)[2] == 1.3
    assert decide(bid=1.30, start=1.0)[0] == "hold"
    assert decide(bid=1.30, start=1.0, weekly=False)[2] == 1.43  # a new group skips the weekly limit
    assert decide(bid=5.9, start=5.9, weekly=False)[2] == 6.0  # bid_ceiling


def test_stepping_window(tmp_path, monkeypatch):
    week = {"days": {"2026-01-05": {"bids": [{"campaign": "US - Search", "ad_group": "Analytics", "action": "raise"}]}}}
    (tmp_path / "week-2026-01-05.json").write_text(json.dumps(week))
    firsts = daily_bids.first_steps(tmp_path)
    assert firsts == {("US - Search", "Analytics"): date(2026, 1, 6)}
    assert not daily_bids.settled("US - Search", "Analytics", date(2026, 1, 19), firsts)
    assert daily_bids.settled("US - Search", "Analytics", date(2026, 1, 20), firsts)
    assert not daily_bids.settled("US - Search", "Reporting", date(2026, 3, 1), firsts)


def test_managed_and_week_start():
    assert daily_bids.managed("SEARCH", "Analytics")
    assert not daily_bids.managed("SEARCH", "Reporting")
    assert not daily_bids.managed("DISPLAY", "Analytics")
    assert daily_bids.week_start_bid([("t", 0.8, 1.0, False)], 1.0) == 0.8
    assert daily_bids.week_start_bid([("t", 0.0, 1.0, True)], 1.0) == 1.0
    assert daily_bids.week_start_bid([], 1.2) == 1.2
