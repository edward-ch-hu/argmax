# Strategy: new account discovery

For a fresh account (or a messy inherited one) with no trustworthy history. The loop: clean data first, discover
broadly on Search, tighten fast on what the search terms show, and only then decide what wins.

Fits goals: leads, sales, roas, calls

Config to match: `guard.expected_bidding: MANUAL_CPC`, `guard.search_networks_only: true`, a conservative
`limits.daily_budget_cap`, `winning_topics: []` at first (no daily stepping until a topic shows deals),
`ad_tests.enabled: false` until groups reach the impression floor.

## Goal
The business goal lives in the profile in `argmax.yaml` (`business.goal`, `business.goal_description`); this
section only says how this strategy pursues it: learn which searches bring real customers within 6 to 8 weeks,
spending as little as possible on junk while doing it.

## Success signal
- Counts: `business.primary_kpi` (real leads or sales from the CRM or the store), however few.
- Leading signals only: `conversions.lead_signals`.
- Noise, never judged on: everything else, including Google's auto-created engagement goals.

## Evidence rules
- Nothing is cut on outcome data in the first 4 weeks; cut waste on spend-side data only (junk terms, CPC, off-intent).
- A topic becomes "winning" (added to `winning_topics`) after its first real deal; the weekly proposes it.
- Judge topics on the rolling 90-day table once 4 weeks of data exist.

## Topic spend targets
TBD until discovery shows where deals come from (usually after Phase 2).

| Topic | Target share |
|---|---|
| topic_a | TBD |
| topic_b | TBD |
| other | TBD |

## Phases
### Phase 1: clean setup (1 week)
- Conversions: one primary lead or purchase action; everything else secondary. Auto-apply recommendations off.
- Search only, Manual CPC, one campaign per language or region, one ad group per topic, phrase match keywords.
- Exit check: `daily_guard.py` prints OK for 3 days in a row.

### Phase 2: broad discovery (3 to 4 weeks)
- Add a few broad match keywords per topic to discover searches; daily junk negatives keep them honest.
- Weekly keyword review adds converting terms as phrase; the monthly match type review tightens noisy broad ones.
- Exit check: at least one topic with a real deal, or 4 weeks passed.

### Phase 3: tighten and pick winners
- Move to the B2B lead-gen or e-commerce strategy template; set `winning_topics` and topic spend targets.

## Agent autonomy overrides
- Stricter: no new campaigns without a "yes".
- Looser: the agent may add phrase match keywords from converting search terms without waiting for review.

## Change log
- YYYY-MM-DD: created from strategies/new-account-discovery.md.
