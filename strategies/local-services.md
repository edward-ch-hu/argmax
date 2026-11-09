# Strategy: local services

For a business that serves a local area and wins customers by phone calls and contact forms (trades, clinics,
studios, repair shops). Small budgets, so waste matters more than scale. The loop: right place, right hours,
calls and forms that turn into booked jobs.

Fits goals: calls, leads

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

### Phase 3: Smart Bidding on calls and forms
- Maximize Conversions on lead signals, then Target CPA. Update `guard.expected_bidding`, turn stepping off.

## Agent autonomy overrides
- Stricter: no location or ad schedule change without a "yes" (the owner knows the area and hours).
- Stricter: budget shifts only between campaigns in the same city.

## Change log
- YYYY-MM-DD: created from strategies/local-services.md.
