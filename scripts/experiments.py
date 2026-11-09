"""Experiments: time-boxed bid tests the owner approved, each one an entry under experiments: in the config.

Type ceiling_test: how high can a winning ad group's bid usefully go? From its start date to its end date
daily_bids.py steps the group by the experiment's own rules instead of the normal stepping window: `step` a day,
at most `weekly_limit` from the Monday bid, raised while it loses over `stop_rank_lost` of impressions to ad rank
and never lowered for being visible, held when its campaign loses over stepping.budget_lost_max to budget, never
over its ceiling: `ceiling: fixed` (ceiling_amount) or `ceiling: market` (market_price.py, always under
market_price.safety_limit). Every step is a ledger line with the experiment's id.

Life of an experiment (the routine's run day, account time zone):
  planned   before start: nothing changes yet
  running   start to end: the daily steps it; apply_changes.py refuses hand bids on the group
  judging   after end, until `evaluate` judges it: no daily steps, hand bids still refused
  ended     recorded in reports/experiments.json: the group is back on the normal rules. Unless it was killed, the
            group keeps the experiment's ceiling for later bids (the weekly owns its bid, within its usual limits)
A reserve (optional) holds until the end date: the enabled campaigns other than the experiment's campaign together
stay at or under reserve.others_max (default: reserve.base_cap minus pre_test.budget), so the room the owner added
above the base cap goes to the experiment only (apply_changes.py refuses, daily_guard.py alerts).

evaluate (the weekly; validate by default, --apply to act): per experiment, a table of bid levels (runs of
mid_check.window_days qualifying days: a recorded bid and the campaign under stepping.budget_lost_max lost to budget)
with clicks and spend a day, CPC, lead signals and CRM or ref-matched leads, then
  - mid-test check while running: when the latest level's clicks a day rose under mid_check.min_click_rise while
    its CPC rose over mid_check.max_cpc_rise against the level before, the test ends early and the bid goes back to
    the knee (the median bid of the level before, between pre_test.bid and the current bid)
  - kill rule from the end date on: fewer than kill.min_leads new leads (CRM leads on the group's topic plus leads
    ref-matched to the group, by lead date in the test; lead signals when there is no CRM), or a cost per lead over
    kill.max_cost_per_lead, ends it and reverts the bid to pre_test.bid and the campaign budget to pre_test.budget;
    otherwise the test passed and the bid stays
Ending by the mid-test check or the kill rule is applied, then reported as "Done, reply reverse to undo". The table
and verdicts are written to reports/experiments-<date>.json.

end: ends a running or judging experiment now (only after the owner's "yes" on a decision to end it early), at
--bid (default pre_test.bid), with the campaign budget back to pre_test.budget unless --keep-budget.
reverse: undoes an end (the owner replied "reverse"): the bid and budget from before it. A test ended before its
end date runs again; one past its end date is kept as passed (the owner overrode the kill rule). Bids stay inside limits.bid_floor and the group's ceiling, budgets inside limits.daily_budget_cap.
Starting or extending an experiment is a config change, made only by the owner after a "Needs yes" decision.

Usage: uv run scripts/experiments.py [status]
       uv run scripts/experiments.py evaluate [--apply]
       uv run scripts/experiments.py end <id> [--bid <amount>] [--keep-budget] [--reason "<why>"] [--apply]
       uv run scripts/experiments.py reverse <id> [--apply]
"""
import copy
import json
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

import ads_client
import config
import ledger
import market_price
from topics import ad_group_topic

STATE = Path("reports/experiments.json")
ENDINGS = ("mid_check", "killed", "passed", "ended_by_owner")


# ---- state and phases (pure) -------------------------------------------------------------------------------------

def load_state(path=None):
    path = path or STATE
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.setdefault("ended", {})
    data.setdefault("history", [])
    return data


def save_state(state, path=None):
    path = path or STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    state.setdefault("note", "experiments ended by scripts/experiments.py (evaluate, end, reverse); the config "
                             "holds the experiments themselves")
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def ended(e, state):
    return ((state or {}).get("ended") or {}).get(e["id"])


def phase(e, day, state=None):
    """planned, running, judging or ended on `day` (a run day)."""
    day = str(day)
    if ended(e, state):
        return "ended"
    if day < e["start"]:
        return "planned"
    return "running" if day <= e["end"] else "judging"


def by_id(eid, cfg=None):
    return next((e for e in (cfg or config.get()).experiments if e["id"] == eid), None)


def of_group(campaign, ad_group, cfg=None):
    return [e for e in (cfg or config.get()).experiments if e["campaign"] == campaign and e["ad_group"] == ad_group]


def stepping_today(e, run_day, state=None):
    return phase(e, run_day, state) == "running"


def holding(campaign, ad_group, day, state=None, cfg=None):
    """The experiment that owns the group's bid on `day` (running, or waiting to be judged), or None."""
    return next((e for e in of_group(campaign, ad_group, cfg) if phase(e, day, state) in ("running", "judging")), None)


def ceiling_source(campaign, ad_group, day, state=None, cfg=None):
    """The experiment whose ceiling the group uses on `day`: the latest one started and not killed, or None."""
    started = [e for e in of_group(campaign, ad_group, cfg)
               if e["start"] <= str(day) and (ended(e, state) or {}).get("outcome") != "killed"]
    return max(started, key=lambda e: e["start"], default=None)


def needs_market(campaign, ad_group, day, state=None, cfg=None):
    """True when the group's ceiling on `day` is a market price (so it is worth one query)."""
    cfg = cfg or config.get()
    e = ceiling_source(campaign, ad_group, day, state, cfg)
    return e["ceiling"] == "market" if e else market_price.listed(campaign, ad_group, cfg)


def group_ceiling(campaign, ad_group, day, state=None, market=None, cfg=None):
    """The highest bid the group may get on `day`: its experiment's ceiling (fixed, or the market price under
    market_price.safety_limit), the market price for a market_price.groups group, else limits.bid_ceiling."""
    cfg = cfg or config.get()
    e = ceiling_source(campaign, ad_group, day, state, cfg)
    if e:
        return market_price.ceiling(market, cfg) if e["ceiling"] == "market" else e["ceiling_amount"]
    if market_price.listed(campaign, ad_group, cfg):
        return market_price.ceiling(market, cfg)
    return cfg.limits.bid_ceiling


def step_rules(e, ceiling):
    """daily_bids.decide() rules for a running experiment: raise only, its own step, weekly limit and ceiling."""
    return {"step": e["step"], "weekly_limit": e["weekly_limit"], "low": None, "high": e["stop_rank_lost"],
            "lower": False, "ceiling": ceiling, "experiment": e["id"]}


def reserves(day, state=None, cfg=None):
    """Experiments whose reserve holds on `day`: a reserve, not ended, and `day` not after the end date."""
    cfg = cfg or config.get()
    return [e for e in cfg.experiments if e["reserve"] and str(day) <= e["end"] and not ended(e, state)]


def others_total(budgets, campaign):
    """The total daily budget of the campaigns other than `campaign`. budgets: [(campaign name, budget resource,
    amount)] of the enabled campaigns (a shared budget counts once)."""
    return ads_client.budget_total((res, amount) for name, res, amount in budgets if name != campaign)


def reserve_problem(e, before, after, cur):
    """A FAIL line when a change takes the other campaigns over the reserve (and higher than they were), else None."""
    cap = e["reserve"]["others_max"]
    if after > cap + 1e-9 and after > before + 1e-9:
        return (f"campaigns other than {e['campaign']} would total {cur} {after:.2f} a day, over the {cur} {cap:.2f} "
                f"they may use until {e['end']}: experiment {e['id']} reserves the room above "
                f"{cur} {e['reserve']['base_cap']:g}")
    return None


# ---- levels, the mid-test check and the kill rule (pure) ---------------------------------------------------------

def merge_days(e, stats, recorded):
    """One row per data day: {date, bid, clicks, cost, impressions, lead_signals, rank_lost, budget_lost}.
    stats: {day: {clicks, cost, impressions, lead_signals}} from the account; recorded: {day: the group's entry in a
    daily file's bids section}. The bid on a day is the one its daily entry recorded (the bid in effect that day);
    before the start without one it is pre_test.bid; otherwise unknown (None)."""
    out = []
    for day in sorted(set(stats) | set(recorded)):
        s, r = stats.get(day, {}), recorded.get(day)
        bid = r.get("bid") if r else (e["pre_test"]["bid"] if day < e["start"] else None)
        out.append({"date": day, "bid": bid, "clicks": s.get("clicks", 0), "cost": round(s.get("cost", 0.0), 2),
                    "impressions": s.get("impressions", 0), "lead_signals": s.get("lead_signals", 0.0),
                    "rank_lost": r.get("rank_lost") if r else None, "budget_lost": r.get("budget_lost") if r else None})
    return out


def qualified(days, cfg=None):
    """Days a level can be judged on: a known bid, and the campaign not held back by its budget."""
    limit = (cfg or config.get()).stepping.budget_lost_max
    return [d for d in days if d["bid"] is not None and (d["budget_lost"] or 0) <= limit]


def summarise(days):
    n = len(days)
    clicks, cost = sum(d["clicks"] for d in days), sum(d["cost"] for d in days)
    bids = [d["bid"] for d in days]
    return {"from": days[0]["date"], "to": days[-1]["date"], "days": n, "bid_low": min(bids), "bid_high": max(bids),
            "bid_median": round(statistics.median(bids), 2), "clicks": clicks, "clicks_per_day": round(clicks / n, 2),
            "spend_per_day": round(cost / n, 2), "cpc": round(cost / clicks, 2) if clicks else None,
            "lead_signals": round(sum(d["lead_signals"] for d in days), 1)}


def levels(days, size):
    """Qualified days in runs of `size`, counted back from the latest (the oldest run may be shorter)."""
    out, rest = [], list(days)
    while rest:
        out.insert(0, summarise(rest[-size:]))
        rest = rest[:-size]
    return out


def bid_range(level):
    low, high = level["bid_low"], level["bid_high"]
    return f"{low:.2f}" if low == high else f"{low:.2f} to {high:.2f}"


def mid_check(days, e, current_bid, cfg=None):
    """The mid-test check on the last two levels: {"verdict": end | continue | wait | off, "why", ...}; "end" comes
    with "knee", the bid to go back to."""
    cfg = cfg or config.get()
    mc = e["mid_check"]
    if not mc:
        return {"verdict": "off", "why": "no mid-test check configured"}
    q, size = qualified(days, cfg), mc["window_days"]
    latest, previous = q[-size:], q[-2 * size:-size]
    if len(latest) < mc["min_days"] or len(previous) < mc["min_days"]:
        return {"verdict": "wait", "why": f"needs {mc['min_days']}+ qualifying days at each of the last two levels "
                                          f"({len(previous)} and {len(latest)} so far)"}
    a, b = summarise(previous), summarise(latest)
    if not a["clicks"] or not b["clicks"]:
        return {"verdict": "wait", "why": "no clicks at one of the last two levels", "previous": a, "latest": b}
    click_rise = b["clicks_per_day"] / a["clicks_per_day"] - 1
    cpc_rise = b["cpc"] / a["cpc"] - 1
    out = {"previous": a, "latest": b, "click_rise": round(click_rise, 3), "cpc_rise": round(cpc_rise, 3)}
    moved = (f"bid {bid_range(a)} -> {bid_range(b)}: clicks a day {a['clicks_per_day']:g} -> {b['clicks_per_day']:g} "
             f"({click_rise:+.0%}), CPC {a['cpc']:.2f} -> {b['cpc']:.2f} ({cpc_rise:+.0%})")
    if click_rise < mc["min_click_rise"] and cpc_rise > mc["max_cpc_rise"]:
        low = e["pre_test"]["bid"]
        knee = round(min(max(a["bid_median"], low), max(current_bid, low)), 2)
        return {**out, "verdict": "end", "knee": knee,
                "why": f"{moved}: clicks rose under {mc['min_click_rise']:.0%} while CPC rose over "
                       f"{mc['max_cpc_rise']:.0%}, so extra bid stopped buying clicks; back to the knee {knee:.2f}"}
    return {**out, "verdict": "continue", "why": f"{moved}: the curve is not flat yet"}


def kill_verdict(leads, cost, e):
    """(killed, why) on the end date. leads: new leads during the test; cost: the group's spend during it."""
    k = e["kill"]
    if leads < k["min_leads"]:
        return True, f"{leads:g} new leads during the test, under the {k['min_leads']} it needed"
    cpl = cost / leads if leads else None
    if k["max_cost_per_lead"] is not None:
        if cpl is None and cost > 0:
            return True, f"spent {cost:.2f} with no lead (cost per lead limit {k['max_cost_per_lead']:g})"
        if cpl is not None and cpl > k["max_cost_per_lead"]:
            return True, f"cost per lead {cpl:.2f}, over {k['max_cost_per_lead']:g} ({leads:g} leads, {cost:.2f} spent)"
    return False, f"{leads:g} new leads, {cost:.2f} spent" + (f", cost per lead {cpl:.2f}" if cpl is not None else "")


def crm_leads(e, crm_rows, matches, start, end):
    """New leads during [start, end] (lead dates): CRM leads on the group's topic plus leads ref-matched to the group."""
    topic = ad_group_topic(e["ad_group"])
    fps = {r["fp"] for r in crm_rows if start <= r["date"] <= end and topic and topic in r["topics"]}
    fps |= {m["fp"] for m in matches if m["status"] == "matched" and start <= m["date"] <= end
            and (m["clicks"][0]["campaign"], m["clicks"][0]["ad_group"]) == (e["campaign"], e["ad_group"])}
    return len(fps)


def plan_end(e, group, camps, outcome, bid, budget, why, today, ceiling, cfg=None):
    """(fails, plan, record) to set the group's bid (and its campaign's budget) when an experiment ends or an end is
    reversed. plan has apply_changes.py's shape; record goes to reports/experiments.json. Pure."""
    cfg = cfg or config.get()
    lim, cur = cfg.limits, cfg.account.currency
    fails, plan = [], {}
    camp = next((c for c in camps if c["name"] == e["campaign"]), None)
    where = f"{e['campaign']} / {e['ad_group']}"
    reason = f"experiment {e['id']}: {outcome.replace('_', ' ')}: {why}"
    if bid is not None and round(bid, 2) != round(group["bid"], 2):
        if not lim.bid_floor - 1e-9 <= bid <= ceiling + 1e-9:
            fails.append(f"bid {where}: {cur} {bid:.2f} is outside {lim.bid_floor:.2f} to {ceiling:.2f}")
        else:
            plan[("ad_group", group["resource"])] = {
                "fields": {"cpc_bid_micros": ads_client.micros(bid, cur)},
                "labels": [f"bid       {where}: {cur} {group['bid']:.2f} -> {bid:.2f}"],
                "ledger": [ledger.entry("ad_group", where, "cpc", group["bid"], round(bid, 2), reason,
                                        ad_group_topic(e["ad_group"]), "bid back where extra bid still paid",
                                        day=today, experiment=e["id"])]}
    if budget is not None and camp and round(budget, 2) != round(camp["budget"], 2):
        users = sum(c["budget_resource"] == camp["budget_resource"] for c in camps)
        enabled = [(c["budget_resource"], budget if c is camp else c["budget"]) for c in camps if c["status"] == "ENABLED"]
        total = ads_client.budget_total(enabled)
        if users > 1:
            fails.append(f"budget {camp['name']}: shared with another campaign; set it by hand")
        elif total > lim.daily_budget_cap + 1e-9:
            fails.append(f"budget {camp['name']}: the total daily budget would be {cur} {total:.2f}, over the "
                         f"{cur} {lim.daily_budget_cap:g} cap")
        else:
            plan[("budget", camp["budget_resource"])] = {
                "fields": {"amount_micros": ads_client.micros(budget, cur)},
                "labels": [f"budget    {camp['name']}: {cur} {camp['budget']:.2f} -> {budget:.2f}"],
                "ledger": [ledger.entry("campaign", camp["name"], "daily_budget", camp["budget"], round(budget, 2),
                                        reason, None, "budget back to its level before the test", day=today,
                                        experiment=e["id"])]}
    record = {"date": str(today), "outcome": outcome, "why": why, "bid_before": group["bid"],
              "bid_after": round(bid, 2) if bid is not None else group["bid"],
              "budget_before": camp["budget"] if camp else None,
              "budget_after": round(budget, 2) if budget is not None and camp else (camp["budget"] if camp else None)}
    return fails, plan, record


# ---- the account side -----------------------------------------------------------------------------------------------

def recorded_days(e, out_dir=None):
    """{data day: the group's entry} from the daily files' bids sections."""
    from daily_scout import OUT_DIR, read

    out = {}
    for path in sorted((out_dir or OUT_DIR).glob("week-*.json")):
        for day, entry in (read(path) or {}).get("days", {}).items():
            for g in entry.get("bids") or []:
                if (g.get("campaign"), g.get("ad_group")) == (e["campaign"], e["ad_group"]):
                    out[day] = g
    return out


def group_stats(ga, resource, since, until, cfg=None):
    """{day: {clicks, cost, impressions, lead_signals}} for one ad group on Google Search."""
    from keyword_review import lead_conversions

    where = (f"ad_group.resource_name = '{resource}' AND segments.date BETWEEN '{since}' AND '{until}' "
             "AND segments.ad_network_type = 'SEARCH'")
    blank = {"clicks": 0, "cost": 0.0, "impressions": 0, "lead_signals": 0.0}
    out = {}
    for r in ads_client.rows(ga, f"""SELECT segments.date, segments.ad_network_type, metrics.clicks,
            metrics.cost_micros, metrics.impressions FROM ad_group WHERE {where}"""):
        d = out.setdefault(r.segments.date, dict(blank))
        d["clicks"] += r.metrics.clicks
        d["cost"] += r.metrics.cost_micros / 1e6
        d["impressions"] += r.metrics.impressions
    for (day, _), conv in lead_conversions(ga, "ad_group", ("segments.date", "segments.ad_network_type"), where,
                                           cfg).items():
        out.setdefault(day, dict(blank))["lead_signals"] += conv
    return out


def execute(client, ga, plan, validate_only):
    """One atomic mutate for a plan (apply_changes.py's shape), logged to the ledger. Exits on a failure."""
    import apply_changes
    from google.ads.googleads.errors import GoogleAdsException

    if not plan:
        return
    ops, labels = apply_changes.operations(client, plan)
    try:
        with ledger.pending([x for p in plan.values() for x in p["ledger"]], not validate_only):
            ga.mutate(request={"customer_id": ads_client.customer_id(), "mutate_operations": ops,
                               "validate_only": validate_only})
    except GoogleAdsException as ex:
        sys.exit("FAIL   " + "; ".join(x.message for x in ex.failure.errors) + "  (nothing changed)")
    for label in labels:
        print(f"{'VALID' if validate_only else 'DONE '}  {label}")


def account(ga):
    import apply_changes

    camps, groups, _ = apply_changes.load_account(ga, False)
    return camps, groups


def find_group(e, groups):
    found = [g for g in groups if g["campaign"] == e["campaign"] and g["name"] == e["ad_group"]]
    return found[0] if len(found) == 1 else None


def live_ceiling(ga, e, group, today, state, cfg):
    market = None
    if needs_market(e["campaign"], e["ad_group"], today, state, cfg):
        market, note = market_price.fetch(ga, group["resource"], str(today - timedelta(days=1)),
                                          f"{e['campaign']} / {e['ad_group']}")
        if note:
            print(f"NOTE   {note}")
    return group_ceiling(e["campaign"], e["ad_group"], today, state, market, cfg)


# ---- commands -------------------------------------------------------------------------------------------------------

def describe(e, cfg):
    ceiling = (f"market price under {cfg.market_price.safety_limit:g}" if e["ceiling"] == "market"
               else f"{e['ceiling_amount']:g}")
    reserve = (f"; reserve: others at most {e['reserve']['others_max']:g} until {e['end']}" if e["reserve"] else "")
    return (f"{e['campaign']} / {e['ad_group']}, {e['start']} to {e['end']}: +{e['step']:.0%} a day, "
            f"+/-{e['weekly_limit']:.0%} a week, raised while over {e['stop_rank_lost']:.0%} lost to rank, "
            f"ceiling {ceiling}{reserve}")


def status():
    cfg = config.get()
    if not cfg.experiments:
        print("No experiments in the config.")
        return
    state, today = load_state(), ads_client.today()
    for e in cfg.experiments:
        rec = ended(e, state)
        ph = phase(e, today, state)
        tail = f" ({rec['outcome']} on {rec['date']}: {rec['why']})" if rec else ""
        print(f"{ph.upper():8} {e['id']}: {describe(e, cfg)}{tail}")


def evaluate(validate_only):
    cfg = config.get()
    cur = cfg.account.currency
    if not cfg.experiments:
        print("No experiments in the config.")
        return
    import crm
    import match_ref

    today = ads_client.today()
    yesterday = today - timedelta(days=1)
    state = load_state()
    client = ads_client.load()
    ga = client.get_service("GoogleAdsService")  # keep a reference so the stream isn't closed early
    camps, groups = account(ga)
    crm_rows = crm.load()
    matches = match_ref.match(client, crm_rows) if crm_rows else []
    report, actions = {"date": str(today), "currency": cur, "experiments": []}, []
    print("VALIDATE ONLY (no changes)" if validate_only else "APPLYING CHANGES")
    for e in cfg.experiments:
        ph = phase(e, today, state)
        row = {"id": e["id"], "phase": ph, "campaign": e["campaign"], "ad_group": e["ad_group"],
               "start": e["start"], "end": e["end"]}
        report["experiments"].append(row)
        print(f"EXP    {e['id']} ({ph}): {describe(e, cfg)}")
        if ph in ("planned", "ended"):
            if ph == "ended":
                row["ended"] = ended(e, state)
            continue
        group = find_group(e, groups)
        if group is None:
            print(f"FAIL   {e['id']}: ad group '{e['campaign']} / {e['ad_group']}' not found exactly once")
            row["error"] = "ad group not found"
            continue
        size = (e["mid_check"] or {}).get("window_days", 7)
        since = date.fromisoformat(e["start"]) - timedelta(days=size)
        until = min(yesterday, date.fromisoformat(e["end"]))
        days = merge_days(e, group_stats(ga, group["resource"], since, until, cfg), recorded_days(e))
        table = levels(qualified(days, cfg), size)
        for level in table:
            if crm.enabled(cfg):
                level["leads"] = crm_leads(e, crm_rows, matches, level["from"], level["to"])
            print(f"LEVEL  {e['id']} {level['from']} to {level['to']} ({level['days']} days), bid {bid_range(level)}: "
                  f"{level['clicks_per_day']:g} clicks and {cur} {level['spend_per_day']:.2f} a day, CPC "
                  f"{level['cpc'] if level['cpc'] is not None else '-'}, {level['lead_signals']:g} lead signals"
                  + (f", {level['leads']} leads" if "leads" in level else ""))
        row.update({"bid": group["bid"], "levels": table})
        test_days = [d for d in days if e["start"] <= d["date"] <= e["end"]]
        if str(today) >= e["end"]:
            cost = round(sum(d["cost"] for d in test_days), 2)
            if crm.enabled(cfg):
                leads, source = crm_leads(e, crm_rows, matches, e["start"], e["end"]), "CRM and ref-matched leads"
            else:
                leads, source = round(sum(d["lead_signals"] for d in test_days), 1), "lead signals (no CRM)"
            killed, why = kill_verdict(leads, cost, e)
            row["kill"] = {"leads": leads, "source": source, "cost": cost, "killed": killed, "why": why}
            print(f"KILL   {e['id']}: {'killed' if killed else 'passed'}: {why} ({source})")
            if killed:
                actions.append((e, group, "killed", e["pre_test"]["bid"], e["pre_test"]["budget"], why))
            else:
                actions.append((e, group, "passed", None, None, why))
        else:
            verdict = mid_check(days, e, group["bid"], cfg)
            row["mid_check"] = verdict
            print(f"MID    {e['id']}: {verdict['verdict']}: {verdict['why']}")
            if verdict["verdict"] == "end":
                actions.append((e, group, "mid_check", verdict["knee"], None, verdict["why"]))

    path = Path(f"reports/experiments-{today}.json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"Wrote {path}")

    for e, group, outcome, bid, budget, why in actions:
        ceiling = live_ceiling(ga, e, group, today, state, cfg) if bid is not None else cfg.limits.bid_ceiling
        fails, plan, record = plan_end(e, group, camps, outcome, bid, budget, why, today, ceiling, cfg)
        if fails:
            for line in fails:
                print(f"FAIL   {e['id']}: {line}")
            print(f"FAIL   {e['id']}: not ended; fix the cause and run evaluate again")
            continue
        execute(client, ga, plan, validate_only)
        if validate_only:
            continue
        state["ended"][e["id"]] = record
        save_state(state)
        if outcome == "passed":
            print(f"ENDED  {e['id']} passed: {why}; the bid stays at {cur} {group['bid']:.2f} and the weekly owns it")
        else:
            print(f"NOTIFY EXP {e['id']} ended ({outcome.replace('_', ' ')}): bid {cur} {record['bid_before']:.2f} -> "
                  f"{record['bid_after']:.2f}; {why}")
            print(f"DECISION Done, reply reverse to undo: experiment {e['id']} ended by its "
                  f"{'mid-test check' if outcome == 'mid_check' else 'kill rule'} "
                  f"(undo: uv run scripts/experiments.py reverse {e['id']} --apply)")


def end(eid, bid, keep_budget, reason, validate_only):
    cfg = config.get()
    e = by_id(eid, cfg)
    if e is None:
        sys.exit(f"FAIL   no experiment '{eid}' in the config")
    today, state = ads_client.today(), load_state()
    if phase(e, today, state) not in ("running", "judging"):
        sys.exit(f"FAIL   {eid} is {phase(e, today, state)}: only a running or judging experiment can be ended")
    client = ads_client.load()
    ga = client.get_service("GoogleAdsService")  # keep a reference so the stream isn't closed early
    camps, groups = account(ga)
    group = find_group(e, groups)
    if group is None:
        sys.exit(f"FAIL   ad group '{e['campaign']} / {e['ad_group']}' not found exactly once")
    bid = e["pre_test"]["bid"] if bid is None else bid
    budget = None if keep_budget else e["pre_test"]["budget"]
    print("VALIDATE ONLY (no changes)" if validate_only else "APPLYING CHANGES")
    fails, plan, record = plan_end(e, group, camps, "ended_by_owner", bid, budget, reason, today,
                                   live_ceiling(ga, e, group, today, state, cfg), cfg)
    if fails:
        for line in fails:
            print(f"FAIL   {line}")
        sys.exit("Nothing changed.")
    execute(client, ga, plan, validate_only)
    if not validate_only:
        state["ended"][eid] = record
        save_state(state)
        print(f"ENDED  {eid} by the owner: {reason}")


def reverse(eid, validate_only):
    cfg = config.get()
    e = by_id(eid, cfg)
    state = load_state()
    rec = ended(e, state) if e else None
    if rec is None:
        sys.exit(f"FAIL   no ended experiment '{eid}' to reverse")
    if rec["outcome"] == "passed":
        print(f"{eid} passed its kill rule and changed nothing: nothing to reverse")
        return
    today = ads_client.today()
    without = copy.deepcopy(state)
    without["ended"].pop(eid)
    client = ads_client.load()
    ga = client.get_service("GoogleAdsService")  # keep a reference so the stream isn't closed early
    camps, groups = account(ga)
    group = find_group(e, groups)
    if group is None:
        sys.exit(f"FAIL   ad group '{e['campaign']} / {e['ad_group']}' not found exactly once")
    budget = rec["budget_before"] if rec.get("budget_after") != rec.get("budget_before") else None
    print("VALIDATE ONLY (no changes)" if validate_only else "APPLYING CHANGES")
    fails, plan, _ = plan_end(e, group, camps, "reversed", rec["bid_before"], budget,
                              f"owner replied reverse to the end on {rec['date']}", today,
                              live_ceiling(ga, e, group, today, without, cfg), cfg)
    if fails:
        for line in fails:
            print(f"FAIL   {line}")
        sys.exit("Nothing changed.")
    execute(client, ga, plan, validate_only)
    if not validate_only:
        without["history"].append({**rec, "id": eid, "reversed": str(today)})
        if str(today) <= e["end"]:
            print(f"REVERSED {eid}: it runs again until {e['end']}")
        else:
            without["ended"][eid] = {**rec, "date": str(today), "outcome": "passed",
                                     "why": f"the owner reversed its {rec['outcome'].replace('_', ' ')} of {rec['date']}",
                                     "bid_after": rec["bid_before"], "budget_after": rec["budget_before"]}
            print(f"REVERSED {eid}: kept as passed (past its end date); the weekly owns the bid")
        save_state(without)


def main():
    args = sys.argv[1:]
    validate_only = "--apply" not in args

    def option(name):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None

    words = [a for a in args if not a.startswith("--") and a not in (option("--bid"), option("--reason"))]
    command = words[0] if words else "status"
    if command == "status":
        status()
    elif command == "evaluate":
        evaluate(validate_only)
    elif command in ("end", "reverse") and len(words) > 1:
        if command == "end":
            bid = option("--bid")
            end(words[1], float(bid) if bid else None, "--keep-budget" in args,
                option("--reason") or "ended early on the owner's yes", validate_only)
        else:
            reverse(words[1], validate_only)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
