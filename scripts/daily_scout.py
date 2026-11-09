"""Daily scout: read-only on the Google Ads account. Adds the day to reports/daily/week-<MONDAY>.json for the weekly.

One file per Monday-to-Sunday week, filed by the date of the data (so Monday's run, which covers Sunday, completes
last week's file before the Monday review). Each run adds or replaces its own day, so re-running a day is safe.

Sections:
- guard: the daily_guard checks (alerts and news)
- crm:   CRM rows that are new or changed stage since the previous daily file (no names or emails), and, with ref
         codes on, the fill rate of the last 14 days' leads (ref_fill_14d). Skipped when crm.source is none.
- hunt:  the day's search terms that match a winning topic, search terms with a lead-signal conversion
         (conversions.lead_signals), and spend / clicks / lead signals per topic
- refs:  CRM leads with an ad click ref code and the click it matches (match_ref.py, which also saves the day's
         clicks to reports/daily/clicks/). Only with ref_codes.enabled.
Prints one NOTIFY line per thing worth a comment on the weekly report (ALERT, NEWS, WIN, REF, CRM quiet for
crm.stale_after_days+ days, REF_GAP: leads in the last 14 days and none with a ref code, at most once per 7 days),
or "QUIET". After recording the day it checks that every earlier day of the week and the previous Sunday are on
file, and backfills a missing day the same way (NOTIFY MISSED). Bids are not backfilled.

Usage: uv run scripts/daily_scout.py [DATE]   (DATE defaults to yesterday, YYYY-MM-DD)
"""
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import ads_client
import config
import crm
import daily_guard
import match_ref
from ads_client import rows
from topics import ad_group_topic, main_topic, winning

OUT_DIR = Path("reports/daily")


def week_path(day, out_dir=None):
    monday = date.fromisoformat(day) - timedelta(days=date.fromisoformat(day).weekday())
    return (out_dir or OUT_DIR) / f"week-{monday}.json"


def read(path):
    return json.loads(path.read_text()) if path.exists() else None


def crm_baseline(day, week):
    """CRM stages as they were before `day`, or None (first run, or a backfill of an older day)."""
    if week and week.get("crm_stages_date") == day:
        return week.get("crm_stages_prev")  # re-run of the same day
    if week and week.get("crm_stages_date", "") < day:
        return week.get("crm_stages")
    if week is None:
        earlier = sorted(p for p in OUT_DIR.glob("week-*.json") if p.stem < week_path(day).stem)
        prev = read(earlier[-1]) if earlier else None
        if prev and prev.get("crm_stages_date", "") < day:
            return prev.get("crm_stages")
    return None


def previous_day(day, week=None):
    """The entry of the latest recorded day before `day` (`week` = its week file if already read), or None."""
    for w in (week or read(week_path(day)), *(read(p) for p in sorted(OUT_DIR.glob("week-*.json"), reverse=True)
                                              if p.stem < week_path(day).stem)):
        earlier = [d for d in sorted((w or {}).get("days", {}), reverse=True) if d < day]
        if earlier:
            return w["days"][earlier[0]]
    return None


def previous_refs(day, week):
    """Ref codes in the CRM as of the latest earlier day on file, or None if there is no earlier day."""
    prev = previous_day(day, week)
    return None if prev is None else {r["code"] for r in prev.get("refs", [])}


def days_quiet(entry):
    last = (entry.get("crm") or {}).get("last_entry")
    return (date.fromisoformat(entry["date"]) - date.fromisoformat(last)).days if last else None


def crm_quiet_alert(out, prev, stale_days=None):
    """Alert at stale_days without a CRM entry and every 7 days after. A missed run doesn't skip it: the alert also
    fires when the previous recorded day had not reached this 7-day step yet."""
    stale_days = stale_days or config.get().crm.stale_after_days
    days = days_quiet(out)
    if days is None:
        return False
    prev_days = days_quiet(prev) if prev and prev.get("crm") else None
    prev_step = (prev_days // 7) if prev_days is not None else 0
    return days >= stale_days and (days % 7 == 0 or prev_step < days // 7)


def missing_days(day):
    """Days before `day` in its week, plus the previous Sunday, that have no entry."""
    d = date.fromisoformat(day)
    monday = d - timedelta(days=d.weekday())
    wanted = [str(monday - timedelta(days=1))] + [str(monday + timedelta(days=i)) for i in range(d.weekday())]
    return [x for x in wanted if x not in (read(week_path(x)) or {}).get("days", {})]


def crm_diff(current, seen):
    """(new rows, rows whose stage changed) against the baseline {fp: stage}; nothing when there is no baseline."""
    new, changed = [], []
    if seen is None:
        return new, changed
    for r in current:
        public = {k: r[k] for k in ("date", "stage", "topics", "mrr")}
        if r["fp"] not in seen:
            new.append(public)
        elif seen[r["fp"]] != r["stage"]:
            changed.append({**public, "from": seen[r["fp"]]})
    return new, changed


def crm_section(day, week):
    current = crm.load()
    seen = crm_baseline(day, week)
    new, changed = crm_diff(current, seen)
    stages = {r["fp"]: r["stage"] for r in current}
    out = {"rows": len(current), "last_entry": crm.last_entry(current), "new": new, "changed": changed,
           "compared": seen is not None}
    if config.get().ref_codes.enabled:
        out["ref_fill_14d"] = crm.ref_fill(current, str(date.fromisoformat(day) - timedelta(days=13)), day)
    return out, stages, seen


def ref_gap_alert(out, prev):
    """True when the last 14 days have leads and none carries a ref code, and REF_GAP last fired 7+ days ago."""
    fill = (out.get("crm") or {}).get("ref_fill_14d")
    if not fill:
        return False
    last = ((prev or {}).get("crm") or {}).get("ref_gap_alerted")
    fire = bool(fill["leads"]) and not fill["with_ref"] and (
        not last or (date.fromisoformat(out["date"]) - date.fromisoformat(last)).days >= 7)
    out["crm"]["ref_gap_alerted"] = out["date"] if fire else last
    return fire


def topic_spend(ga, date_filter):
    """Cost / clicks / impressions per topic (by ad group name), e.g. date_filter "segments.date = '2026-01-01'"."""
    by_topic = defaultdict(lambda: {"cost": 0.0, "clicks": 0, "impressions": 0})
    for r in rows(ga, f"""SELECT campaign.name, ad_group.name, metrics.cost_micros, metrics.clicks, metrics.impressions
            FROM ad_group WHERE {date_filter} AND metrics.impressions > 0"""):
        t = by_topic[ad_group_topic(r.ad_group.name, "other")]
        t["cost"] = round(t["cost"] + r.metrics.cost_micros / 1e6, 2)
        t["clicks"] += r.metrics.clicks
        t["impressions"] += r.metrics.impressions
    return by_topic


def hunt_section(client, day):
    ga = client.get_service("GoogleAdsService")  # keep a reference so the stream isn't closed early
    by_topic = topic_spend(ga, f"segments.date = '{day}'")
    wins = winning()

    terms = []
    for r in rows(ga, f"""SELECT campaign.name, ad_group.name, search_term_view.search_term, metrics.impressions,
            metrics.clicks, metrics.cost_micros FROM search_term_view
            WHERE segments.date = '{day}' AND metrics.impressions > 0"""):
        topic = main_topic(r.search_term_view.search_term)
        if topic in wins:
            terms.append({"term": r.search_term_view.search_term, "topic": topic, "campaign": r.campaign.name,
                          "ad_group": r.ad_group.name, "impressions": r.metrics.impressions,
                          "clicks": r.metrics.clicks, "cost": round(r.metrics.cost_micros / 1e6, 2)})
    terms.sort(key=lambda t: (-t["clicks"], -t["impressions"]))

    lead_terms = []
    signals = ads_client.quoted(config.get().conversions.lead_signals)
    for r in rows(ga, f"""SELECT campaign.name, ad_group.name, search_term_view.search_term,
            segments.conversion_action_name, metrics.all_conversions FROM search_term_view
            WHERE segments.date = '{day}' AND segments.conversion_action_name IN {signals}
            AND metrics.all_conversions > 0"""):
        lead_terms.append({"term": r.search_term_view.search_term, "campaign": r.campaign.name,
                           "ad_group": r.ad_group.name, "action": r.segments.conversion_action_name,
                           "conversions": r.metrics.all_conversions})
        t = by_topic[ad_group_topic(r.ad_group.name, "other")]
        t["lead_signals"] = t.get("lead_signals", 0) + r.metrics.all_conversions
    return {"by_topic": dict(by_topic), "winning_terms": terms[:50], "lead_signal_terms": lead_terms}


def record(client, day):
    """Adds or replaces `day` in its week file. Returns (the day's entry, the week, its path, NOTIFY lines)."""
    cfg = config.get()
    alerts, news, total = daily_guard.check(client, day)
    path = week_path(day)
    week = read(path)
    out = {"date": day, "guard": {"alerts": alerts, "news": news, "total_budget": total}}
    stages = baseline = None
    if crm.enabled():
        out["crm"], stages, baseline = crm_section(day, week)
    out["hunt"] = hunt_section(client, day)
    seen_refs = None
    if match_ref.enabled():
        match_ref.collect_missing(client, day)
        out["refs"] = match_ref.match(client)
        seen_refs = previous_refs(day, week)
    prev = previous_day(day, week)
    ref_gap = ref_gap_alert(out, prev)
    if week is None:
        monday = date.fromisoformat(path.stem.removeprefix("week-"))
        week = {"week_start": str(monday), "week_end": str(monday + timedelta(days=6)), "days": {}}
    week["days"][day] = out
    week["days"] = dict(sorted(week["days"].items()))
    if stages is not None and week.get("crm_stages_date", "") <= day:  # a backfill of an older day doesn't move it
        if week.get("crm_stages_date") != day:
            week["crm_stages_prev"] = baseline
        week["crm_stages"], week["crm_stages_date"] = stages, day
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(week, ensure_ascii=False, indent=1))

    notify = [f"ALERT {a}" for a in alerts] + [f"NEWS  {n}" for n in news]
    if "crm" in out:
        notify += [f"WIN   CRM {r['date']}: {', '.join(r['topics']) or 'no topic'}, "
                   f"{cfg.crm.deal_value_label} {r['mrr']:g}"
                   for r in out["crm"]["new"] + out["crm"]["changed"] if r["stage"] == "win"]
        if crm_quiet_alert(out, prev):
            notify.append(f"ALERT CRM has no new entries for {days_quiet(out)} days (last {out['crm']['last_entry']}); "
                          "ask whoever logs leads to update it")
    for r in out.get("refs", []):
        if seen_refs is not None and r["code"] not in seen_refs:
            where = "; ".join(f"{c['campaign']} / {c['ad_group']} / {c['keyword'] or '(no keyword)'}, clicked "
                              f"{c['click_date']}" for c in r["clicks"])
            notify.append(f"REF   CRM {r['date']} ({', '.join(r['topics']) or 'no topic'}, {r['stage']}) "
                          f"{r['code']}: {r['status']}" + (f": {where}" if where else ""))
    if ref_gap:
        f = out["crm"]["ref_fill_14d"]
        notify.append(f"REF_GAP {f['leads']} CRM lead(s) since {f['since']}, none with a ref code; ask sales to paste "
                      f"the ({cfg.ref_codes.prefix}...) code from the lead's message into the CRM")
    return out, week, path, notify


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else str(ads_client.today() - timedelta(days=1))
    client = ads_client.load()
    out, week, path, notify = record(client, day)
    for missed in missing_days(day):
        record(client, missed)
        notify.append(f"MISSED {missed}: no entry, backfilled")
    print(f"Wrote {day} into {path} ({len(week['days'])} of 7 days)")
    w = out["hunt"]["by_topic"]
    cur = ads_client.currency()
    print("Topics: " + "; ".join(f"{k} {cur} {v['cost']:.2f} / {v['clicks']} clicks" for k, v in sorted(w.items())))
    print(f"Winning-topic search terms: {len(out['hunt']['winning_terms'])}; "
          + (f"new CRM rows: {len(out['crm']['new'])}; changed: {len(out['crm']['changed'])}; "
             if "crm" in out else "CRM: none configured; ")
          + f"leads with a ref code: {len(out.get('refs', []))}")
    for line in notify:
        print("NOTIFY " + line)
    if not notify:
        print("QUIET")


if __name__ == "__main__":
    main()
