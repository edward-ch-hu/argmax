# Strategy: local services

For a business that serves a local area and wins customers by phone calls and contact forms (trades, clinics,
studios, repair shops). Small budgets, so waste matters more than scale. The loop: right place, right hours,
calls and forms that turn into booked jobs.

Fits goals: calls, leads

Bidding end state: smart bidding hand-off | agent-run manual CPC (permanent)
- smart bidding hand-off: the last phase hands bids to Google's Smart Bidding. Fits high conversion volume and clean
  conversion data that Google can learn from.
- agent-run manual CPC (permanent): bids stay Manual CPC for good, set by the routines and judged on real deals
  offline. Fits low volume or noisy conversions.
Keep one choice on the line above; it must match `business.bidding_end_state` in argmax.yaml (smart_bidding or
manual_cpc; `strategy_check.py` and `doctor.py` check). With manual CPC the routines never propose a bid strategy
switch, and a winning group capped by its bid can get a ceiling test instead (README, "Experiments").

Config to match: `conversions.lead_signals: [Calls from ads, Contact Form]` (your actions), topics = services,
a small `limits.daily_budget_cap`, `crm.source: csv` with a simple booked-jobs sheet if you have one.

## Goal
The business goal lives in the profile in `argmax.yaml` (`business.goal`, `business.goal_description`); this
section only says how this strategy pursues it: get booked jobs from the service area (`business.markets`) at a
cost per job the business can afford, inside a tight daily budget.

## Success signal
- Counts: `business.primary_kpi` (here: booked jobs from the CRM or a simple sheet, and calls over 60 seconds).
- Leading signals only: contact form submits, all calls from ads.
- Noise, never judged on: direction clicks, website visits, short calls under 30 seconds.

## Evidence rules
- A service is not cut on outcome data until it has spent at least 10x the target cost per job over 45 days.
- Judge on a rolling 60-day table; small volumes swing week to week.
- Calls outside opening hours count as missed opportunities, not as ad failures.

## Topic spend targets
TBD until the first set gets a human "yes".

| Topic | Target share |
|---|---|
| service_a | TBD |
| service_b | TBD |
| emergency | TBD |
| other | TBD |

## Phases
### Phase 1: right place, right hours (2 weeks)
- Location targeting "presence" (people in the area), not "interest". Ad schedule = opening hours (plus emergency
  hours if offered). Search only. Call extensions on.
- Daily junk negatives with local junk words added to `negatives.junk_words` (jobs, salary, course, DIY).
- Exit check: under 10% of clicks from outside the service area; calls answered in opening hours.

### Phase 2: cost per job
- Shift budget to the services and hours with the lowest cost per booked job.
- Pause keywords with spend over 2x target cost per job and no lead signal.
- Exit check: 20+ booked jobs or calls over 60 seconds in 30 days.

### Phase 3: the bidding end state (keep the variant picked above, delete the other)
Smart bidding hand-off on calls and forms:
- Maximize Conversions on lead signals, then Target CPA. Update `guard.expected_bidding`, turn stepping off.

Agent-run manual CPC (permanent), when calls are few or many are not real jobs:
- Bids stay Manual CPC, judged on booked jobs. No routine proposes switching a bid strategy.

## Agent autonomy overrides
- Stricter: no location or ad schedule change without a "yes" (the owner knows the area and hours).
- Stricter: budget shifts only between campaigns in the same city.

## Change log
- YYYY-MM-DD: created from strategies/local-services.md.
