"""Market price: what Google says it costs to win the top spot for an ad group's keywords.

The price is Google's first-position CPC estimate per keyword (ad_group_criterion.position_estimates
.first_position_cpc_micros; the top-of-page estimate when a keyword has no first-position one), weighted by each
keyword's impressions over the 30 days to the data day. A group with no impressions, or keywords with no estimate,
has no market price (None).

It is only ever used as a ceiling, and always under market_price.safety_limit (the hard cap against a bad estimate):
ceiling = min(safety_limit, max(market price, or market_price.fallback when there is none, limits.bid_floor)).
fallback defaults to limits.bid_ceiling. Used by experiments with `ceiling: market` and by the winning groups in
market_price.groups for normal daily stepping (daily_bids.py), and by apply_changes.py for weekly bids on them.

When Google refuses the query (an access level or a field that is not available to the project), fetch() returns
None and a NOTE line, and the ceiling falls back: the run goes on.
"""
from datetime import date, timedelta

import ads_client
import config
from google.ads.googleads.errors import GoogleAdsException

DAYS = 30


def query(ad_group_resource, day):
    start = date.fromisoformat(str(day)) - timedelta(days=DAYS - 1)
    return f"""SELECT ad_group_criterion.position_estimates.first_position_cpc_micros,
        ad_group_criterion.position_estimates.top_of_page_cpc_micros, metrics.impressions FROM keyword_view
        WHERE ad_group.resource_name = '{ad_group_resource}' AND ad_group_criterion.status = 'ENABLED'
        AND ad_group_criterion.negative = FALSE AND segments.date BETWEEN '{start}' AND '{day}'"""


def weighted(estimates):
    """The impression-weighted price from [(first position micros, top of page micros, impressions)], or None. Pure."""
    total = weight = 0
    for first, top, impressions in estimates:
        price = (first or top or 0) / 1e6
        if price and impressions:
            total += price * impressions
            weight += impressions
    return round(total / weight, 2) if weight else None


def market_price(ga, ad_group_resource, day):
    """The group's market price over the 30 days to `day` (the data day), or None."""
    found = []
    for r in ads_client.rows(ga, query(ad_group_resource, day)):
        est = r.ad_group_criterion.position_estimates
        found.append((est.first_position_cpc_micros, est.top_of_page_cpc_micros, r.metrics.impressions))
    return weighted(found)


def fetch(ga, ad_group_resource, day, label=""):
    """(price or None, note or None). A refused query is a note, never a failure."""
    try:
        return market_price(ga, ad_group_resource, day), None
    except GoogleAdsException as ex:
        cfg = config.get()
        fallback = cfg.market_price.fallback if cfg.market_price.fallback is not None else cfg.limits.bid_ceiling
        return None, (f"market price unavailable{' for ' + label if label else ''} "
                      f"({ads_client.error_text(ex)}): the ceiling falls back to {fallback:.2f}")


def ceiling(market, cfg=None):
    """The bid ceiling a market price allows: never over market_price.safety_limit, never under limits.bid_floor."""
    cfg = cfg or config.get()
    m, lim = cfg.market_price, cfg.limits
    fallback = m.fallback if m.fallback is not None else lim.bid_ceiling
    price = market if market else fallback
    return round(min(m.safety_limit, max(price, lim.bid_floor)), 2)


def listed(campaign, ad_group, cfg=None):
    """True for a group in market_price.groups (normal stepping up to the market price)."""
    cfg = cfg or config.get()
    return {"campaign": campaign, "ad_group": ad_group} in cfg.market_price.groups
