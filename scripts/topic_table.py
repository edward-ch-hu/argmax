"""Rolling 90-day topic table: spend, CRM leads, ref-matched leads, wins and trial_to_win per topic. Read-only.

Every topic-level decision (defund, shift spend, judge a topic) uses this view, never one week or one month
against the last (STRATEGY.md, Evidence rules). Spend topics come from ad group names (config: ad_group_topics;
"other" = no topic, e.g. Performance Max); CRM topics from the lead's tags ("none" = no tag). Leads count by lead date.

Usage: uv run scripts/topic_table.py [END_DATE]   (END_DATE defaults to yesterday in the account time zone)
"""
import json
import sys
from datetime import date, timedelta

import ads_client
import crm
import match_ref
from daily_scout import topic_spend
from topics import ad_group_topic

DAYS = 90


def table(spend, crm_rows, matches, start, end):
    """The per-topic table from spend per topic, CRM rows and ref matches (pure, for tests)."""
    total = sum(t["cost"] for t in spend.values())
    leads = [r for r in crm_rows if str(start) <= r["date"] <= str(end)]
    funnels = crm.funnel_by_topic(leads)
    matched = {}
    for e in matches:
        if e["status"] == "matched" and str(start) <= e["date"] <= str(end):
            matched.setdefault(ad_group_topic(e["clicks"][0]["ad_group"], "other"), set()).add(e["fp"])
    out = {}
    for t in sorted(set(spend) | set(funnels) | set(matched)):
        cost, f = spend.get(t, {}).get("cost", 0.0), funnels.get(t, {})
        out[t] = {"spend": round(cost, 2), "spend_share": round(cost / total, 3) if total else None,
                  "leads": f.get("leads", 0), "ref_matched_leads": len(matched.get(t, ())),
                  "wins": f.get("won", 0), "trial_to_win": f.get("trial_to_win")}
    return out


def rolling(ga, client, crm_rows, end, days=DAYS):
    start = end - timedelta(days=days - 1)
    spend = topic_spend(ga, f"segments.date BETWEEN '{start}' AND '{end}'")
    leads = [r for r in crm_rows if str(start) <= r["date"] <= str(end)]
    out = {"range": [str(start), str(end)], "days": days, "currency": ads_client.currency(),
           "by_topic": table(spend, crm_rows, match_ref.match(client, leads), start, end)}
    if not crm.enabled():
        out["note"] = "crm.source is none: spend only, no leads or wins"
    return out


def main():
    end = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else ads_client.today() - timedelta(days=1)
    client = ads_client.load()
    ga = client.get_service("GoogleAdsService")  # keep a reference so the stream isn't closed early
    print(json.dumps(rolling(ga, client, crm.load(), end), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
