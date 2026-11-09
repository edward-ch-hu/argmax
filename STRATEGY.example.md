# Strategy

Copy a template from `strategies/` (or this file) to `STRATEGY.md` and make it yours. The routines read it every
run; `uv run scripts/strategy_check.py` checks that the sections below exist and that target shares add up.
Limits (budget cap, bid limits) live in `argmax.yaml`, not here: this file says where to go, the config says how
fast the agent may move. The business profile (`business:` in `argmax.yaml`: goal, KPI, markets, report language,
deal currency) says what the owner wants; this file does not restate it.

Fits goals: leads

Bidding end state: smart bidding hand-off | agent-run manual CPC (permanent)
- smart bidding hand-off: the last phase hands bids to Google's Smart Bidding. Fits high conversion volume and clean
  conversion data that Google can learn from.
- agent-run manual CPC (permanent): bids stay Manual CPC for good, set by the routines and judged on real deals
  offline. Fits low volume or noisy conversions.
Keep one choice on the line above; it must match `business.bidding_end_state` in argmax.yaml (smart_bidding or
manual_cpc; `strategy_check.py` and `doctor.py` check). With manual CPC the routines never propose a bid strategy
switch, and a winning group capped by its bid can get a ceiling test instead (README, "Experiments").

## Goal
The business goal lives in the profile in `argmax.yaml` (`business.goal`, `business.goal_description`); this
section only says how this strategy pursues it: find which topics, keywords and campaigns produce real deals, then
move spend there at the same total budget. (For the fictional Acme Analytics the profile says: goal leads, "Trials
that turn into paid plans, at the same total budget".)

## Success signal
- Counts: `business.primary_kpi` (here: real CRM leads and wins, `crm.source`), tied to ads by ref codes when
  `ref_codes.enabled`.
- Leading signals only: the conversion actions in `conversions.lead_signals` (e.g. Demo Request, Signup).
- Noise, never used for any judgment: `conversions.noise_signals` (e.g. Chat Widget Open). Shown in tables only.

## Evidence rules
- No topic or campaign is defunded on outcome data below a floor: spend of at least 500 x the account's average
  Search CPC (onboarding writes the amount here, from `init.py --derive`; about 1,500 at a CPC of 3) over at least 60
  days with 0 CRM or ref-matched leads. Below the floor, cut waste on spend-side data only (off-intent
  search terms, CPC, impressions lost to budget).
- Topics are judged on the rolling 90-day table (`uv run scripts/topic_table.py`: spend, leads, ref-matched leads,
  wins, trial_to_win), never month against month.
- 0 leads in one week is not evidence.
- Noise signals are excluded from every judgment.

## Topic spend targets
Share of ad spend per topic. TBD until the first set gets a human "yes"; then write the shares here and add
"approved YYYY-MM-DD" to this paragraph.

| Topic | Target share |
|---|---|
| analytics | TBD |
| dashboards | TBD |
| reporting | TBD |
| other | TBD |

How targets change after the first approval:
- The monthly review proposes updates from the rolling 90-day topic table.
- Small update (no topic moves more than 10 percentage points from the approved targets, shares sum to 100): an
  "Unless you say no" decision. Silence applies it after its due date: the weekly edits this table and logs it.
- Bigger move: "Needs yes"; silence means no change.
The weekly moves budgets and bids toward the approved shares inside the configured limits.

## Phases
### Phase 1: clean data (about 3 weeks)
- Google Search only (Display Expansion and Search Partners off), remarketing on visitor lists only.
- Manual CPC; ad group bids from 30-day Search CPCs. Weekly keyword review blocks waste and adds winners.
- Winning-topic groups are stepped daily by `daily_bids.py` toward the rank-lost band, then settle.
- Do not change bidding strategy mid-phase. Only bids (within the weekly limit) and keywords change.

Exit check, per campaign:
| Metric | Keep going | Rethink |
|---|---|---|
| Search impression share | rising week on week | flat under 10% at the bid ceiling |
| Real leads (CRM, ref-matched) | any from this campaign | none and over 500 spent |
| Cost per lead signal (leading only) | stable or falling | rising 2 weeks in a row |

### Phase 2: optimise on the data
- Raise bids on keywords converting above their ad group average; pause keywords with spend and no conversions.
- Move winning search terms to exact match in their own ad group.
- Ad copy tests run through `ad_test.py` (one new test a week at most, winning-topic groups first).

Exit check: a campaign has 30+ lead signals or real CRM leads in 30 days.

### Phase 3: the bidding end state (keep the variant picked above, delete the other)
Smart bidding hand-off:
- Upload real leads as offline conversions (by click id) so bidding learns from deals, not clicks.
- Never optimise for a noise signal. Bid for lead signals and uploaded leads, then Target CPA at the Phase 2 CPA.
- Set `guard.expected_bidding` to the new strategy and `stepping.enabled: false` for those campaigns' groups.

Agent-run manual CPC (permanent):
- Bids stay Manual CPC, set by `daily_bids.py` and the weekly on CRM and ref-matched leads, never on Google's
  conversion counts. No routine proposes switching a bid strategy.
- A winning group that loses most impressions to rank at its bid ceiling can get a ceiling test (an experiment,
  "Needs yes" to start) to find where extra bid stops buying clicks.

Either way: keep auto-apply recommendations off; review Google's suggestions by hand.

## Agent autonomy overrides
None: the defaults in AGENTS.md apply. Write stricter or looser rules here (still inside `argmax.yaml` limits),
e.g. "no new keywords in the UK campaign without a yes" or "the agent may pause remarketing on its own".

## Change log
- YYYY-MM-DD: created from STRATEGY.example.md.
