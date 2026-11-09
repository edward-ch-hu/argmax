"""Daily bid steps for the winning-topic Search ad groups (config: winning_topics, ad_group_topics), Manual CPC.

Aims each group at a visibility sweet spot: losing stepping.rank_lost_band (default 20% to 50%) of impressions to
ad rank. Judged on yesterday's data.
- raise one step (stepping.step, default 10%) when rank-lost impression share is over the band, or when the group
  got 0 impressions but has an approved ad
- lower one step when rank-lost impression share is under the band (already visible, save money); needs
  stepping.min_impressions
- hold when the campaign lost over stepping.budget_lost_max of impressions to budget (a higher bid only burns the
  budget faster; the fix is moving budget away from losing topics, done in the weekly review), and otherwise
Limits: one step per group per day (none if the bid changed after the data day ended), stepping.weekly_limit per
group per calendar week (from the bid on Monday; groups in stepping.new_groups skip this until their date), and
limits.bid_floor to limits.bid_ceiling. Only steps on yesterday's data; an older DATE prints the plan, never applies.
Stepping window: a group steps only for stepping.window_days from its first daily evaluation, stepped or not. The
start is the earliest of: reports/stepping.json (written on every --apply run: the first day each group was
evaluated, never overwritten), the first daily step in reports/changes.jsonl (routine daily, field cpc), and the first
day the group shows up in a daily file's bids section. After the window the group is "settled": no daily step and no
BID or BUDGET notice; the weekly review sets its bid. A group the daily never evaluated has no window yet, so the
weekly may set its bid (apply_changes.py refuses bids only inside a window).

Experiments (config: experiments, scripts/experiments.py): from its start date to its end date a group in a running
experiment is stepped by the experiment's own rules (its step, weekly limit and stop_rank_lost; raised only, never
lowered for being visible; held when its campaign loses over stepping.budget_lost_max to budget), whatever its
stepping window says, and also when it is not a winning-topic group. Ceilings: a group's experiment ceiling (fixed,
or the market price), the market price for groups in market_price.groups, else limits.bid_ceiling; a market price
never goes over market_price.safety_limit (market_price.py). The market price the run saw is recorded as
"market_price" in the group's bids row, and each experiment step carries the experiment's id in the bids row and
in the ledger.

Adds a "bids" section to the day in reports/daily/week-<MONDAY>.json (run after daily_scout.py) and prints one
NOTIFY line per change, plus one per group newly held by its campaign budget. Each applied step is logged to
reports/changes.jsonl (ledger.py, routine "daily").

Usage: uv run scripts/daily_bids.py [DATE]          (validate only)
       uv run scripts/daily_bids.py [DATE] --apply  (makes the change)
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import ads_client
import config
import experiments
import ledger
import market_price
from ads_client import rows
from daily_scout import OUT_DIR, previous_day, read, week_path
from google.ads.googleads.errors import GoogleAdsException
from topics import ad_group_topic, winning


def managed(channel, ad_group):
    """True for the ad groups this script may step: winning-topic groups in Search campaigns."""
    return channel == "SEARCH" and ad_group_topic(ad_group) in winning()


STATE = Path("reports/stepping.json")


def daily_file_starts(out_dir=None):
    """{(campaign, ad group): run date of its first evaluation} from the daily files' bids sections (any action)."""
    out = {}
    for path in sorted((out_dir or OUT_DIR).glob("week-*.json")):
        for day, entry in sorted((read(path) or {}).get("days", {}).items()):
            for g in entry.get("bids") or []:
                out.setdefault((g["campaign"], g["ad_group"]), date.fromisoformat(day) + timedelta(days=1))
    return out


def ledger_starts(entries=None):
    """{(campaign, ad group): date of its first daily bid step} from the ledger (applied lines only)."""
    out = {}
    for e in sorted(ledger.read(entries=entries), key=lambda e: e["date"]):
        if e.get("routine") != "daily" or e.get("field") != "cpc" or e.get("level") != "ad_group":
            continue
        key = (e["campaign"], e["ad_group"]) if e.get("ad_group") else tuple(e["entity"].split(" / ", 1))
        out.setdefault(key, date.fromisoformat(e["date"]))
    return out


def recorded_starts(path=None):
    """{(campaign, ad group): first evaluation} from reports/stepping.json."""
    path = path or STATE
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {(g["campaign"], g["ad_group"]): date.fromisoformat(g["first_evaluated"]) for g in data.get("groups", [])}


def record_evaluations(groups, run_day, path=None):
    """Adds the groups evaluated on `run_day` that reports/stepping.json does not hold yet. Never moves a start."""
    path = path or STATE
    known = recorded_starts(path)
    new = [(g["campaign"], g["ad_group"]) for g in groups if (g["campaign"], g["ad_group"]) not in known]
    if not new:
        return []
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "note": "first daily evaluation per winning-topic group (daily_bids.py); the stepping window starts here"}
    data.setdefault("groups", []).extend({"campaign": c, "ad_group": a, "first_evaluated": str(run_day)} for c, a in new)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return new


def window_starts(out_dir=None, entries=None, state=None):
    """{(campaign, ad group): the day its stepping window started}: the earliest of the three records."""
    out = {}
    for source in (recorded_starts(state), ledger_starts(entries), daily_file_starts(out_dir)):
        for key, day in source.items():
            out[key] = min(day, out.get(key, day))
    return out


def window():
    return timedelta(days=config.get().stepping.window_days)


def settled(campaign, ad_group, run_day, starts=None):
    """True when the group's stepping window has ended by `run_day`."""
    start = (window_starts() if starts is None else starts).get((campaign, ad_group))
    return start is not None and run_day >= start + window()


def stepping(campaign, ad_group, run_day, starts=None):
    """True while the group is inside its stepping window (the daily owns its bid). False before its first daily
    evaluation and after the window."""
    start = (window_starts() if starts is None else starts).get((campaign, ad_group))
    return start is not None and start <= run_day < start + window()


def bid_changes(ga, monday, until):
    """{ad group resource: [(time, old bid, new bid, was enabled)]} for bid changes from Monday to `until`, oldest first."""
    out = {}
    for r in rows(ga, f"""SELECT change_event.change_date_time, change_event.change_resource_name,
            change_event.changed_fields, change_event.old_resource, change_event.new_resource FROM change_event
            WHERE change_event.change_date_time >= '{monday}' AND change_event.change_date_time <= '{until}'
            AND change_event.change_resource_type = 'AD_GROUP' LIMIT 10000"""):
        e = r.change_event
        old, new = e.old_resource.ad_group, e.new_resource.ad_group
        if old.cpc_bid_micros != new.cpc_bid_micros:
            enabled = old.status.name == "PAUSED" and new.status.name == "ENABLED"
            out.setdefault(e.change_resource_name, []).append(
                (e.change_date_time, old.cpc_bid_micros / 1e6, new.cpc_bid_micros / 1e6, enabled))
    return {k: sorted(v) for k, v in out.items()}


def week_start_bid(group_changes, bid):
    """The bid on Monday: the old bid of the week's first change (the new one if that change enabled the group)."""
    first = group_changes[0] if group_changes else None
    return (first[2] if first[3] else first[1]) if first else bid


def budget_held(groups):
    return {(g["campaign"], g["ad_group"]) for g in groups or []
            if g.get("action") == "hold" and "to budget" in g.get("why", "")}


def new_budget_holds(groups, previous_groups):
    """Groups held by budget today that were not held by budget on the previous recorded day."""
    before = budget_held(previous_groups)
    return [g for g in groups if (g["campaign"], g["ad_group"]) in budget_held(groups) - before]


def stepping_rules(cfg=None, ceiling=None):
    """decide() rules for a winning group inside its stepping window (config: stepping)."""
    cfg = cfg or config.get()
    s = cfg.stepping
    return {"step": s.step, "weekly_limit": s.weekly_limit, "low": s.rank_lost_band[0], "high": s.rank_lost_band[1],
            "lower": True, "ceiling": cfg.limits.bid_ceiling if ceiling is None else ceiling, "experiment": None}


def decide(bid, impressions, rank_lost, budget_lost, approved, late_change, start_bid, weekly_limit_applies, cfg=None,
           rules=None):
    """(action, why, new bid) for one group that is still in its stepping window or in a running experiment. Pure.
    late_change: (time, old, new) of a bid change after the data day ended, or None. rules: stepping_rules() (the
    default) or experiments.step_rules()."""
    cfg = cfg or config.get()
    s, lim = cfg.stepping, cfg.limits
    r = rules or stepping_rules(cfg)
    low_band, high_band = r["low"], r["high"]
    cur = cfg.account.currency
    if late_change:
        return "hold", f"bid already changed at {late_change[0][:16]} ({late_change[1]:.2f} -> {late_change[2]:.2f})", bid
    if budget_lost > s.budget_lost_max:
        return "hold", f"campaign lost {budget_lost:.0%} of impressions to budget", bid
    if rank_lost is None:
        if not approved:
            return "hold", "0 impressions and no approved ad", bid
        direction, why = 1, "0 impressions with an approved ad"
    elif rank_lost > high_band:
        direction, why = 1, f"lost {rank_lost:.0%} to rank"
    elif not r["lower"]:
        return "hold", f"lost {rank_lost:.0%} to rank (experiment {r['experiment']}: raised only while over " \
                       f"{high_band:.0%}, never lowered)", bid
    elif rank_lost < low_band and impressions >= s.min_impressions:
        direction, why = -1, f"lost only {rank_lost:.0%} to rank"
    else:
        return "hold", (f"lost {rank_lost:.0%} to rank (in the {low_band:.0%} to {high_band:.0%} band)"
                        if impressions >= s.min_impressions or rank_lost >= low_band
                        else f"only {impressions} impressions"), bid
    low, high = lim.bid_floor, r["ceiling"]
    if weekly_limit_applies:
        low, high = max(low, start_bid * (1 - r["weekly_limit"])), min(high, start_bid * (1 + r["weekly_limit"]))
    new = round(min(max(bid * (1 + direction * r["step"]), low), high), 2)
    if (new - bid) * direction <= 0:
        return "hold", f"{why}, but at the limit ({cur} {low:.2f} to {high:.2f} this week)", bid
    return ("raise" if direction > 0 else "lower"), why, new


def plan(client, day):
    """(groups, notes): one row per winning-topic group and per group in a running experiment, and NOTE lines."""
    cfg = config.get()
    ga = client.get_service("GoogleAdsService")  # keep a reference so the stream isn't closed early
    run_day = date.fromisoformat(day) + timedelta(days=1)
    monday = run_day - timedelta(days=run_day.weekday())
    changes = bid_changes(ga, monday, run_day + timedelta(days=1))

    budget_lost = {r.campaign.name: r.metrics.search_budget_lost_impression_share for r in rows(ga, f"""
        SELECT campaign.name, metrics.search_budget_lost_impression_share FROM campaign
        WHERE segments.date = '{day}' AND campaign.status = 'ENABLED' AND campaign.advertising_channel_type = 'SEARCH'""")}
    approved = {r.ad_group.resource_name for r in rows(ga, """SELECT ad_group.resource_name FROM ad_group_ad
        WHERE ad_group_ad.status = 'ENABLED' AND ad_group_ad.policy_summary.approval_status IN
        ('APPROVED', 'APPROVED_LIMITED')""")}
    stats = {r.ad_group.resource_name: r.metrics for r in rows(ga, f"""SELECT ad_group.resource_name,
        metrics.impressions, metrics.search_rank_lost_impression_share FROM ad_group WHERE segments.date = '{day}'
        AND campaign.status = 'ENABLED' AND campaign.advertising_channel_type = 'SEARCH'""")}

    starts = window_starts()
    state = experiments.load_state()
    running = {(e["campaign"], e["ad_group"]): e for e in cfg.experiments
               if experiments.stepping_today(e, run_day, state)}
    out, notes = [], []
    for r in rows(ga, """SELECT campaign.name, ad_group.name, ad_group.resource_name, ad_group.cpc_bid_micros
            FROM ad_group WHERE campaign.status = 'ENABLED' AND campaign.advertising_channel_type = 'SEARCH'
            AND ad_group.status = 'ENABLED'"""):
        name, res = r.ad_group.name, r.ad_group.resource_name
        exp = running.get((r.campaign.name, name))
        if not exp and not managed("SEARCH", name):
            continue
        bid = r.ad_group.cpc_bid_micros / 1e6
        m = stats.get(res)
        impressions = m.impressions if m else 0
        rank_lost = m.search_rank_lost_impression_share if m and impressions else None
        row = {"campaign": r.campaign.name, "ad_group": name, "resource": res, "bid": bid, "new_bid": bid,
               "impressions": impressions, "rank_lost": rank_lost,
               "budget_lost": round(budget_lost.get(r.campaign.name, 0.0), 3)}
        if exp:
            row["experiment"] = exp["id"]
        out.append(row)
        market = None
        if experiments.needs_market(r.campaign.name, name, run_day, state, cfg):  # recorded for the weekly too
            market, note = market_price.fetch(ga, res, day, f"{r.campaign.name} / {name}")
            row["market_price"] = market
            if note:
                notes.append(note)
        if not exp and settled(r.campaign.name, name, run_day, starts):
            ended = starts[(r.campaign.name, name)] + window() - timedelta(days=1)
            row["action"], row["why"] = "settled", f"stepping window ended {ended}; the weekly review sets this bid"
            continue
        ceiling = experiments.group_ceiling(r.campaign.name, name, run_day, state, market, cfg)
        group_changes = changes.get(res, [])
        late = [c for c in group_changes if c[0] >= str(run_day)]
        if exp:
            rules, weekly = experiments.step_rules(exp, ceiling), True
        else:
            rules, weekly = stepping_rules(cfg, ceiling), str(run_day) >= str(cfg.stepping.new_groups.get(name, ""))
        row["action"], row["why"], row["new_bid"] = decide(
            bid, impressions, rank_lost, row["budget_lost"], res in approved, late[-1] if late else None,
            week_start_bid(group_changes, bid), weekly, cfg, rules)
    return out, notes


def step_entries(steps):
    """Ledger lines for the day's steps; an experiment step carries the experiment's id."""
    out = []
    for g in steps:
        exp = g.get("experiment")
        out.append({**ledger.entry("ad_group", f"{g['campaign']} / {g['ad_group']}", "cpc", g["bid"], g["new_bid"],
                                   f"{'experiment ' + exp if exp else 'daily'} step: {g['why']}",
                                   ad_group_topic(g["ad_group"]),
                                   "rank-lost impression share moves toward the band" if not exp else
                                   "more impressions until rank-lost is under the experiment's stop",
                                   routine="daily", experiment=exp),
                    "campaign": g["campaign"], "ad_group": g["ad_group"]})
    return out


def main():
    cfg = config.get()
    if not cfg.stepping.enabled:
        print("stepping.enabled is false in argmax.yaml: no daily bid steps")
        return
    if not cfg.winning_topics and not cfg.experiments:
        print("winning_topics is empty in argmax.yaml: no group to step")
        return
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    yesterday = str(ads_client.today() - timedelta(days=1))
    day = args[0] if args else yesterday
    is_yesterday = day == yesterday
    validate_only = "--apply" not in sys.argv or not is_yesterday
    if "--apply" in sys.argv and not is_yesterday:
        print(f"{day} is not yesterday: plan only, nothing applied")
    client = ads_client.load()
    groups, notes = plan(client, day)
    for note in notes:
        print(f"NOTE  {note}")
    steps = [g for g in groups if g["action"] in ("raise", "lower")]
    cur = ads_client.currency()
    entries = step_entries(steps)
    ops = []
    for g in steps:
        op = client.get_type("AdGroupOperation")
        op.update.resource_name = g["resource"]
        op.update.cpc_bid_micros = ads_client.micros(g["new_bid"])
        op.update_mask.paths.append("cpc_bid_micros")
        ops.append(op)
    if ops:
        try:
            with ledger.pending(entries, not validate_only):
                client.get_service("AdGroupService").mutate_ad_groups(
                    request={"customer_id": ads_client.customer_id(), "operations": ops, "validate_only": validate_only})
        except GoogleAdsException as ex:
            sys.exit("FAIL " + "; ".join(e.message for e in ex.failure.errors))

    for g in groups:
        label = ("VALID" if validate_only else "DONE ") if g in steps else "SETTL" if g["action"] == "settled" else "HOLD "
        extra = "".join([f", experiment {g['experiment']}" if g.get("experiment") else "",
                         f", market price {g['market_price']:.2f}" if g.get("market_price") else ""])
        print(f"{label} {g['campaign']} / {g['ad_group']}: {cur} {g['bid']:.2f} -> {g['new_bid']:.2f} ({g['why']}{extra})")
    run_day = date.fromisoformat(day) + timedelta(days=1)
    state = experiments.load_state()
    for e in cfg.experiments:
        if experiments.phase(e, run_day, state) == "judging":
            print(f"NOTE  experiment {e['id']} stopped stepping after {e['end']}: the weekly judges it "
                  "(experiments.py evaluate)")

    if not validate_only:
        managed_groups = [g for g in groups if managed("SEARCH", g["ad_group"])]
        for c, a in record_evaluations(managed_groups, run_day):
            print(f"NOTE  {c} / {a}: first daily evaluation, its {cfg.stepping.window_days}-day stepping window starts")
        path = week_path(day)
        week = read(path)
        if week and day in week["days"]:
            week["days"][day]["bids"] = [{k: v for k, v in g.items() if k != "resource"} for g in groups]
            path.write_text(json.dumps(week, ensure_ascii=False, indent=1))
        else:
            print(f"NOTIFY ALERT daily_bids: {day} is missing from {path}; run daily_scout.py first")
        for g in steps:
            tag = f", experiment {g['experiment']}" if g.get("experiment") else ""
            print(f"NOTIFY BID   {g['campaign']} / {g['ad_group']}: {cur} {g['bid']:.2f} -> {g['new_bid']:.2f} "
                  f"({g['why']}{tag})")
        prev = previous_day(day)
        for g in new_budget_holds(groups, (prev or {}).get("bids")):
            print(f"NOTIFY BUDGET {g['campaign']} / {g['ad_group']} held at {cur} {g['bid']:.2f}: {g['why']}")


if __name__ == "__main__":
    main()
