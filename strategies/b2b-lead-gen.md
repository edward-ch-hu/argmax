# Strategy: B2B lead generation

For a business that sells through a sales conversation (SaaS, agencies, B2B services) and logs leads and deals in
a CRM. The loop: find the topics that produce real deals, move spend there, cut waste everywhere else, and never
let a noisy conversion steer the account. This is argmax's home turf.

Fits goals: leads

Bidding end state: smart bidding hand-off | agent-run manual CPC (permanent)
- smart bidding hand-off: the last phase hands bids to Google's Smart Bidding. Fits high conversion volume and clean
  conversion data that Google can learn from.
- agent-run manual CPC (permanent): bids stay Manual CPC for good, set by the routines and judged on real deals
  offline. Fits low volume or noisy conversions.
Keep one choice on the line above; it must match `business.bidding_end_state` in argmax.yaml (smart_bidding or
manual_cpc; `strategy_check.py` and `doctor.py` check). With manual CPC the routines never propose a bid strategy
switch, and a winning group capped by its bid can get a ceiling test instead (README, "Experiments").

Config to match: `crm.source` set, `winning_topics` = the topics with wins, `stepping.enabled: true`,
`guard.expected_bidding: MANUAL_CPC` (until a smart bidding hand-off, if that is the end state),
`business.bidding_end_state` as picked above, optionally `ref_codes.enabled: true`.

## Goal
The business goal lives in the profile in `argmax.yaml` (`business.goal`, `business.goal_description`); this
section only says how this strategy pursues it: find which topics, keywords and campaigns produce real CRM deals,
then move spend there at the same total budget.

## Success signal
- Counts: `business.primary_kpi` (here: CRM leads and wins, `crm.statuses.won`), ref-matched to clicks where
  possible.
- Leading signals only: `conversions.lead_signals` (form submits, demo requests, signups); `business.kpi_conversions`
  are the ones that stand for the KPI.
- Noise, never judged on: `conversions.noise_signals` (chat opens, button clicks, page-view goals).

## Evidence rules
- No topic or campaign is defunded on outcome data below a floor: spend of at least 500 x the account's average
  Search CPC (onboarding writes the amount here, from `init.py --derive`; about 1,500 at a CPC of 3) over at least 60
  days with 0 CRM or ref-matched leads. Below the floor, cut waste on spend-side data only (off-intent
  search terms, CPC, impressions lost to budget).
- Topics are judged on the rolling 90-day table (`scripts/topic_table.py`), never month against month.
- 0 leads in one week is not evidence. At a few leads a week, before/after counts around one change are a hint.
- Noise signals are excluded from every judgment.

## Topic spend targets
TBD until the first set gets a human "yes" (the monthly proposes it from the 90-day table). Then write the shares
here and add "approved YYYY-MM-DD".

| Topic | Target share |
|---|---|
| topic_a | TBD |
| topic_b | TBD |
| other | TBD |

After the first approval: updates within 10 percentage points per topic (summing to 100) are "Unless you say no";
bigger moves are "Needs yes".

## Phases
### Phase 1: clean data (about 3 weeks)
- Search only (Display Expansion and Search Partners off). Manual CPC. Remarketing on visitor lists only.
- Weekly keyword review; daily junk negatives; daily bid steps on winning-topic groups.
- Exit check per campaign: impression share rising, or any real lead; rethink when no lead and over 500 spent, or
  impression share flat under 10% at the bid ceiling.

### Phase 2: optimise on the data
- Raise bids on keywords converting above their group average; pause keywords with spend and no conversions.
- Winning search terms to exact match in their own ad group. Ad copy tests on winning-topic groups first.
- Exit check: a campaign has 30+ lead signals or real CRM leads in 30 days.

### Phase 3: the bidding end state (keep the variant picked above, delete the other)
Smart bidding hand-off:
- Upload real leads as offline conversions (click id) so bidding learns from deals.
- Bid for lead signals and uploaded leads (Target CPA at the Phase 2 CPA), never for a noise signal.
- Set `guard.expected_bidding` to the new strategy and `stepping.enabled: false` for those campaigns' groups.

Agent-run manual CPC (permanent), the usual fit at a few real leads a week:
- Bids stay Manual CPC, set by `daily_bids.py` and the weekly on CRM and ref-matched leads, not on Google's
  conversion counts. No routine proposes switching a bid strategy.
- A winning group capped by its bid (most impressions lost to rank at the ceiling) can get a ceiling test, an
  experiment that starts only after a "yes".

## Agent autonomy overrides
None: AGENTS.md defaults apply.

## Change log
- YYYY-MM-DD: created from strategies/b2b-lead-gen.md.
