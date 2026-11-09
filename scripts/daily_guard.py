"""Read-only daily guardrail check. Changes nothing. Prints one line per alert, or "OK" when all checks pass.

Usage: uv run scripts/daily_guard.py [DATE]   (DATE defaults to yesterday, YYYY-MM-DD)

Checks (the day, ENABLED campaigns; thresholds from adgrad.yaml):
- auto-apply recommendation subscriptions are all off
- Search campaigns have Display Expansion and Search Partners off and got no Display (CONTENT) traffic
  (guard.search_networks_only)
- the total daily budget across enabled campaigns is at or under limits.daily_budget_cap
- every enabled campaign uses guard.expected_bidding (skipped when null) and is eligible to serve
- Search campaigns got Search impressions; no campaign spent over guard.overspend_multiple x its daily budget
- any lead-signal conversion (conversions.lead_signals) is reported as news: check the CRM for a real lead
"""
import sys
from collections import defaultdict
from datetime import timedelta

import ads_client
import config
from ads_client import rows
from google.ads.googleads.errors import GoogleAdsException


def budget_alerts(total, cfg=None):
    cap = (cfg or config.get()).limits.daily_budget_cap
    return [f"Total daily budget {ads_client.currency()} {total:.2f} is over the {cap:g} cap"] if total > cap + 1e-9 else []


def check(client, day):
    """Returns (alerts, news, total_daily_budget) for one day."""
    cfg = config.get()
    g = cfg.guard
    ga = client.get_service("GoogleAdsService")  # keep a reference so the stream isn't closed early
    alerts, news = [], []
    cur = ads_client.currency()

    subs = rows(ga, "SELECT recommendation_subscription.resource_name, recommendation_subscription.type "
                    "FROM recommendation_subscription WHERE recommendation_subscription.status = 'ENABLED'")
    for r in subs:
        if not r.recommendation_subscription.resource_name.endswith("/UNKNOWN"):
            alerts.append(f"Auto-apply is ON: {r.recommendation_subscription.type_.name}")

    campaigns = rows(ga, """SELECT campaign.name, campaign.advertising_channel_type, campaign.bidding_strategy_type,
        campaign.primary_status, campaign.network_settings.target_content_network,
        campaign.network_settings.target_partner_search_network, campaign_budget.amount_micros
        FROM campaign WHERE campaign.status = 'ENABLED'""")
    budget = {}
    total = 0.0
    for r in campaigns:
        c = r.campaign
        budget[c.name] = r.campaign_budget.amount_micros / 1e6
        total += budget[c.name]
        if g.expected_bidding and c.bidding_strategy_type.name != g.expected_bidding:
            alerts.append(f"{c.name}: bidding is {c.bidding_strategy_type.name}, expected {g.expected_bidding}")
        if c.primary_status.name not in ("ELIGIBLE", "LIMITED"):
            alerts.append(f"{c.name}: status {c.primary_status.name}")
        if g.search_networks_only and c.advertising_channel_type.name == "SEARCH":
            if c.network_settings.target_content_network:
                alerts.append(f"{c.name}: Display Expansion is ON")
            if c.network_settings.target_partner_search_network:
                alerts.append(f"{c.name}: Search Partners is ON")
    alerts += budget_alerts(total, cfg)

    stats = rows(ga, f"""SELECT campaign.name, campaign.advertising_channel_type, segments.ad_network_type,
        metrics.impressions, metrics.cost_micros FROM campaign
        WHERE campaign.status = 'ENABLED' AND segments.date = '{day}'""")
    impr = defaultdict(lambda: defaultdict(int))
    spend = defaultdict(float)
    for r in stats:
        impr[r.campaign.name][r.segments.ad_network_type.name] += r.metrics.impressions
        spend[r.campaign.name] += r.metrics.cost_micros / 1e6
    for r in campaigns:
        name = r.campaign.name
        if r.campaign.advertising_channel_type.name != "SEARCH":
            continue
        if g.search_networks_only and impr[name]["CONTENT"]:
            alerts.append(f"{name}: {impr[name]['CONTENT']} Display impressions on {day}")
        if not impr[name]["SEARCH"]:
            alerts.append(f"{name}: 0 Google Search impressions on {day}")
    for name, cost in spend.items():
        if name in budget and cost > g.overspend_multiple * budget[name]:
            alerts.append(f"{name}: spent {cur} {cost:.2f} on {day}, over {g.overspend_multiple:g}x its "
                          f"{cur} {budget[name]:.2f} budget")

    conv = rows(ga, f"""SELECT campaign.name, segments.conversion_action_name, metrics.all_conversions FROM campaign
        WHERE segments.date = '{day}' AND segments.conversion_action_name IN {ads_client.quoted(cfg.conversions.lead_signals)}
        AND metrics.all_conversions > 0""")
    for r in conv:
        news.append(f"{r.campaign.name}: {r.metrics.all_conversions:g} {r.segments.conversion_action_name} on {day} "
                    "(check for a real lead)")

    return alerts, news, total


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else str(ads_client.today() - timedelta(days=1))
    alerts, news, total = check(ads_client.load(), day)
    for line in alerts:
        print("ALERT " + line)
    for line in news:
        print("NEWS  " + line)
    if not alerts and not news:
        print(f"OK    {day}: all checks passed (total budget {ads_client.currency()} {total:.2f})")


if __name__ == "__main__":
    try:
        main()
    except GoogleAdsException as ex:
        sys.exit("FAIL " + "; ".join(e.message for e in ex.failure.errors))
