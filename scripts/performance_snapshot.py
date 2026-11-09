"""Read-only snapshot of account performance, printed as JSON sections.

Usage: uv run scripts/performance_snapshot.py [DAYS]   (default 30, ending yesterday)
"""
import json
import sys
from datetime import timedelta

import ads_client
from google.protobuf.json_format import MessageToDict

METRICS = ("metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions, metrics.conversions_value, "
           "metrics.ctr, metrics.average_cpc")


def queries(where):
    return {
        "account": "SELECT customer.descriptive_name, customer.currency_code, customer.time_zone, customer.auto_tagging_enabled FROM customer",
        "campaigns": f"""SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type,
            campaign.bidding_strategy_type, campaign_budget.amount_micros, {METRICS},
            metrics.search_impression_share, metrics.search_budget_lost_impression_share, metrics.search_rank_lost_impression_share
            FROM campaign WHERE campaign.status != 'REMOVED' AND {where}""",
        # Display vs Search: never judge a Search campaign's traffic from totals alone
        "campaign_networks": f"""SELECT campaign.name, segments.ad_network_type, {METRICS}
            FROM campaign WHERE campaign.status != 'REMOVED' AND {where}""",
        "campaign_daily_networks": f"""SELECT segments.date, campaign.name, segments.ad_network_type, {METRICS}
            FROM campaign WHERE campaign.status = 'ENABLED' AND {where}""",
        "ad_groups": f"""SELECT campaign.name, ad_group.name, ad_group.status, {METRICS}
            FROM ad_group WHERE ad_group.status != 'REMOVED' AND {where}""",
        "keywords": f"""SELECT campaign.name, ad_group.name, ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type,
            ad_group_criterion.status, ad_group_criterion.quality_info.quality_score,
            ad_group_criterion.quality_info.creative_quality_score, ad_group_criterion.quality_info.post_click_quality_score,
            ad_group_criterion.quality_info.search_predicted_ctr, {METRICS}
            FROM keyword_view WHERE ad_group_criterion.status != 'REMOVED' AND {where}""",
        "search_terms": f"""SELECT campaign.name, search_term_view.search_term, search_term_view.status, {METRICS}
            FROM search_term_view WHERE {where} AND metrics.impressions > 0 ORDER BY metrics.cost_micros DESC LIMIT 200""",
        "ads": f"""SELECT campaign.name, ad_group.name, ad_group_ad.ad.id, ad_group_ad.ad.type, ad_group_ad.status,
            ad_group_ad.policy_summary.approval_status, ad_group_ad.ad_strength, ad_group_ad.ad.final_urls, {METRICS}
            FROM ad_group_ad WHERE ad_group_ad.status != 'REMOVED' AND {where}""",
        "conversion_actions": """SELECT conversion_action.name, conversion_action.status, conversion_action.type,
            conversion_action.category, conversion_action.primary_for_goal, conversion_action.counting_type
            FROM conversion_action WHERE conversion_action.status != 'REMOVED'""",
        "conversions_by_action": f"""SELECT campaign.name, segments.conversion_action_name, metrics.all_conversions
            FROM campaign WHERE {where} AND metrics.all_conversions > 0""",
        "daily": f"SELECT segments.date, {METRICS} FROM customer WHERE {where}",
        "devices": f"SELECT segments.device, {METRICS} FROM customer WHERE {where}",
    }


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    end = ads_client.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    client = ads_client.load()
    service = client.get_service("GoogleAdsService")
    out = {"range": [str(start), str(end)], "currency": ads_client.currency()}
    for name, query in queries(f"segments.date BETWEEN '{start}' AND '{end}'").items():
        out[name] = [MessageToDict(type(r).pb(r), preserving_proto_field_name=True) for r in ads_client.rows(service, query)]
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
