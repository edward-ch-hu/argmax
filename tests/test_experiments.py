"""Experiments (ceiling tests), market price ceilings and budget reserves. No network: Google Ads is a stub."""
import copy
import json
from datetime import date
from types import SimpleNamespace as NS

import apply_changes
import config
import daily_bids
import daily_guard
import experiments
import market_price
import pytest
import yaml
from conftest import ROOT, make
from google.ads.googleads.errors import GoogleAdsException

EXP = {"id": "analytics-ceiling", "type": "ceiling_test", "campaign": "US - Search", "ad_group": "Analytics",
       "start": "2026-03-02", "end": "2026-03-23", "step": 0.20, "weekly_limit": 0.60, "stop_rank_lost": 0.10,
       "ceiling": "market", "pre_test": {"bid": 2.0, "budget": 60}, "kill": {"min_leads": 1, "max_cost_per_lead": 400},
       "reserve": {"base_cap": 120}}


def with_exp(**changes):
    e = {**copy.deepcopy(EXP), **changes}
    return config.activate(make(experiments=[e]))


def the(cfg=None):
    return (cfg or config.get()).experiments[0]


# ---- config ---------------------------------------------------------------------------------------------------------

def test_the_commented_example_in_the_example_config_is_valid():
    lines = (ROOT / "argmax.example.yaml").read_text(encoding="utf-8").splitlines()
    i = lines.index(next(x for x in lines if x.startswith("experiments: []")))
    block = []
    for line in lines[i + 1:]:
        if not line.startswith("#"):
            break
        block.append(line[1:])
    entries = yaml.safe_load("\n".join(block))
    cfg = make(experiments=entries)
    e = the(cfg)
    assert e["start"] == "2026-03-02" and e["ceiling"] == "market" and e["reserve"]["others_max"] == 60
    assert e["mid_check"]["window_days"] == 7


def test_defaults_are_filled_in():
    e = the(with_exp(mid_check={"window_days": 5}, ceiling="fixed", reserve=None))
    assert e["mid_check"] == {"min_click_rise": 0.15, "max_cpc_rise": 0.30, "window_days": 5, "min_days": 3}
    assert e["ceiling_amount"] == 6.0  # fixed defaults to limits.bid_ceiling


@pytest.mark.parametrize("changes, problem", [
    ({"id": "Bad Id"}, "experiments[0].id"),
    ({"end": "2026-03-01"}, "end: must not be before start"),
    ({"start": "soon"}, "must be a date"),
    ({"type": "ab_test"}, "type: must be one of ceiling_test"),
    ({"pre_test": None}, "pre_test"),
    ({"pre_test": {"bid": 9.0}}, "pre_test.bid"),  # over limits.bid_ceiling
    ({"ceiling": "fixed", "ceiling_amount": 99.0}, "ceiling_amount"),  # over market_price.safety_limit
    ({"ceiling": "market", "ceiling_amount": 8.0}, "only for a fixed ceiling"),
    ({"reserve": {"base_cap": 500}}, "reserve.base_cap"),  # over limits.daily_budget_cap
    ({"reserve": {"base_cap": 120}, "pre_test": {"bid": 2.0}}, "reserve.others_max: needed"),
    ({"step": 0.9}, "step"),
    ({"kill": {"min_leads": -1}}, "kill.min_leads"),
    ({"mid_check": {"min_days": 9, "window_days": 7}}, "min_days"),
    ({"surprise": 1}, "unknown key"),
])
def test_bad_experiments_are_refused(changes, problem):
    with pytest.raises(config.ConfigError, match=problem.replace("[", r"\[").replace("]", r"\]")):
        with_exp(**changes)


def test_a_market_ceiling_needs_a_safety_limit():
    data = {"experiments": [copy.deepcopy(EXP)], "market_price.safety_limit": None}
    with pytest.raises(config.ConfigError, match="needs market_price.safety_limit"):
        make(**data)
    with pytest.raises(config.ConfigError, match="market_price.safety_limit: needed"):
        make(**{"market_price.safety_limit": None,
                "market_price.groups": [{"campaign": "US - Search", "ad_group": "Analytics"}]})


def test_overlapping_experiments_on_one_group_are_refused():
    second = {**copy.deepcopy(EXP), "id": "second", "start": "2026-03-20", "end": "2026-04-10"}
    with pytest.raises(config.ConfigError, match="overlap"):
        make(experiments=[copy.deepcopy(EXP), second])
    later = {**second, "start": "2026-03-24"}
    assert len(make(experiments=[copy.deepcopy(EXP), later]).experiments) == 2


# ---- phases ---------------------------------------------------------------------------------------------------------

def test_phases_and_holding():
    with_exp()
    e = the()
    assert experiments.phase(e, date(2026, 3, 1)) == "planned"
    assert experiments.phase(e, date(2026, 3, 2)) == "running"
    assert experiments.phase(e, date(2026, 3, 23)) == "running"
    assert experiments.phase(e, date(2026, 3, 24)) == "judging"
    state = {"ended": {"analytics-ceiling": {"outcome": "mid_check"}}}
    assert experiments.phase(e, date(2026, 3, 10), state) == "ended"
    assert experiments.holding("US - Search", "Analytics", date(2026, 3, 1)) is None
    assert experiments.holding("US - Search", "Analytics", date(2026, 3, 30))["id"] == "analytics-ceiling"
    assert experiments.holding("US - Search", "Analytics", date(2026, 3, 30), state) is None
    assert experiments.holding("US - Search", "Reporting", date(2026, 3, 10)) is None


# ---- market price ---------------------------------------------------------------------------------------------------

class Ga:
    """search_stream stub answering each query with the rows of the first matching key, recording queries."""
    def __init__(self, answers, fail=None):
        self.answers, self.fail, self.queries = answers, fail, []

    def search_stream(self, customer_id, query):
        self.queries.append(query)
        if self.fail and self.fail in query:
            raise GoogleAdsException(None, None, NS(errors=[NS(error_code="QUERY_ERROR", message="not allowed")]), "x")
        for key, value in self.answers.items():
            if key in query:
                return [NS(results=value)]
        return [NS(results=[])]


def estimate(first, top, impressions):
    return NS(ad_group_criterion=NS(position_estimates=NS(first_position_cpc_micros=int(first * 1e6),
                                                          top_of_page_cpc_micros=int(top * 1e6))),
              metrics=NS(impressions=impressions))


def test_market_price_is_impression_weighted_with_top_of_page_as_fallback():
    ga = Ga({"position_estimates": [estimate(4.0, 2.0, 300), estimate(0, 3.0, 100), estimate(9.0, 5.0, 0)]})
    assert market_price.market_price(ga, "customers/1/adGroups/7", "2026-03-10") == 3.75  # (4x300 + 3x100) / 400
    q = ga.queries[0]
    assert "first_position_cpc_micros" in q and "top_of_page_cpc_micros" in q and "FROM keyword_view" in q
    assert "BETWEEN '2026-02-09' AND '2026-03-10'" in q  # 30 days to the data day
    assert market_price.weighted([]) is None


def test_market_ceiling_is_capped_by_the_safety_limit():
    cfg = config.get()  # safety_limit 15, bid_floor 0.30, bid_ceiling 6 in the example
    assert market_price.ceiling(9.5, cfg) == 9.5
    assert market_price.ceiling(40.0, cfg) == 15.0  # a bad estimate never beats the safety limit
    assert market_price.ceiling(None, cfg) == 6.0  # no estimate: fallback = limits.bid_ceiling
    assert market_price.ceiling(0.05, cfg) == 0.3  # never under the floor
    assert market_price.ceiling(None, make(**{"market_price.fallback": 4.0})) == 4.0


def test_a_refused_market_query_degrades_to_a_note():
    ga = Ga({}, fail="position_estimates")
    price, note = market_price.fetch(ga, "customers/1/adGroups/7", "2026-03-10", "US - Search / Analytics")
    assert price is None and "unavailable for US - Search / Analytics" in note and "falls back to 6.00" in note


def test_group_ceilings():
    with_exp()
    day = date(2026, 3, 10)
    assert experiments.group_ceiling("US - Search", "Analytics", day, market=9.0) == 9.0
    assert experiments.group_ceiling("US - Search", "Analytics", date(2026, 3, 1), market=9.0) == 6.0  # not started
    killed = {"ended": {"analytics-ceiling": {"outcome": "killed"}}}
    assert experiments.group_ceiling("US - Search", "Analytics", day, killed, market=9.0) == 6.0
    passed = {"ended": {"analytics-ceiling": {"outcome": "passed"}}}
    assert experiments.group_ceiling("US - Search", "Analytics", date(2026, 5, 1), passed, market=9.0) == 9.0
    assert experiments.needs_market("US - Search", "Analytics", day)
    assert not experiments.needs_market("US - Search", "Reporting", day)
    with_exp(ceiling="fixed", ceiling_amount=8.0)
    assert experiments.group_ceiling("US - Search", "Analytics", day) == 8.0
    assert not experiments.needs_market("US - Search", "Analytics", day)
    config.activate(make(**{"market_price.groups": [{"campaign": "US - Search", "ad_group": "Reporting"}]}))
    assert experiments.group_ceiling("US - Search", "Reporting", day, market=7.5) == 7.5
    assert experiments.needs_market("US - Search", "Reporting", day)


# ---- daily stepping -------------------------------------------------------------------------------------------------

def decide(rules, bid=2.0, rank_lost=0.6, impressions=100, start=2.0, budget_lost=0.0):
    return daily_bids.decide(bid, impressions, rank_lost, budget_lost, True, None, start, True, None, rules)


def test_experiment_rules_raise_faster_and_never_lower():
    with_exp()
    rules = experiments.step_rules(the(), 15.0)
    assert decide(rules, rank_lost=0.3) == ("raise", "lost 30% to rank", 2.4)  # over the 10% stop: +20%
    action, why, bid = decide(rules, rank_lost=0.05)
    assert action == "hold" and "never lowered" in why and bid == 2.0  # visible: held, not lowered
    assert decide(rules, bid=3.0, start=2.0)[2] == 3.2  # +60% from Monday at most
    assert decide(rules, bid=3.2, start=2.0)[0] == "hold"
    assert decide(experiments.step_rules(the(), 2.2), rank_lost=0.3)[2] == 2.2  # the ceiling
    assert decide(rules, budget_lost=0.5)[0] == "hold"  # budget-capped: no point raising
    # the normal rules lower a visible group
    assert decide(daily_bids.stepping_rules(), rank_lost=0.05)[0] == "lower"


class Client:
    def __init__(self, ga):
        self.ga = ga

    def get_service(self, name):
        return self.ga


def plan_ga(bid=2.0, rank_lost=0.4, market=None):
    group = NS(campaign=NS(name="US - Search"), ad_group=NS(name="Analytics", resource_name="customers/1/adGroups/7",
                                                            cpc_bid_micros=int(bid * 1e6)))
    answers = {
        "FROM change_event": [],
        "search_budget_lost_impression_share FROM campaign": [
            NS(campaign=NS(name="US - Search"), metrics=NS(search_budget_lost_impression_share=0.0))],
        "FROM ad_group_ad": [NS(ad_group=NS(resource_name="customers/1/adGroups/7"))],
        "search_rank_lost_impression_share FROM ad_group": [
            NS(ad_group=NS(resource_name="customers/1/adGroups/7"),
               metrics=NS(impressions=200, search_rank_lost_impression_share=rank_lost))],
        "position_estimates": [estimate(market, market, 100)] if market else [],
        "ad_group.cpc_bid_micros": [group],
    }
    return Ga(answers)


def test_plan_steps_an_experiment_past_its_stepping_window(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "reports").mkdir()
    # the group's normal 14-day window started long ago: without the experiment it is settled
    (tmp_path / "reports" / "stepping.json").write_text(json.dumps(
        {"groups": [{"campaign": "US - Search", "ad_group": "Analytics", "first_evaluated": "2026-01-05"}]}))
    groups, notes = daily_bids.plan(Client(plan_ga()), "2026-01-30")
    assert groups[0]["action"] == "settled"

    with_exp()
    groups, notes = daily_bids.plan(Client(plan_ga(market=9.0)), "2026-03-09")
    g = groups[0]
    assert g["experiment"] == "analytics-ceiling" and g["action"] == "raise" and g["new_bid"] == 2.4
    assert g["market_price"] == 9.0 and notes == []
    entries = daily_bids.step_entries([g])
    assert entries[0]["experiment"] == "analytics-ceiling" and entries[0]["routine"] == "daily"
    assert entries[0]["reason"].startswith("experiment analytics-ceiling step")

    # after the end date it no longer steps (judging): back to settled
    groups, _ = daily_bids.plan(Client(plan_ga()), "2026-03-24")
    assert groups[0]["action"] == "settled" and "experiment" not in groups[0]


def test_plan_market_price_degrades_to_the_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with_exp()
    ga = plan_ga(bid=5.9, rank_lost=0.4)
    ga.fail = "position_estimates"
    groups, notes = daily_bids.plan(Client(ga), "2026-03-09")
    assert groups[0]["market_price"] is None and groups[0]["new_bid"] == 6.0  # fallback ceiling limits.bid_ceiling
    assert len(notes) == 1 and "falls back" in notes[0]


def test_daily_step_ledger_lines_without_an_experiment_have_no_id():
    g = {"campaign": "US - Search", "ad_group": "Analytics", "bid": 1.0, "new_bid": 1.1, "why": "lost 60% to rank"}
    (entry,) = daily_bids.step_entries([g])
    assert "experiment" not in entry and entry["reason"] == "daily step: lost 60% to rank"


# ---- mid-test check and kill rule -----------------------------------------------------------------------------------

def days(bids_clicks_cpc, start=1, budget_lost=0.0):
    out = []
    for i, (bid, clicks, cpc) in enumerate(bids_clicks_cpc):
        out.append({"date": f"2026-03-{start + i:02d}", "bid": bid, "clicks": clicks, "cost": round(clicks * cpc, 2),
                    "impressions": clicks * 20, "lead_signals": 0.0, "rank_lost": 0.4, "budget_lost": budget_lost})
    return out


def test_mid_check_ends_a_flat_curve_at_the_knee():
    with_exp()
    flat = days([(2.6, 19, 2.4)] * 7 + [(4.2, 20, 3.4)] * 7)  # clicks +5%, CPC +42%
    v = experiments.mid_check(flat, the(), current_bid=4.2)
    assert v["verdict"] == "end" and v["knee"] == 2.6
    assert v["click_rise"] == pytest.approx(0.053, abs=0.001) and v["cpc_rise"] == pytest.approx(0.417, abs=0.001)
    assert "back to the knee 2.60" in v["why"]


def test_mid_check_continues_while_bid_still_buys_clicks():
    with_exp()
    rising = days([(2.6, 19, 2.4)] * 7 + [(4.2, 30, 3.4)] * 7)  # clicks +58%
    assert experiments.mid_check(rising, the(), 4.2)["verdict"] == "continue"


def test_mid_check_waits_for_enough_qualifying_days():
    with_exp()
    assert experiments.mid_check(days([(2.6, 19, 2.4)] * 5), the(), 2.6)["verdict"] == "wait"
    # days held back by the campaign budget do not count
    capped = days([(2.6, 19, 2.4)] * 7) + days([(4.2, 20, 3.4)] * 7, start=8, budget_lost=0.5)
    assert experiments.mid_check(capped, the(), 4.2)["verdict"] == "wait"
    assert experiments.mid_check(days([(2.6, 19, 2.4)] * 14), the(with_exp(mid_check=None)), 2.6)["verdict"] == "off"


def test_levels_table():
    with_exp()
    table = experiments.levels(days([(2.0, 10, 2.0)] * 3 + [(2.4, 12, 2.5)] * 7), 7)
    assert [t["days"] for t in table] == [3, 7]
    assert table[1]["bid_low"] == 2.4 and table[1]["clicks_per_day"] == 12 and table[1]["cpc"] == 2.5


def test_merge_days_uses_recorded_bids_and_the_pre_test_bid_before_the_start():
    with_exp()
    stats = {"2026-03-01": {"clicks": 5, "cost": 10.0, "impressions": 50, "lead_signals": 1.0},
             "2026-03-03": {"clicks": 6, "cost": 15.0, "impressions": 60, "lead_signals": 0.0}}
    recorded = {"2026-03-03": {"bid": 2.4, "rank_lost": 0.3, "budget_lost": 0.0},
                "2026-03-04": {"bid": 2.88, "rank_lost": 0.2, "budget_lost": 0.0}}
    merged = experiments.merge_days(the(), stats, recorded)
    assert [(d["date"], d["bid"], d["clicks"]) for d in merged] == [
        ("2026-03-01", 2.0, 5), ("2026-03-03", 2.4, 6), ("2026-03-04", 2.88, 0)]


def test_kill_rule():
    with_exp()
    e = the()
    assert experiments.kill_verdict(0, 500.0, e)[0] is True  # no new lead
    assert experiments.kill_verdict(2, 1000.0, e)[0] is True  # 500 a lead, over 400
    killed, why = experiments.kill_verdict(3, 900.0, e)
    assert killed is False and "cost per lead 300.00" in why
    e2 = the(with_exp(kill={"min_leads": 0, "max_cost_per_lead": 400}))
    assert experiments.kill_verdict(0, 50.0, e2)[0] is True  # spent with no lead at all
    assert experiments.kill_verdict(0, 0.0, e2)[0] is False


def test_crm_leads_count_topic_leads_and_ref_matches_once():
    with_exp()
    rows = [{"fp": "a", "date": "2026-03-05", "topics": ["analytics"]},
            {"fp": "b", "date": "2026-03-06", "topics": ["reporting"]},
            {"fp": "c", "date": "2026-02-20", "topics": ["analytics"]}]  # before the test
    matches = [{"fp": "a", "date": "2026-03-05", "status": "matched",
                "clicks": [{"campaign": "US - Search", "ad_group": "Analytics"}]},
               {"fp": "b", "date": "2026-03-06", "status": "matched",
                "clicks": [{"campaign": "US - Search", "ad_group": "Analytics"}]},
               {"fp": "d", "date": "2026-03-07", "status": "ambiguous", "clicks": []}]
    assert experiments.crm_leads(the(), rows, matches, "2026-03-02", "2026-03-23") == 2  # a (both ways) and b (ref)


# ---- ending and reversing -------------------------------------------------------------------------------------------

CAMPS = [
    {"resource": "c/1", "name": "US - Search", "status": "ENABLED", "channel": "SEARCH", "budget_resource": "b/1",
     "budget": 90.0},
    {"resource": "c/2", "name": "UK - Search", "status": "ENABLED", "channel": "SEARCH", "budget_resource": "b/2",
     "budget": 50.0},
]
GROUPS = [
    {"campaign": "US - Search", "channel": "SEARCH", "resource": "g/1", "name": "Analytics", "status": "ENABLED", "bid": 4.2},
    {"campaign": "US - Search", "channel": "SEARCH", "resource": "g/2", "name": "Reporting", "status": "ENABLED", "bid": 1.0},
]


def test_plan_end_reverts_bid_and_budget_with_ledger_ids():
    with_exp()
    fails, plan, record = experiments.plan_end(the(), GROUPS[0], CAMPS, "killed", 2.0, 60, "no new lead",
                                               date(2026, 3, 23), 15.0)
    assert fails == []
    assert plan[("ad_group", "g/1")]["fields"] == {"cpc_bid_micros": 2_000_000}
    assert plan[("budget", "b/1")]["fields"] == {"amount_micros": 60_000_000}
    assert all(e["experiment"] == "analytics-ceiling" for p in plan.values() for e in p["ledger"])
    assert record == {"date": "2026-03-23", "outcome": "killed", "why": "no new lead", "bid_before": 4.2,
                      "bid_after": 2.0, "budget_before": 90.0, "budget_after": 60}


def test_plan_end_stays_inside_the_limits():
    with_exp()
    fails, _, _ = experiments.plan_end(the(), GROUPS[0], CAMPS, "reversed", 9.0, None, "x", date(2026, 3, 23), 8.0)
    assert any("outside 0.30 to 8.00" in f for f in fails)
    fails, _, _ = experiments.plan_end(the(), GROUPS[0], CAMPS, "reversed", 4.2, 110, "x", date(2026, 3, 23), 8.0)
    assert any("over the USD 150 cap" in f for f in fails)  # 110 + 50 > 150
    fails, plan, record = experiments.plan_end(the(), GROUPS[0], CAMPS, "passed", None, None, "ok", date(2026, 3, 23), 8.0)
    assert fails == [] and plan == {} and record["bid_after"] == 4.2


def test_state_round_trip(tmp_path):
    path = tmp_path / "experiments.json"
    state = experiments.load_state(path)
    assert state == {"ended": {}, "history": []}
    state["ended"]["x"] = {"outcome": "passed"}
    experiments.save_state(state, path)
    assert experiments.load_state(path)["ended"] == {"x": {"outcome": "passed"}}


# ---- apply_changes: hand bids and the reserve -----------------------------------------------------------------------

def run(changes, today, state=None, ceilings=None):
    return apply_changes.evaluate(changes, CAMPS, GROUPS, [], {}, {}, today, state=state, ceilings=ceilings)


def test_hand_bids_on_a_group_an_experiment_holds_are_refused():
    with_exp()
    bid = {"bids": [{"campaign": "US - Search", "ad_group": "Analytics", "cpc": 4.5}]}
    for day in (date(2026, 3, 10), date(2026, 3, 30)):  # running, then waiting to be judged
        fails, _, _ = run(bid, day)
        assert any("experiment analytics-ceiling holds this bid" in f for f in fails)
    other = {"bids": [{"campaign": "US - Search", "ad_group": "Reporting", "cpc": 1.1}]}
    assert run(other, date(2026, 3, 10))[0] == []  # other groups are free


def test_after_a_passed_experiment_the_weekly_bids_up_to_its_ceiling():
    with_exp()
    passed = {"ended": {"analytics-ceiling": {"outcome": "passed"}}}
    bid = {"bids": [{"campaign": "US - Search", "ad_group": "Analytics", "cpc": 4.5}]}
    assert run(bid, date(2026, 3, 30), passed, {("US - Search", "Analytics"): 9.0})[0] == []  # no longer held
    groups = [{**GROUPS[0], "bid": 7.0}]
    high = {"bids": [{"campaign": "US - Search", "ad_group": "Analytics", "cpc": 8.0}]}
    fails, _, _ = apply_changes.evaluate(high, CAMPS, groups, [], {}, {}, date(2026, 3, 30), state=passed,
                                         ceilings={("US - Search", "Analytics"): 9.0})
    assert fails == []  # 8.00 is over limits.bid_ceiling but under the experiment's market ceiling
    killed = {"ended": {"analytics-ceiling": {"outcome": "killed"}}}
    fails, _, _ = apply_changes.evaluate(high, CAMPS, groups, [], {}, {}, date(2026, 3, 30), state=killed)
    assert any("outside 0.30 to 6.00" in f for f in fails)  # killed: back to the normal ceiling


RESERVE_CAMPS = [{**CAMPS[0], "budget": 70.0}, {**CAMPS[1], "budget": 50.0}]  # others: 50 of the 60 they may use


def reserve_run(changes, today, state=None, camps=None):
    return apply_changes.evaluate(changes, camps or RESERVE_CAMPS, GROUPS, [], {}, {}, today, state=state)


def test_reserve_keeps_the_room_for_the_experiment_campaign():
    with_exp()  # base cap 120, pre-test budget 60: the others may use 60 together
    day = date(2026, 3, 10)
    more = {"budgets": [{"campaign": "UK - Search", "daily_budget": 65}]}
    fails, _, totals = reserve_run(more, day)
    assert totals[1] == 135.0  # under the 150 cap: only the reserve refuses it
    assert len(fails) == 1 and "would total USD 65.00" in fails[0] and "reserves the room above USD 120" in fails[0]
    assert reserve_run({"budgets": [{"campaign": "UK - Search", "daily_budget": 60}]}, day)[0] == []  # at the line
    # the experiment campaign itself may use the room (inside the cap)
    assert reserve_run({"budgets": [{"campaign": "US - Search", "daily_budget": 100}]}, day)[0] == []
    # enabling a paused campaign counts toward the others
    paused = RESERVE_CAMPS + [{"resource": "c/3", "name": "DE - Search", "status": "PAUSED", "channel": "SEARCH",
                               "budget_resource": "b/3", "budget": 20.0}]
    fails, _, _ = reserve_run({"status": [{"level": "campaign", "campaign": "DE - Search", "status": "ENABLED"}]},
                              day, camps=paused)
    assert any("would total USD 70.00" in f for f in fails)
    # already over (a manual change): a file that does not add to it is not blocked
    over = [RESERVE_CAMPS[0], {**RESERVE_CAMPS[1], "budget": 70.0}]
    assert reserve_run({"budgets": [{"campaign": "UK - Search", "daily_budget": 65}]}, day, camps=over)[0] == []
    # after the end date, or once the experiment ended, the reserve is gone
    assert reserve_run(more, date(2026, 3, 24))[0] == []
    assert reserve_run(more, day, {"ended": {"analytics-ceiling": {"outcome": "mid_check"}}})[0] == []


def test_reserve_with_an_explicit_others_max():
    with_exp(reserve={"base_cap": 120, "others_max": 40})
    fails, _, _ = reserve_run({"budgets": [{"campaign": "UK - Search", "daily_budget": 55}]}, date(2026, 3, 10))
    assert any("over the USD 40.00" in f for f in fails)


def test_daily_guard_alerts_on_a_reserve_overrun():
    with_exp()
    budgets = [("US - Search", "b/1", 90.0), ("UK - Search", "b/2", 50.0), ("DE - Search", "b/3", 20.0)]
    (alert,) = daily_guard.reserve_alerts(budgets, date(2026, 3, 10))
    assert "other than US - Search have USD 70.00" in alert and "over the USD 60.00" in alert
    assert daily_guard.reserve_alerts(budgets, date(2026, 3, 24)) == []  # after the end date
    assert daily_guard.reserve_alerts(budgets[:2], date(2026, 3, 10)) == []


# ---- evaluate, end to end with a stub account -----------------------------------------------------------------------

def stat(day, clicks, cost):
    return NS(segments=NS(date=day), metrics=NS(clicks=clicks, cost_micros=int(cost * 1e6), impressions=clicks * 20))


def account_ga(stats):
    camp = NS(campaign=NS(resource_name="c/1", name="US - Search", status=NS(name="ENABLED"),
                          advertising_channel_type=NS(name="SEARCH")),
              campaign_budget=NS(resource_name="b/1", amount_micros=90_000_000))
    group = NS(campaign=NS(name="US - Search", advertising_channel_type=NS(name="SEARCH")),
               ad_group=NS(resource_name="g/1", name="Analytics", status=NS(name="ENABLED"), cpc_bid_micros=4_200_000))
    return Ga({"conversion_action_name": [], "metrics.clicks": stats, "FROM campaign WHERE": [camp],
               "ad_group.status, ad_group.cpc_bid_micros": [group], "position_estimates": [estimate(9.0, 9.0, 100)]})


def evaluate_at(tmp_path, monkeypatch, today, stats, recorded, apply=True):
    import ads_client

    monkeypatch.chdir(tmp_path)
    daily = tmp_path / "reports" / "daily"
    daily.mkdir(parents=True, exist_ok=True)
    week = {"days": {d: {"bids": [{"campaign": "US - Search", "ad_group": "Analytics", "bid": b, "budget_lost": 0.0,
                                   "rank_lost": 0.4}]} for d, b in recorded.items()}}
    (daily / "week-2026-03-02.json").write_text(json.dumps(week))
    ga = account_ga(stats)
    monkeypatch.setattr(ads_client, "load", lambda: Client(ga))
    monkeypatch.setattr(ads_client, "today", lambda: today)
    executed = []
    monkeypatch.setattr(experiments, "execute", lambda client, ga, plan, validate_only: executed.append(
        (plan, validate_only)))
    experiments.evaluate(validate_only=not apply)
    return executed, experiments.load_state(), json.loads((tmp_path / "reports" / f"experiments-{today}.json").read_text())


def test_evaluate_ends_a_flat_test_early_at_the_knee(tmp_path, monkeypatch, capsys):
    with_exp()
    stats = [stat(f"2026-03-{d:02d}", 19, 19 * 2.4) for d in range(2, 9)] + \
            [stat(f"2026-03-{d:02d}", 20, 20 * 3.4) for d in range(9, 16)]
    recorded = {**{f"2026-03-{d:02d}": 2.6 for d in range(2, 9)}, **{f"2026-03-{d:02d}": 4.2 for d in range(9, 16)}}
    executed, state, report = evaluate_at(tmp_path, monkeypatch, date(2026, 3, 16), stats, recorded)
    (plan, validate_only), = executed
    assert validate_only is False and plan[("ad_group", "g/1")]["fields"] == {"cpc_bid_micros": 2_600_000}
    assert state["ended"]["analytics-ceiling"]["outcome"] == "mid_check"
    assert report["experiments"][0]["mid_check"]["verdict"] == "end"
    out = capsys.readouterr().out
    assert "DECISION Done, reply reverse to undo: experiment analytics-ceiling" in out and "LEVEL" in out


def test_evaluate_validates_only_by_default(tmp_path, monkeypatch):
    with_exp()
    stats = [stat(f"2026-03-{d:02d}", 19, 19 * 2.4) for d in range(2, 9)] + \
            [stat(f"2026-03-{d:02d}", 20, 20 * 3.4) for d in range(9, 16)]
    recorded = {**{f"2026-03-{d:02d}": 2.6 for d in range(2, 9)}, **{f"2026-03-{d:02d}": 4.2 for d in range(9, 16)}}
    executed, state, _ = evaluate_at(tmp_path, monkeypatch, date(2026, 3, 16), stats, recorded, apply=False)
    assert executed[0][1] is True and state["ended"] == {}  # nothing recorded without --apply


def test_evaluate_kills_on_the_end_date_without_leads(tmp_path, monkeypatch):
    with_exp()  # no CRM in the example: leads are lead signals, and the stub has none
    stats = [stat(f"2026-03-{d:02d}", 20, 60.0) for d in range(2, 24)]
    recorded = {f"2026-03-{d:02d}": 3.0 for d in range(2, 24)}
    executed, state, report = evaluate_at(tmp_path, monkeypatch, date(2026, 3, 23), stats, recorded)
    (plan, _), = executed
    assert plan[("ad_group", "g/1")]["fields"] == {"cpc_bid_micros": 2_000_000}  # back to pre_test.bid
    assert plan[("budget", "b/1")]["fields"] == {"amount_micros": 60_000_000}  # and pre_test.budget
    assert state["ended"]["analytics-ceiling"]["outcome"] == "killed"
    kill = report["experiments"][0]["kill"]
    assert kill["killed"] and kill["source"] == "lead signals (no CRM)" and kill["cost"] == 1320.0
