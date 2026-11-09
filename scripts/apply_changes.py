"""Bid, budget and status changes from one JSON file, checked against the Autonomy limits in argmax.yaml.

The only way the weekly review changes bids, budgets and campaign / ad group / keyword status (new keywords and
negatives go through apply_keyword_review.py). The file is reports/changes-<date>.json; every list is optional.
Amounts are in the account currency (account.currency):
{
 "date": "2026-01-05",
 "routine": "weekly",
 "reason": "one line: why",
 "budgets": [{"campaign": "US - Search", "daily_budget": 60, "expected_effect": "analytics loses less to budget"}],
 "bids":    [{"campaign": "US - Search", "ad_group": "Reporting", "cpc": 1.20,
              "reason": "0 CRM wins on reporting in 90 days", "expected_effect": "reporting spend share down"}],
 "status":  [{"level": "campaign", "campaign": "UK - Search", "status": "PAUSED"},
             {"level": "ad_group", "campaign": "US - Search", "ad_group": "Reporting", "status": "PAUSED"},
             {"level": "keyword", "campaign": "US - Search", "ad_group": "Analytics", "keyword": "web analytics tool",
              "match": "PHRASE", "status": "PAUSED"}]
}
Campaign and ad group names are exact. Keyword text is compared case-insensitively; "match" (EXACT, PHRASE, BROAD)
is needed only when the text exists with more than one match type. "status" is PAUSED or ENABLED.
Any item may carry its own "reason" (else the file's) and an "expected_effect" (short text); with --apply every
change is appended to reports/changes.jsonl (ledger.py) for the monthly change audit.

Refuses the whole file (FAIL lines, exit 1, nothing changed) when:
- the total daily budget across enabled campaigns after the change is over limits.daily_budget_cap (status changes
  in the same file count; paused campaigns don't; a budget shared by several campaigns counts once)
- an ad group bid is more than limits.weekly_bid_change away from that group's bid at the start of the week
  (Monday 00:00 in the account time zone), or outside limits.bid_floor to the group's ceiling: limits.bid_ceiling,
  or for a group with a started (not killed) experiment its ceiling, or for a market_price.groups group the market
  price (never over market_price.safety_limit; experiments.group_ceiling)
- a bid is set on a winning-topic Search group still inside its daily_bids.py stepping window (window_days from the
  group's first daily evaluation; a group the daily never evaluated has no window)
- a bid is set on a group an experiment holds (from its start date until experiments.py evaluate judges it)
- an experiment's reserve holds (config: experiments, reserve) and the enabled campaigns other than its campaign
  would total over its reserve.others_max, higher than before the change
- a Performance Max campaign is enabled (unless limits.allow_enable_performance_max)
- a name does not match exactly one campaign, ad group or keyword, or the same thing is listed twice
All changes go in one atomic request.

Usage: uv run scripts/apply_changes.py reports/changes-<date>.json          (validate only)
       uv run scripts/apply_changes.py reports/changes-<date>.json --apply  (makes the changes)
"""
import json
import sys
from datetime import timedelta
from pathlib import Path

import ads_client
import config
import daily_bids
import experiments
import ledger
import market_price
from ads_client import rows
from google.ads.googleads.errors import GoogleAdsException
from topics import ad_group_topic

STATUSES = ("PAUSED", "ENABLED")
FIELD_NAMES = {"amount_micros": "daily_budget", "cpc_bid_micros": "cpc"}


def one(found, what, fails):
    if len(found) != 1:
        fails.append(f"{what}: {'no match' if not found else f'{len(found)} matches'}")
        return None
    return found[0]


def load_account(ga, with_keywords):
    """The account as plain dicts: campaigns, ad groups and (when needed) keywords."""
    camps = [{"resource": r.campaign.resource_name, "name": r.campaign.name, "status": r.campaign.status.name,
              "channel": r.campaign.advertising_channel_type.name, "budget_resource": r.campaign_budget.resource_name,
              "budget": r.campaign_budget.amount_micros / 1e6}
             for r in rows(ga, """SELECT campaign.resource_name, campaign.name, campaign.status,
                campaign.advertising_channel_type, campaign_budget.resource_name, campaign_budget.amount_micros
                FROM campaign WHERE campaign.status != 'REMOVED'""")]
    groups = [{"campaign": r.campaign.name, "channel": r.campaign.advertising_channel_type.name,
               "resource": r.ad_group.resource_name, "name": r.ad_group.name, "status": r.ad_group.status.name,
               "bid": r.ad_group.cpc_bid_micros / 1e6}
              for r in rows(ga, """SELECT campaign.name, campaign.advertising_channel_type, ad_group.resource_name,
                ad_group.name, ad_group.status, ad_group.cpc_bid_micros FROM ad_group
                WHERE ad_group.status != 'REMOVED' AND campaign.status != 'REMOVED'""")]
    keywords = []
    if with_keywords:
        keywords = [{"campaign": r.campaign.name, "ad_group": r.ad_group.name,
                     "resource": r.ad_group_criterion.resource_name, "text": r.ad_group_criterion.keyword.text,
                     "match": r.ad_group_criterion.keyword.match_type.name, "status": r.ad_group_criterion.status.name}
                    for r in rows(ga, """SELECT campaign.name, ad_group.name, ad_group_criterion.resource_name,
                        ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type, ad_group_criterion.status
                        FROM ad_group_criterion WHERE ad_group_criterion.type = 'KEYWORD'
                        AND ad_group_criterion.negative = FALSE AND ad_group_criterion.status != 'REMOVED'
                        AND ad_group.status != 'REMOVED' AND campaign.status != 'REMOVED'""")]
    return camps, groups, keywords


def evaluate(changes, camps, groups, keywords, bid_history, starts, today, cfg=None, state=None, ceilings=None):
    """Check a changes file against the account (plain dicts). Pure, for tests.
    bid_history: {ad group resource: [(time, old, new, was_enabled)]} since Monday; starts: daily_bids.window_starts();
    state: experiments.load_state() (default: no experiment ended); ceilings: {(campaign, ad group): ceiling} for
    groups whose ceiling needs a live market price (default: experiments.group_ceiling without one).
    Returns (fails, plan, (total before, total after)); plan = {(kind, resource): {fields, labels, ledger}}."""
    cfg = cfg or config.get()
    state = state or {}
    ceilings = ceilings or {}
    lim = cfg.limits
    cur = cfg.account.currency
    budget_users = {}
    for c in camps:
        budget_users[c["budget_resource"]] = budget_users.get(c["budget_resource"], 0) + 1

    fails, plan, seen = [], {}, set()
    new_budget, new_status = {}, {}

    def add(kind, resource, field, value, label, item, entity, before, after, topic):
        if (kind, resource, field) in seen:
            fails.append(f"{label}: listed twice")
            return
        seen.add((kind, resource, field))
        p = plan.setdefault((kind, resource), {"fields": {}, "labels": [], "ledger": []})
        p["fields"][field] = value
        p["labels"].append(label)
        level = {"budget": "campaign"}.get(kind, kind)
        p["ledger"].append(ledger.entry(
            level, entity, FIELD_NAMES.get(field, field), before, after,
            item.get("reason") or changes.get("reason", ""), topic, item.get("expected_effect", ""),
            changes.get("routine", "weekly"), day=today))

    def campaign(name):
        return one([c for c in camps if c["name"] == name], f"campaign '{name}'", fails)

    def group(cname, gname):
        return one([g for g in groups if g["campaign"] == cname and g["name"] == gname],
                   f"ad group '{cname} / {gname}'", fails)

    for b in changes.get("budgets", []):
        c = campaign(b.get("campaign"))
        amount = b.get("daily_budget")
        if c is None:
            continue
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
            fails.append(f"budget {c['name']}: daily_budget must be a positive number")
            continue
        if budget_users[c["budget_resource"]] > 1:
            fails.append(f"budget {c['name']}: the budget is shared with another campaign")
            continue
        new = ads_client.micros(amount, cur) / 1e6
        new_budget[c["resource"]] = new
        add("budget", c["budget_resource"], "amount_micros", ads_client.micros(amount, cur),
            f"budget    {c['name']}: {cur} {c['budget']:.2f} -> {new:.2f}", b, c["name"], c["budget"], new, None)

    for b in changes.get("bids", []):
        g = group(b.get("campaign"), b.get("ad_group"))
        bid = b.get("cpc")
        if g is None:
            continue
        where = f"{g['campaign']} / {g['name']}"
        if isinstance(bid, bool) or not isinstance(bid, (int, float)) or bid <= 0:
            fails.append(f"bid {where}: cpc must be a positive number")
            continue
        exp = experiments.holding(g["campaign"], g["name"], today, state, cfg)
        if exp:
            fails.append(f"bid {where}: experiment {exp['id']} holds this bid from {exp['start']} until it is judged "
                         f"(end {exp['end']}); it steps by its own rules and only experiments.py ends it")
            continue
        if daily_bids.managed(g["channel"], g["name"]) and cfg.stepping.enabled and \
                daily_bids.stepping(g["campaign"], g["name"], today, starts):
            fails.append(f"bid {where}: daily_bids.py is still stepping this winning-topic group; change its rules instead")
            continue
        start = daily_bids.week_start_bid(bid_history.get(g["resource"], []), g["bid"])
        new = ads_client.micros(bid, cur) / 1e6
        if start <= 0:
            fails.append(f"bid {where}: no bid at the start of the week to compare with")
            continue
        if abs(new / start - 1) > lim.weekly_bid_change + 1e-9:
            fails.append(f"bid {where}: {cur} {start:.2f} on Monday -> {new:.2f} is {new / start - 1:+.0%}, "
                         f"over the +/-{lim.weekly_bid_change:.0%} weekly limit")
            continue
        ceiling = ceilings.get((g["campaign"], g["name"])) or \
            experiments.group_ceiling(g["campaign"], g["name"], today, state, None, cfg)
        if not lim.bid_floor - 1e-9 <= new <= ceiling + 1e-9:
            fails.append(f"bid {where}: {cur} {new:.2f} is outside {lim.bid_floor:.2f} to {ceiling:.2f}")
            continue
        add("ad_group", g["resource"], "cpc_bid_micros", ads_client.micros(bid, cur),
            f"bid       {where}: {cur} {g['bid']:.2f} -> {new:.2f} (Monday {start:.2f}, {new / start - 1:+.0%})",
            b, where, g["bid"], new, ad_group_topic(g["name"]))

    for s in changes.get("status", []):
        level, status = s.get("level"), s.get("status")
        if status not in STATUSES:
            fails.append(f"status {s}: status must be PAUSED or ENABLED")
            continue
        if level == "campaign":
            c = campaign(s.get("campaign"))
            if c is None:
                continue
            if status == "ENABLED" and c["channel"] == "PERFORMANCE_MAX" and not lim.allow_enable_performance_max:
                fails.append(f"status {c['name']}: enabling a Performance Max campaign is not allowed")
                continue
            new_status[c["resource"]] = status
            add("campaign", c["resource"], "status", status, f"campaign  {c['name']}: {c['status']} -> {status}",
                s, c["name"], c["status"], status, None)
        elif level == "ad_group":
            g = group(s.get("campaign"), s.get("ad_group"))
            if g is not None:
                add("ad_group", g["resource"], "status", status,
                    f"ad group  {g['campaign']} / {g['name']}: {g['status']} -> {status}",
                    s, f"{g['campaign']} / {g['name']}", g["status"], status, ad_group_topic(g["name"]))
        elif level == "keyword":
            text, match = (s.get("keyword") or "").lower(), (s.get("match") or "").upper()
            k = one([k for k in keywords if k["campaign"] == s.get("campaign") and k["ad_group"] == s.get("ad_group")
                     and k["text"].lower() == text and (not match or k["match"] == match)],
                    f"keyword '{s.get('campaign')} / {s.get('ad_group')} / {s.get('keyword')}'"
                    + (f" ({match})" if match else ""), fails)
            if k is not None:
                entity = f"{k['campaign']} / {k['ad_group']} / {k['text']} ({k['match']})"
                add("keyword", k["resource"], "status", status, f"keyword   {entity}: {k['status']} -> {status}",
                    s, entity, k["status"], status, ad_group_topic(k["ad_group"]))
        else:
            fails.append(f"status {s}: level must be campaign, ad_group or keyword")

    def budgets(after):
        """[(campaign, budget resource, amount)] of the enabled campaigns, before or after the change."""
        return [(c["name"], c["budget_resource"], new_budget.get(c["resource"], c["budget"]) if after else c["budget"])
                for c in camps if (new_status.get(c["resource"], c["status"]) if after else c["status"]) == "ENABLED"]

    def total(after):
        """Across enabled campaigns; a shared budget counts once (its amount cannot change here)."""
        return ads_client.budget_total((res, amount) for _, res, amount in budgets(after))

    totals = (total(False), total(True))
    if totals[1] > lim.daily_budget_cap + 1e-9:
        fails.append(f"total daily budget across enabled campaigns would be {cur} {totals[1]:.2f}, "
                     f"over the {cur} {lim.daily_budget_cap:g} cap")
    for e in experiments.reserves(today, state, cfg):
        problem = experiments.reserve_problem(e, experiments.others_total(budgets(False), e["campaign"]),
                                              experiments.others_total(budgets(True), e["campaign"]), cur)
        if problem:
            fails.append(problem)
    return fails, plan, totals


def check(ga, changes):
    camps, groups, keywords = load_account(ga, any(s.get("level") == "keyword" for s in changes.get("status", [])))
    today = ads_client.today()
    monday = today - timedelta(days=today.weekday())
    bid_history = daily_bids.bid_changes(ga, monday, today + timedelta(days=1))
    state = experiments.load_state()
    ceilings = {}
    for b in changes.get("bids", []):
        g = next((g for g in groups if g["campaign"] == b.get("campaign") and g["name"] == b.get("ad_group")), None)
        if g and experiments.needs_market(g["campaign"], g["name"], today, state):
            price, note = market_price.fetch(ga, g["resource"], str(today - timedelta(days=1)),
                                             f"{g['campaign']} / {g['name']}")
            if note:
                print(f"NOTE   {note}")
            ceilings[(g["campaign"], g["name"])] = experiments.group_ceiling(g["campaign"], g["name"], today, state,
                                                                             price)
    return evaluate(changes, camps, groups, keywords, bid_history, daily_bids.window_starts(), today, state=state,
                    ceilings=ceilings)


def operations(client, plan):
    ops, labels = [], []
    for (kind, resource), p in plan.items():
        op = client.get_type("MutateOperation")
        sub = {"budget": op.campaign_budget_operation, "campaign": op.campaign_operation,
               "ad_group": op.ad_group_operation, "keyword": op.ad_group_criterion_operation}[kind]
        sub.update.resource_name = resource
        for field, value in p["fields"].items():
            if field == "status":
                enum = {"campaign": client.enums.CampaignStatusEnum, "ad_group": client.enums.AdGroupStatusEnum,
                        "keyword": client.enums.AdGroupCriterionStatusEnum}[kind]
                value = getattr(enum, value)
            setattr(sub.update, field, value)
            sub.update_mask.paths.append(field)
        ops.append(op)
        labels.append("; ".join(p["labels"]))
    return ops, labels


def main():
    files = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not files:
        sys.exit(__doc__)
    changes = json.loads(Path(files[0]).read_text(encoding="utf-8"))
    validate_only = "--apply" not in sys.argv
    cfg = config.get()
    client = ads_client.load()
    ga = client.get_service("GoogleAdsService")  # keep a reference so the stream isn't closed early

    print(f"{changes.get('date', '?')}: {changes.get('reason', '(no reason given)')}")
    fails, plan, (before, after) = check(ga, changes)
    if fails:
        for line in fails:
            print(f"FAIL   {line}")
        sys.exit(f"Nothing changed: {len(fails)} rule(s) failed.")
    if not plan:
        print("Nothing to change.")
        return

    ops, labels = operations(client, plan)
    print("VALIDATE ONLY (no changes)" if validate_only else "APPLYING CHANGES")
    try:
        with ledger.pending([e for p in plan.values() for e in p["ledger"]], not validate_only):
            ga.mutate(request={"customer_id": ads_client.customer_id(), "mutate_operations": ops,
                               "validate_only": validate_only})
    except GoogleAdsException as ex:
        for e in ex.failure.errors:
            index = next((p.index for p in e.location.field_path_elements if p.field_name == "mutate_operations"), None)
            print(f"FAIL   {labels[index] if index is not None else ''}  <- {e.message}")
        sys.exit(f"Nothing changed: the request is atomic ({len(ops)} operations).")
    for label in labels:
        print(f"{'VALID' if validate_only else 'DONE '}  {label}")
    print(f"total daily budget across enabled campaigns: {cfg.account.currency} {before:.2f} -> {after:.2f} "
          f"(cap {cfg.limits.daily_budget_cap:g})")


if __name__ == "__main__":
    main()
