"""Daily exact-match negatives for junk search terms (the daily scout's step 2c).

keyword_review.py's NEGATIVE rule and thresholds on the negatives.lookback_days (default 7) of Google Search traffic
ending DATE (default yesterday), per campaign and search term (summed over its ad groups, since the negative is
campaign-level). No positives, pauses or Keyword Planner ideas: keyword_review.py runs in the weekly for those.
- adds EXACT campaign negatives, through apply_keyword_review.apply() (the weekly's mutation code)
- never a winning-topic term without a junk word: those go to held_winning for the weekly
- at most negatives.max_per_day per run day, highest cost first (what the ledger already holds for today counts)
- skips a term the campaign already blocks (a campaign negative, or a negative in a shared list it uses, with the
  same text in any match type) and a term whose daily negative was undone (ledger), so a re-run never adds twice
Only applies on yesterday's data; an older DATE prints the plan but never applies (like daily_bids.py).
With --apply: each added negative goes to reports/changes.jsonl (ledger.py, routine "daily", with campaign, text,
cost and clicks), and the day in reports/daily/week-<MONDAY>.json gets a "negatives" section (run after
daily_scout.py): added, held_winning, over_cap. Prints NOTIFY NEG when it added something and NOTIFY NEG_HELD when
a held term costing negatives.held_notify_cost+ is new since the previous recorded day.

undo: removes a campaign's EXACT negative (the weekly's way to reverse a wrong one) and logs it to the ledger;
the daily never adds that term to that campaign again.

Usage: uv run scripts/daily_negatives.py [DATE]          (validate only)
       uv run scripts/daily_negatives.py [DATE] --apply  (makes the change)
       uv run scripts/daily_negatives.py undo "<term>" --campaign "<name>" [--reason "<why>"] [--apply]
"""
import json
import sys
from datetime import date, timedelta

import ads_client
import config
import ledger
from ads_client import rows
from apply_keyword_review import apply
from daily_scout import previous_day, read, week_path
from google.ads.googleads.errors import GoogleAdsException
from keyword_review import money, negative_rule, search_campaigns, search_terms
from topics import main_topic


def norm(text):
    return " ".join(text.lower().strip('"[]+').split())


def blocked(ga, campaigns):
    """{campaign id: negative keyword texts} from its own negatives and the shared negative lists it uses."""
    ids = ",".join(map(str, campaigns))
    out = {cid: set() for cid in campaigns}
    for r in rows(ga, f"""SELECT campaign.id, campaign_criterion.keyword.text FROM campaign_criterion
            WHERE campaign.id IN ({ids}) AND campaign_criterion.type = 'KEYWORD' AND campaign_criterion.negative = TRUE
            AND campaign_criterion.status != 'REMOVED'"""):
        out[r.campaign.id].add(norm(r.campaign_criterion.keyword.text))
    users = {}
    for r in rows(ga, f"""SELECT campaign.id, shared_set.id FROM campaign_shared_set WHERE campaign.id IN ({ids})
            AND campaign_shared_set.status = 'ENABLED' AND shared_set.type = 'NEGATIVE_KEYWORDS'"""):
        users.setdefault(r.shared_set.id, []).append(r.campaign.id)
    if users:
        for r in rows(ga, f"""SELECT shared_set.id, shared_criterion.keyword.text FROM shared_criterion
                WHERE shared_set.id IN ({",".join(map(str, users))}) AND shared_criterion.type = 'KEYWORD'"""):
            for cid in users[r.shared_set.id]:
                out[cid].add(norm(r.shared_criterion.keyword.text))
    return out


def daily_lines(run_day=None, entries=None):
    """Ledger lines of daily negatives: all of them, or those added on `run_day`."""
    return [e for e in ledger.read(entries=entries) if e.get("routine") == "daily" and e.get("field") == "negative"
            and e.get("after") and (run_day is None or e["date"] == str(run_day))]


def undone(entries=None):
    return {(e.get("campaign"), norm(e.get("text", ""))) for e in ledger.read(entries=entries)
            if e.get("field") == "negative" and e.get("after") is None}


def select(terms, have, gone, added_today, cfg=None):
    """The selection rule (pure, for tests). terms: {(campaign id, normalised text): {campaign, ad_group, text,
    cost, clicks, conversions, ...}} summed over the window; have: {campaign id: blocked texts}; gone: {(campaign
    name, text)} undone by the weekly; added_today: daily negatives already in the ledger today.
    Returns (to_add, held, over_cap, skipped), each highest cost first."""
    cfg = cfg or config.get()
    candidates, held, skipped = [], [], []
    for (cid, text), row in terms.items():
        negative = negative_rule(row["text"], row["cost"], row["clicks"], row["conversions"], cfg)
        if not negative:
            continue
        reason, topic, is_held = negative
        if is_held:
            held.append({**row, "topic": topic, "reason": reason})
        elif text in have.get(cid, set()) or (row["campaign"], text) in gone:
            skipped.append({**row, "reason": "already blocked" if text in have.get(cid, set()) else "undone by the weekly"})
        else:
            candidates.append({**row, "match": "EXACT", "reason": reason, "approve": True})
    for group in (candidates, held, skipped):
        group.sort(key=lambda r: -r["cost"])
    room = max(0, cfg.negatives.max_per_day - added_today)
    return candidates[:room], held, candidates[room:], skipped


def plan(client, day, run_day):
    """Returns (to_add, held, over_cap, skipped) rows, highest cost first."""
    cfg = config.get()
    ga = client.get_service("GoogleAdsService")  # keep a reference so the stream isn't closed early
    campaigns = search_campaigns(ga)
    if not campaigns:
        return [], [], [], []
    end = date.fromisoformat(day)
    period = f"segments.date BETWEEN '{end - timedelta(days=cfg.negatives.lookback_days - 1)}' AND '{end}'"
    sums = {}
    for row, m in sorted(search_terms(ga, campaigns, period), key=lambda x: -x[1].cost_micros):
        t = sums.setdefault((row["campaign_id"], norm(row["text"])), {**row, "micros": 0, "clicks": 0, "conv": 0.0})
        t["micros"] += m.cost_micros
        t["clicks"] += m.clicks
        t["conv"] += m.conversions
    terms = {}
    for key, t in sums.items():
        micros, conv = t.pop("micros"), t.pop("conv")
        terms[key] = {**t, "cost": money(micros), "conversions": round(conv, 1)}
    return select(terms, blocked(ga, campaigns), undone(), len(daily_lines(run_day)), cfg)


def run(day, apply_changes):
    cfg = config.get()
    cur = cfg.account.currency
    run_day = ads_client.today()
    yesterday = str(run_day - timedelta(days=1))
    validate_only = not apply_changes or day != yesterday
    if apply_changes and day != yesterday:
        print(f"{day} is not yesterday: plan only, nothing applied")
    client = ads_client.load()
    to_add, held, over_cap, skipped = plan(client, day, run_day)
    for r in held:
        print(f"HELD  {r['campaign']} / {r['ad_group']}: [{r['text']}] {cur} {r['cost']:.2f}, {r['clicks']} clicks "
              f"({r['topic']}, for the weekly)")
    for r in skipped:
        print(f"SKIP  {r['campaign']}: [{r['text']}] {cur} {r['cost']:.2f} ({r['reason']})")
    for r in over_cap:
        print(f"WAIT  {r['campaign']}: [{r['text']}] {cur} {r['cost']:.2f} (over the {cfg.negatives.max_per_day} a day cap)")
    for r in to_add:
        print(f"ADD   {r['campaign']} / {r['ad_group']}: [{r['text']}] {cur} {r['cost']:.2f}, {r['clicks']} clicks "
              f"({r['reason']})")
    if not to_add:
        print("Nothing to add.")
    annotate = lambda r: {k: r[k] for k in ("campaign", "text", "cost", "clicks")}  # noqa: E731
    done = apply(client, {"negatives": to_add}, validate_only, routine="daily", annotate=annotate) if to_add else []
    if validate_only:
        return
    entries = [e for _, e in done]  # apply() logged them to the ledger

    path = week_path(day)
    week = read(path)
    if week and day in week["days"]:
        week["days"][day]["negatives"] = {
            "window": f"{date.fromisoformat(day) - timedelta(days=cfg.negatives.lookback_days - 1)} to {day}",
            "added": [{k: e[k] for k in ("campaign", "text", "cost", "clicks", "reason")} for e in daily_lines(run_day)],
            "held_winning": [{k: r[k] for k in ("campaign", "ad_group", "text", "topic", "cost", "clicks")} for r in held],
            "over_cap": [{k: r[k] for k in ("campaign", "text", "cost", "clicks")} for r in over_cap]}
        path.write_text(json.dumps(week, ensure_ascii=False, indent=1))
    else:
        print(f"NOTIFY ALERT daily_negatives: {day} is missing from {path}; run daily_scout.py first")
    if entries:
        top = ", ".join(e["text"] for e in sorted(entries, key=lambda e: -e["cost"])[:3])
        print(f"NOTIFY NEG added {len(entries)}: {cur} {sum(e['cost'] for e in entries):.2f} in "
              f"{cfg.negatives.lookback_days} days ({top})")
    big = [r for r in held if r["cost"] >= cfg.negatives.held_notify_cost]
    before = {(r["campaign"], norm(r["text"])) for r in
              ((previous_day(day) or {}).get("negatives") or {}).get("held_winning", [])
              if r["cost"] >= cfg.negatives.held_notify_cost}
    if any((r["campaign"], norm(r["text"])) not in before for r in big):
        print(f"NOTIFY NEG_HELD {len(big)} winning-topic terms left for the weekly")


def undo(term, campaign, reason, validate_only):
    client = ads_client.load()
    ga = client.get_service("GoogleAdsService")  # keep a reference so the stream isn't closed early
    found = [r for r in rows(ga, """SELECT campaign.name, campaign_criterion.resource_name, campaign_criterion.keyword.text
            FROM campaign_criterion WHERE campaign_criterion.type = 'KEYWORD' AND campaign_criterion.negative = TRUE
            AND campaign_criterion.keyword.match_type = 'EXACT' AND campaign_criterion.status != 'REMOVED'
            AND campaign.status != 'REMOVED'""")
             if r.campaign.name == campaign and norm(r.campaign_criterion.keyword.text) == norm(term)]
    if len(found) != 1:
        sys.exit(f"FAIL  {campaign}: [{term}]: {'no exact negative' if not found else f'{len(found)} matches'}")
    crit = found[0].campaign_criterion
    op = client.get_type("CampaignCriterionOperation")
    op.remove = crit.resource_name
    print("VALIDATE ONLY (no changes)" if validate_only else "APPLYING CHANGES")
    text = crit.keyword.text
    entry = {**ledger.entry("keyword", f"{campaign} (campaign negative) / {text}", "negative", "EXACT", None,
                            reason, main_topic(text), "buyer searches can show the ads again"),
             "campaign": campaign, "text": text}
    try:
        with ledger.pending([entry], not validate_only):
            client.get_service("CampaignCriterionService").mutate_campaign_criteria(
                request={"customer_id": ads_client.customer_id(), "operations": [op], "validate_only": validate_only})
    except GoogleAdsException as ex:
        sys.exit(f"FAIL  {campaign}: [{text}] <- " + "; ".join(e.message for e in ex.failure.errors))
    print(f"{'VALID' if validate_only else 'DONE '}  remove negative  {campaign}: [{text}]")


def main():
    args = sys.argv[1:]
    validate_only = "--apply" not in args

    def option(name):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None

    if args and args[0] == "undo":
        if len(args) < 2 or not option("--campaign"):
            sys.exit(__doc__)
        undo(args[1], option("--campaign"), option("--reason") or "undo: blocked buyer intent", validate_only)
        return
    days = [a for a in args if not a.startswith("--")]
    run(days[0] if days else str(ads_client.today() - timedelta(days=1)), not validate_only)


if __name__ == "__main__":
    main()
