"""Monthly review numbers: read-only on the Google Ads account. Writes reports/monthly/<YYYY-MM>.json and prints it.

One rule for every month, recomputed from scratch each run so history stays consistent:
- spend:         metrics.cost_micros per segments.month (account currency, account time zone)
- new customers: CRM rows with stage "win" whose lead date is in the month; new value = the sum of their deal value
                 (crm.deal_value_label, e.g. MRR, in business.deal_currency; the line names that currency when it
                 is not the account currency)
- ROI:           first-month deal value x crm.deal_value_fx / spend (not lifetime return). "at least" when the
                 month's leads still have open rows (talking or trial) that could still win.
- funnel:        crm.funnel() per month (talking, trial, won, lost after / without a trial, and the rates)
History starts at report.history_start (YYYY-MM), or 11 months before the report month when unset.
Revisions are months whose numbers differ from the previous month's report (late CRM wins or deal value edits).
crm_stale is true when the CRM's last entry is over crm.stale_after_days old. warnings lists wins logged with no
deal value (date and fingerprint only). month.this.ref_matched ties the month's leads to ad clicks through their
ref codes (match_ref.py; only with ref_codes.enabled). rolling_90d_by_topic is topic_table.py's 90-day view up to
the month end, the only view topic decisions use. client_summary has the last 3 months and the year to date,
worded for the client update. change_audit checks the changes in reports/changes.jsonl (ledger.py):
- this_month: changes applied in the month, with their topic's spend share 4 weeks before vs after
- judged: changes whose 6-week lead window has closed and whose 10-week win window is still open or closed
  this month: the topic's CRM leads, ref-matched leads and wins before vs after (same length each side)
- not_yet_observable: changes whose lead window is still open
With crm.source none the report has spend, campaigns, topics and the change audit's spend side only.

Usage: uv run scripts/monthly_report.py [--month YYYY-MM]
Without --month it reports the previous month (account time zone), the one that just ended when it runs on the 1st.
Prints NOTIFY NO_BASELINE <month> when there is no report for the month before to compare with.
"""
import calendar
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import ads_client
import config
import crm
import ledger
import match_ref
import topic_table
from ads_client import rows
from daily_scout import topic_spend
from topics import ad_group_topic

OUT_DIR = Path("reports/monthly")
FIELDS = ("spend", "leads", "open_leads", "wins", "new_value")
NOISE_NOTE = ("At a few real leads a week, lead counts before vs after one change are noisy: read them as a hint, "
              "not proof, and judge topics on the rolling 90-day table.")


def month_range(month):
    first = date.fromisoformat(f"{month}-01")
    return first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def prev_month(month):
    return str(month_range(month)[0] - timedelta(days=1))[:7]


def months(start, end):
    out = [start]
    while out[-1] < end:
        out.append(str(month_range(out[-1])[1] + timedelta(days=1))[:7])
    return out


def history_start(report_month, cfg=None):
    hs = (cfg or config.get()).report.history_start
    if hs:
        return min(str(hs), report_month)
    m = report_month
    for _ in range(11):
        m = prev_month(m)
    return m


def roi(value, spend, fx):
    return round(value * fx / spend, 2) if spend else None


def line(h, label=None, cfg=None):
    """One plain-English line for a month (or the year to date): spend, customers, new value, first-month ROI."""
    cfg = cfg or config.get()
    cur, value_label = cfg.account.currency, cfg.crm.deal_value_label
    if cfg.business.deal_currency != cur:
        value_label = f"{value_label} {cfg.business.deal_currency}"
    label = label or f"{calendar.month_name[int(h['month'][5:7])]} {h['month'][:4]}"
    text = f"{label}: spent {cur} {h['spend']:,.0f}"
    if not crm.enabled(cfg):
        return text
    if h["wins"]:
        at_least = "at least " if h["open_leads"] else ""
        r = "n/a" if h["roi"] is None else f"{h['roi']:g}x"
        text += (f", {h['wins']} new customer{'s' if h['wins'] != 1 else ''}, {at_least}new {value_label} "
                 f"{h['new_value']:,.0f}, first-month ROI {r}")
    elif h["open_leads"]:
        text += f", no deal closed yet ({h['open_leads']} lead{'s' if h['open_leads'] != 1 else ''} still open)"
    else:
        text += ", 0 new customers"
    if h.get("revised"):
        text += " (revised since the last report)"
    if h.get("crm_stale"):
        text += " (CRM not updated yet)"
    return text


def month_history(spend, crm_rows, month_list, fx):
    """One row per month from spend {YYYY-MM: amount} and CRM rows (pure, for tests)."""
    out = []
    for m in month_list:
        leads = [r for r in crm_rows if r["date"][:7] == m]
        wins = [r for r in leads if r["stage"] == "win"]
        h = {"month": m, "spend": spend.get(m, 0.0), "leads": len(leads),
             "open_leads": sum(r["stage"] == "open" for r in leads), "wins": len(wins),
             "new_value": round(sum(r["mrr"] for r in wins), 2)}
        h["roi"] = roi(h["new_value"], h["spend"], fx)
        h["funnel"] = crm.funnel(leads)
        out.append(h)
    return out


def history(ga, crm_rows, report_month):
    _, end = month_range(report_month)
    start = history_start(report_month)
    spend = {r.segments.month[:7]: round(r.metrics.cost_micros / 1e6, 2) for r in rows(ga, f"""SELECT segments.month,
        metrics.cost_micros FROM customer WHERE segments.date BETWEEN '{start}-01' AND '{end}'""")}
    return month_history(spend, crm_rows, months(start, report_month), config.get().crm.deal_value_fx)


def revisions(hist, previous):
    old = {h["month"]: h for h in previous["history"]} if previous else {}
    out = []
    for h in hist:
        o = old.get(h["month"])
        if not o:
            continue
        changes = {f: [o.get(f), h[f]] for f in FIELDS if abs((o.get(f) or 0) - (h[f] or 0)) >= 0.01}
        if changes:
            out.append({"month": h["month"], "changes": changes})
    return out


def campaigns(ga, first, last):
    where = f"segments.date BETWEEN '{first}' AND '{last}'"
    out, total = {}, 0
    for r in rows(ga, f"""SELECT campaign.name, campaign.status, metrics.cost_micros, metrics.clicks,
            metrics.impressions, metrics.conversions FROM campaign WHERE {where}"""):
        total += r.metrics.cost_micros
        if r.metrics.impressions or r.metrics.cost_micros or r.metrics.conversions:
            out[r.campaign.name] = {"status": r.campaign.status.name, "cost": round(r.metrics.cost_micros / 1e6, 2),
                                    "clicks": r.metrics.clicks, "impressions": r.metrics.impressions,
                                    "conversions": round(r.metrics.conversions, 1), "conversions_by_action": {}}
    for r in rows(ga, f"""SELECT campaign.name, segments.conversion_action_name, metrics.conversions
            FROM campaign WHERE {where} AND metrics.conversions > 0"""):
        if r.campaign.name in out:  # lead signals and noise signals apart; noise is shown, never judged on
            out[r.campaign.name]["conversions_by_action"][r.segments.conversion_action_name] = round(r.metrics.conversions, 1)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["cost"])), round(total / 1e6, 2)


def client_summary(hist, month, cfg=None):
    """The last 3 months and the year to date, worded for the client update."""
    cfg = cfg or config.get()
    ytd_months = [h for h in hist if h["month"][:4] == month[:4]]
    ytd = {"month": f"{month[:4]}-ytd", "spend": round(sum(h["spend"] for h in ytd_months), 2),
           "wins": sum(h["wins"] for h in ytd_months), "open_leads": sum(h["open_leads"] for h in ytd_months),
           "new_value": round(sum(h["new_value"] for h in ytd_months), 2),
           "revised": False, "crm_stale": any(h.get("crm_stale") for h in ytd_months)}
    ytd["roi"] = roi(ytd["new_value"], ytd["spend"], cfg.crm.deal_value_fx)
    since = calendar.month_name[int(ytd_months[0]["month"][5:7])] if ytd_months else ""
    return {"last_3_months": [line(h, cfg=cfg) for h in hist[-3:]],
            "year_to_date": line(ytd, f"{month[:4]} to date (from {since})", cfg)}


def change_audit(ga, client, crm_rows, month, today, entries=None):
    first, last = month_range(month)
    spend_cache = {}

    def share(topic, start, end):
        if topic == "mixed" or end < start:
            return None
        if (start, end) not in spend_cache:
            spend_cache[(start, end)] = topic_spend(ga, f"segments.date BETWEEN '{start}' AND '{end}'")
        spend = spend_cache[(start, end)]
        total = sum(t["cost"] for t in spend.values())
        return round(spend.get(topic, {}).get("cost", 0.0) / total, 3) if total else None

    def outcome(topic, start, end):
        if not crm.enabled():
            return None
        leads = [r for r in crm_rows if str(start) <= r["date"] <= str(end) and (topic == "mixed" or topic in r["topics"])]
        matched = {e["fp"] for e in match_ref.match(client, leads) if e["status"] == "matched"
                   and topic in ("mixed", ad_group_topic(e["clicks"][0]["ad_group"]))}
        return {"leads": len(leads), "ref_matched_leads": len(matched), "wins": sum(r["stage"] == "win" for r in leads)}

    groups = {}
    for e in ledger.read() if entries is None else entries:
        groups.setdefault((e["date"], e["topic"]), []).append(e)
    out = {"note": NOISE_NOTE, "this_month": [], "judged": [], "not_yet_observable": []}
    for (day, topic), group in sorted(groups.items()):
        if day > str(last):
            continue
        d, e0 = date.fromisoformat(day), group[0]
        changes = [{k: e[k] for k in ("level", "entity", "field", "before", "after", "expected_effect")} for e in group]
        if str(first) <= day <= str(last):
            after_end = min(d + timedelta(days=27), today - timedelta(days=1))
            out["this_month"].append({"date": day, "topic": topic, "changes": changes,
                                      "spend_share_before": share(topic, d - timedelta(days=28), d - timedelta(days=1)),
                                      "spend_share_after": share(topic, d, after_end),
                                      "days_after": max((after_end - d).days + 1, 0)})
        if str(today) < e0["judge_leads_after"]:
            out["not_yet_observable"].append({"date": day, "topic": topic, "changes": len(group),
                                              "judge_leads_after": e0["judge_leads_after"]})
        elif e0["judge_wins_after"] >= str(first) and crm.enabled():
            lead_days, win_days = ledger.LEADS_AFTER.days, ledger.WINS_AFTER.days
            row = {"date": day, "topic": topic, "changes": changes,
                   "leads_window_days": lead_days,
                   "before": outcome(topic, d - timedelta(days=lead_days), d - timedelta(days=1)),
                   "after": outcome(topic, d, d + timedelta(days=lead_days - 1))}
            if str(today) >= e0["judge_wins_after"]:
                row["wins_window_days"] = win_days
                row["wins_before"] = outcome(topic, d - timedelta(days=win_days), d - timedelta(days=1))["wins"]
                row["wins_after"] = outcome(topic, d, d + timedelta(days=win_days - 1))["wins"]
            else:
                row["wins_after"] = f"not yet observable (after {e0['judge_wins_after']})"
            out["judged"].append(row)
    return out


def ref_matched(matches):
    """The month's leads whose ref code matched exactly one ad click, by campaign / ad group / keyword."""
    out = {"leads": 0, "wins": 0, "value": 0.0, "by_campaign": {}, "by_ad_group": {}, "by_keyword": {},
           "ambiguous": [], "not_found": 0}
    counted = set()
    for e in matches:
        if e["status"] == "ambiguous":
            out["ambiguous"].append({k: e[k] for k in ("date", "stage", "topics", "code", "clicks")})
            continue
        if e["status"] == "not_found" or e["fp"] in counted:
            out["not_found"] += e["status"] == "not_found"
            continue
        counted.add(e["fp"])
        c, win = e["clicks"][0], e["stage"] == "win"
        keyword = c["keyword"] or "(no keyword)"
        for key, name in (("by_campaign", c["campaign"]), ("by_ad_group", f"{c['campaign']} / {c['ad_group']}"),
                          ("by_keyword", f"{c['campaign']} / {c['ad_group']} / {keyword}"), (None, None)):
            b = out[key].setdefault(name, {"leads": 0, "wins": 0, "value": 0.0}) if key else out
            b["leads"] += 1
            b["wins"] += win
            b["value"] = round(b["value"] + (e["mrr"] if win else 0), 2)
    return out


def detail(ga, client, crm_rows, month):
    first, last = month_range(month)
    leads = [r for r in crm_rows if r["date"][:7] == month]
    wins = [r for r in leads if r["stage"] == "win"]
    camps, spend = campaigns(ga, first, last)
    topics = dict(sorted(topic_spend(ga, f"segments.date BETWEEN '{first}' AND '{last}'").items()))
    out = {"month": month, "range": [str(first), str(last)], "spend": spend, "campaigns": camps,
           "spend_by_topic": topics,  # by ad group; Performance Max has no ad groups, see spend_outside_ad_groups
           "spend_outside_ad_groups": round(spend - sum(t["cost"] for t in topics.values()), 2)}
    if crm.enabled():
        out.update({"crm": {"leads": len(leads), "open": sum(r["stage"] == "open" for r in leads), "wins": len(wins),
                            "value": round(sum(r["mrr"] for r in wins), 2),
                            "wins_list": [{k: r[k] for k in ("date", "topics", "mrr")} for r in wins]},
                    "crm_by_topic": crm.by_topic(leads),
                    "funnel": crm.funnel(leads), "funnel_by_topic": crm.funnel_by_topic(leads)})
    if match_ref.enabled():
        out["ref_fill"] = crm.ref_fill(leads)
        out["ref_matched"] = ref_matched(match_ref.match(client, leads))
    return out


def main():
    cfg = config.get()
    now = ads_client.now()
    month = sys.argv[sys.argv.index("--month") + 1] if "--month" in sys.argv else prev_month(now.strftime("%Y-%m"))

    client = ads_client.load()
    ga = client.get_service("GoogleAdsService")  # keep a reference so the stream isn't closed early
    crm_rows = crm.load()
    prev_path = OUT_DIR / f"{prev_month(month)}.json"
    previous = json.loads(prev_path.read_text()) if prev_path.exists() else None
    last = crm.last_entry(crm_rows)
    days_since = (now.date() - date.fromisoformat(last)).days if last else None
    stale = crm.enabled() and (days_since is None or days_since > cfg.crm.stale_after_days)

    hist = history(ga, crm_rows, month)
    revs = revisions(hist, previous)
    revised = {r["month"] for r in revs}
    for h in hist:
        h["revised"] = h["month"] in revised
        h["crm_stale"] = bool(stale and (last is None or str(month_range(h["month"])[1]) > last))
        h["line"] = line(h, cfg=cfg)
    warnings = [{"warning": "win with no deal value", "date": r["date"], "fp": r["fp"]} for r in crm_rows
                if r["stage"] == "win" and r["mrr_missing"] and hist[0]["month"] <= r["date"][:7] <= month]

    out = {"report_month": month, "generated": now.isoformat(timespec="minutes"), "currency": cfg.account.currency,
           "crm_source": cfg.crm.source, "deal_value_label": cfg.crm.deal_value_label,
           "deal_currency": cfg.business.deal_currency, "deal_value_fx": cfg.crm.deal_value_fx,
           "compared_with": str(prev_path) if previous else None, "crm_stale": stale,
           "history": hist, "revisions": revs, "warnings": warnings,
           "client_summary": client_summary(hist, month, cfg),
           "rolling_90d_by_topic": topic_table.rolling(ga, client, crm_rows, month_range(month)[1]),
           "change_audit": change_audit(ga, client, crm_rows, month, now.date()),
           "month": {"this": detail(ga, client, crm_rows, month),
                     "previous": detail(ga, client, crm_rows, prev_month(month))},
           "crm": {"last_entry": last, "days_since_last_entry": days_since}}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(out, ensure_ascii=False, indent=1)
    (OUT_DIR / f"{month}.json").write_text(text)
    print(text)
    if previous is None:
        print(f"NOTIFY NO_BASELINE {prev_month(month)}: no report to compare with, revisions not checked")


if __name__ == "__main__":
    main()
