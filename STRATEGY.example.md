# Strategy

Copy a template from `strategies/` (or this file) to `STRATEGY.md` and make it yours. The routines read it every
run; `uv run scripts/strategy_check.py` checks that the sections below exist and that target shares add up.
Limits (budget cap, bid limits) live in `argmax.yaml`, not here: this file says where to go, the config says how
fast the agent may move.

## Goal
Find which topics, keywords and campaigns produce real deals, then move spend there. Example for the fictional
Acme Analytics: grow trials that convert to paid plans, at the same total budget.

## Success signal
- Counts: real CRM leads and wins (`crm.source`), tied to ads by ref codes when `ref_codes.enabled`.
- Leading signals only: the conversion actions in `conversions.lead_signals` (e.g. Demo Request, Signup).
- Noise, never used for any judgment: `conversions.noise_signals` (e.g. Chat Widget Open). Shown in tables only.

## Evidence rules
- No topic or campaign is defunded on outcome data below a floor: at least 1,500 (account currency) spent over at
  least 60 days with 0 CRM or ref-matched leads. Below the floor, cut waste on spend-side data only (off-intent
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

### Phase 3: Smart Bidding
- Upload real leads as offline conversions (by click id) so bidding learns from deals, not clicks.
- Never optimise for a noise signal. Bid for lead signals and uploaded leads, then Target CPA at the Phase 2 CPA.
- Keep auto-apply recommendations off; review Google's suggestions by hand.

## Agent autonomy overrides
None: the defaults in AGENTS.md apply. Write stricter or looser rules here (still inside `argmax.yaml` limits),
e.g. "no new keywords in the UK campaign without a yes" or "the agent may pause remarketing on its own".

## Change log
- YYYY-MM-DD: created from STRATEGY.example.md.
