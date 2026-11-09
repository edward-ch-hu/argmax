# Strategy: e-commerce, return on ad spend

For an online store where the purchase happens on the site and carries a value. The loop: group spend by product
category, find the categories that return the most conversion value per unit of spend, move budget there, and keep
the account inside the cap.

Fits goals: roas, sales

Bidding end state: smart bidding hand-off | agent-run manual CPC (permanent)
- smart bidding hand-off: the last phase hands bids to Google's Smart Bidding. Fits high conversion volume and clean
  conversion data that Google can learn from.
- agent-run manual CPC (permanent): bids stay Manual CPC for good, set by the routines and judged on real deals
  offline. Fits low volume or noisy conversions.
Keep one choice on the line above; it must match `business.bidding_end_state` in argmax.yaml (smart_bidding or
manual_cpc; `strategy_check.py` and `doctor.py` check). With manual CPC the routines never propose a bid strategy
switch, and a winning group capped by its bid can get a ceiling test instead (README, "Experiments").

Config to match: `conversions.lead_signals: [Purchase]` (your purchase action), topics = product categories,
`crm.source: none` (Google Ads holds the value) or a CSV of orders if you track margin elsewhere,
`ad_tests.enabled` only if product pages carry stable claims. argmax's topic table is lead-centric: read ROAS from
`metrics.conversions_value` in `scripts/performance_snapshot.py` or `scripts/gaql.py` per ad group.

## Goal
The business goal lives in the profile in `argmax.yaml` (`business.goal`, `business.goal_description`); this
section only says how this strategy pursues it: maximise conversion value per unit of spend (ROAS) across
categories at or under the budget cap, without starving categories that are still learning.

## Success signal
- Counts: `business.primary_kpi` (here: purchase value, and orders, per category from Google Ads
  `conversions_value` of `business.kpi_conversions`).
- Leading signals only: add-to-cart, begin-checkout (keep them secondary in Google Ads).
- Noise, never judged on: page-view or engagement goals.

## Evidence rules
- A category is not cut on value data until it has spent at least 30x its average order value over at least 30 days.
- Judge categories on a rolling 30-day window (purchase cycles are short), never on one week.
- Seasonal categories are compared with the same season, not the previous month.
- Returns and refunds: if you track them, judge on net value; otherwise note that ROAS is gross.

## Topic spend targets
TBD until the first set gets a human "yes".

| Topic | Target share |
|---|---|
| category_a | TBD |
| category_b | TBD |
| category_c | TBD |
| other | TBD |

## Phases
### Phase 1: clean feed and data (2 weeks)
- Check that the purchase conversion fires once per order with the right value. Search and Shopping only.
- Daily junk negatives; weekly keyword review. Manual CPC or Maximize Clicks with a CPC cap.
- Exit check: purchase value in Google Ads within 10% of the store's own revenue for ad-attributed orders.

### Phase 2: shift budget by ROAS
- Each week move budget from the lowest-ROAS categories to the highest, inside the weekly limits.
- Pause keywords and products with spend over 3x average order value and no purchase.
- Exit check: 50+ purchases in 30 days per campaign.

### Phase 3: the bidding end state (keep the variant picked above, delete the other)
Smart bidding hand-off (value-based), the usual fit for a store with steady purchases:
- Switch campaigns with enough purchases to Maximize Conversion Value, then Target ROAS at the Phase 2 ROAS.
- Set `guard.expected_bidding` accordingly and `stepping.enabled: false` (Smart Bidding sets the bids).

Agent-run manual CPC (permanent), for a small catalogue or few purchases a month:
- Bids stay Manual CPC; the weekly keeps moving budget and bids toward the categories with the best ROAS. No
  routine proposes switching a bid strategy.

## Agent autonomy overrides
- Stricter: no bidding strategy change without a "yes" (it resets learning).
- Looser: the agent may pause a product category ad group with zero purchases at 5x average order value spent.

## Change log
- YYYY-MM-DD: created from strategies/ecommerce-roas.md.
