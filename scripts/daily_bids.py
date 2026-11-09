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
Stepping window: a group steps only for stepping.window_days from its first recorded step (from the daily files'
bids sections). After that it is "settled": no daily step and no BID or BUDGET notice; the weekly review sets its bid.

Adds a "bids" section to the day in reports/daily/week-<MONDAY>.json (run after daily_scout.py) and prints one
NOTIFY line per change, plus one per group newly held by its campaign budget. Each applied step is logged to
reports/changes.jsonl (ledger.py, routine "daily").

Usage: uv run scripts/daily_bids.py [DATE]          (validate only)
       uv run scripts/daily_bids.py [DATE] --apply  (makes the change)
"""
import json
import sys
from datetime import date, timedelta

import ads_client
import config
import ledger
from ads_client import rows
from daily_scout import OUT_DIR, previous_day, read, week_path
from google.ads.googleads.errors import GoogleAdsException
from topics import ad_group_topic, winning


def managed(channel, ad_group):
    """True for the ad groups this script may step: winning-topic groups in Search campaigns."""
    return channel == "SEARCH" and ad_group_topic(ad_group) in winning()


def first_steps(out_dir=None):
    """{(campaign, ad group): run date of its first recorded bid step} from the daily files' bids sections."""
    out = {}
    for path in sorted((out_dir or OUT_DIR).glob("week-*.json")):
        for day, entry in sorted((read(path) or {}).get("days", {}).items()):
            for g in entry.get("bids") or []:
                if g.get("action") in ("raise", "lower"):
                    out.setdefault((g["campaign"], g["ad_group"]), date.fromisoformat(day) + timedelta(days=1))
    return out


def window():
    return timedelta(days=config.get().stepping.window_days)


def settled(campaign, ad_group, run_day, firsts=None):
    """True when the group's stepping window has ended by `run_day`."""
    first = (first_steps() if firsts is None else firsts).get((campaign, ad_group))
    return first is not None and run_day >= first + window()


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


def decide(bid, impressions, rank_lost, budget_lost, approved, late_change, start_bid, weekly_limit_applies, cfg=None):
    """(action, why, new bid) for one group that is still in its stepping window. Pure, for tests.
    late_change: (time, old, new) of a bid change after the data day ended, or None."""
    cfg = cfg or config.get()
    s, lim = cfg.stepping, cfg.limits
    low_band, high_band = s.rank_lost_band
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
    elif rank_lost < low_band and impressions >= s.min_impressions:
        direction, why = -1, f"lost only {rank_lost:.0%} to rank"
    else:
        return "hold", (f"lost {rank_lost:.0%} to rank (in the {low_band:.0%} to {high_band:.0%} band)"
                        if impressions >= s.min_impressions or rank_lost >= low_band
                        else f"only {impressions} impressions"), bid
    low, high = lim.bid_floor, lim.bid_ceiling
    if weekly_limit_applies:
        low, high = max(low, start_bid * (1 - s.weekly_limit)), min(high, start_bid * (1 + s.weekly_limit))
    new = round(min(max(bid * (1 + direction * s.step), low), high), 2)
    if (new - bid) * direction <= 0:
        return "hold", f"{why}, but at the limit ({cur} {low:.2f} to {high:.2f} this week)", bid
    return ("raise" if direction > 0 else "lower"), why, new


def plan(client, day):
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

    firsts = first_steps()
    out = []
    for r in rows(ga, """SELECT campaign.name, ad_group.name, ad_group.resource_name, ad_group.cpc_bid_micros
            FROM ad_group WHERE campaign.status = 'ENABLED' AND campaign.advertising_channel_type = 'SEARCH'
            AND ad_group.status = 'ENABLED'"""):
        name, res = r.ad_group.name, r.ad_group.resource_name
        if not managed("SEARCH", name):
            continue
        bid = r.ad_group.cpc_bid_micros / 1e6
        m = stats.get(res)
        impressions = m.impressions if m else 0
        rank_lost = m.search_rank_lost_impression_share if m and impressions else None
        row = {"campaign": r.campaign.name, "ad_group": name, "resource": res, "bid": bid, "new_bid": bid,
               "impressions": impressions, "rank_lost": rank_lost,
               "budget_lost": round(budget_lost.get(r.campaign.name, 0.0), 3)}
        out.append(row)
        if settled(r.campaign.name, name, run_day, firsts):
            ended = firsts[(r.campaign.name, name)] + window() - timedelta(days=1)
            row["action"], row["why"] = "settled", f"stepping window ended {ended}; the weekly review sets this bid"
            continue
        group_changes = changes.get(res, [])
        late = [c for c in group_changes if c[0] >= str(run_day)]
        new_until = str(cfg.stepping.new_groups.get(name, ""))
        row["action"], row["why"], row["new_bid"] = decide(
            bid, impressions, rank_lost, row["budget_lost"], res in approved, late[-1] if late else None,
            week_start_bid(group_changes, bid), str(run_day) >= new_until, cfg)
    return out


def main():
    cfg = config.get()
    if not cfg.stepping.enabled:
        print("stepping.enabled is false in argmax.yaml: no daily bid steps")
        return
    if not cfg.winning_topics:
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
    groups = plan(client, day)
    steps = [g for g in groups if g["action"] in ("raise", "lower")]
    cur = ads_client.currency()

    entries = [ledger.entry("ad_group", f"{g['campaign']} / {g['ad_group']}", "cpc", g["bid"], g["new_bid"],
                            f"daily step: {g['why']}", ad_group_topic(g["ad_group"]),
                            "rank-lost impression share moves toward the band", routine="daily") for g in steps]
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
        print(f"{label} {g['campaign']} / {g['ad_group']}: {cur} {g['bid']:.2f} -> {g['new_bid']:.2f} ({g['why']})")

    if not validate_only:
        path = week_path(day)
        week = read(path)
        if week and day in week["days"]:
            week["days"][day]["bids"] = [{k: v for k, v in g.items() if k != "resource"} for g in groups]
            path.write_text(json.dumps(week, ensure_ascii=False, indent=1))
        else:
            print(f"NOTIFY ALERT daily_bids: {day} is missing from {path}; run daily_scout.py first")
        for g in steps:
            print(f"NOTIFY BID   {g['campaign']} / {g['ad_group']}: {cur} {g['bid']:.2f} -> {g['new_bid']:.2f} ({g['why']})")
        prev = previous_day(day)
        for g in new_budget_holds(groups, (prev or {}).get("bids")):
            print(f"NOTIFY BUDGET {g['campaign']} / {g['ad_group']} held at {cur} {g['bid']:.2f}: {g['why']}")


if __name__ == "__main__":
    main()
